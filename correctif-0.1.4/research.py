import ipaddress, socket, urllib.parse, hashlib, json
import httpx
from .core import secret, normalize, ReviewNeeded, runs, DATA, read
from .schemas import Candidates,Dossier,FactReview,Verdict
from difflib import SequenceMatcher

def safe_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme not in ("http","https") or not p.hostname or p.username or p.password or p.port not in (None,80,443):
        raise ValueError("URL non publique")
    for a in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=="https" else 80),type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(a[4][0]).is_global: raise ValueError("Adresse reseau privee refusee")
    return url

def fetch_text(url):
    import trafilatura
    # Sans cookies, authentification ou proxy utilisateur. Redirections revalidees.
    with httpx.Client(timeout=25,follow_redirects=False,trust_env=False) as client:
        for _ in range(5):
            safe_url(url)
            with client.stream("GET",url,headers={"User-Agent":"AutoShortResearch/0.1"}) as r:
                if r.status_code in (301,302,303,307,308):
                    url=urllib.parse.urljoin(url,r.headers.get("location","")); continue
                r.raise_for_status()
                if not any(t in r.headers.get("content-type","") for t in ("text/html","text/plain")):
                    raise ValueError("Source non textuelle")
                chunks=[]; length=0
                for chunk in r.iter_bytes():
                    length+=len(chunk)
                    if length>2_000_000: raise ValueError("Page trop volumineuse")
                    chunks.append(chunk)
                html=b"".join(chunks).decode(r.encoding or "utf-8",errors="replace")
                text=trafilatura.extract(html,include_comments=False,include_tables=False) or ""
                if len(text)<250: raise ValueError("Page sans texte exploitable")
                return {"url":url,"text":text[:4500]}
    raise ValueError("Trop de redirections")

def search(ctx,query):
    # Reutiliser une recherche identique de ce run, y compris les fichiers de v0.1.
    for cached in sorted((ctx.path/'search').glob('*.json')):
        try:
            previous=read(cached)
            if previous.get('query')==query:return previous['results']
        except (ValueError,KeyError,OSError):continue
    ctx.spend("search")
    key=secret("BRAVE_API_KEY")
    if not key: raise ReviewNeeded("Cle BRAVE_API_KEY manquante dans .env")
    with httpx.Client(timeout=30,trust_env=False) as c:
        r=c.get("https://api.search.brave.com/res/v1/web/search",params={"q":query,"count":8},
                headers={"Accept":"application/json","X-Subscription-Token":key})
        r.raise_for_status()
    results=[{"title":x.get("title",""),"url":x["url"],"snippet":x.get("description","")} for x in r.json().get("web",{}).get("results",[])]
    ctx.artifact(f"search/{ctx.usage['search']:03d}.json",{"query":query,"results":results})
    return results

def discover(ctx,llm):
    theme=ctx.info["theme"]
    hits=search(ctx,theme+" histoire vraie archives musee")+search(ctx,theme+" unusual history museum archive")
    prior=[]
    for run in runs():
        p=DATA/"runs"/run["id"]/"research.json"
        if p.exists(): prior.append(read(p)["dossier"]["title"])
    result=llm.ask("discover","Propose "+str(ctx.cfg['production']['candidates'])+" sujets historiques precis et differents a partir des pistes. Les extraits ne sont pas des preuves. Privilegie sujets racontables en 75 secondes, sans gore, sans accusations sur personnes vivantes. Evite les sujets deja traites. query doit permettre de trouver une source fiable.",
                   {"theme":theme,"results":hits,"already_used":prior},Candidates,temperature=0.6)
    result["candidates"]=[x for x in result["candidates"] if all(SequenceMatcher(None,normalize(x["title"]),normalize(t)).ratio()<0.78 for t in prior)]
    if not result["candidates"]: raise ReviewNeeded("Aucun sujet nouveau trouve")
    return result

def evidence_errors(dossier,sources):
    errors=[]; byid={s["id"]:s for s in sources}; ids=set()
    for c in dossier["claims"]:
        if c["id"] in ids: errors.append("Identifiant de fait duplique")
        ids.add(c["id"])
        for e in c["evidence"]:
            if e["source_id"] not in byid: errors.append("Source inexistante: "+e["source_id"])
            elif normalize(e["quote"]) not in normalize(byid[e["source_id"]]["text"]):
                errors.append("Citation absente du document: "+c["id"])
    return errors

def research(ctx,llm,candidates):
    reasons=[]
    selected=candidates['candidates'][:ctx.cfg['production'].get('candidates',6)]
    for idx,candidate in enumerate(selected):
        ctx.check()
        key=hashlib.sha256(json.dumps(candidate,sort_keys=True).encode()).hexdigest()[:16]
        cache=ctx.path/'research'/f'result_{key}.json'
        if cache.exists():
            result=read(cache)
            if result['accepted']:return result['research']
            reasons.append(candidate['title']+': '+result['reason'])
            ctx.event('research','Rejet deja examine: '+reasons[-1]);continue
        ctx.event('research','Verification: '+candidate['title'])
        def reject(reason):
            reasons.append(candidate['title']+': '+reason)
            ctx.artifact(f'research/result_{key}.json',{'candidate':candidate,'accepted':False,'reason':reason})
            ctx.event('research','Sujet rejete: '+reason)
            ctx.artifact('research/last_rejections.json',reasons)
        sourcefile=ctx.path/'research'/f'candidate_{idx}_sources.json'
        failures=[]
        if sourcefile.exists():
            sources=read(sourcefile)
            ctx.event('research',f'Reprise de {len(sources)} source(s) deja extraite(s)')
        else:
            hits=search(ctx,candidate['query'])+search(ctx,candidate['title']+' museum archives historical evidence')
            sources=[];seen=set()
            for hit in hits:
                ctx.check()
                if hit['url'] in seen:continue
                seen.add(hit['url'])
                try:
                    doc=fetch_text(hit['url']);doc.update(id=f'S{len(sources)+1}',title=hit['title']);sources.append(doc)
                except (ValueError,OSError,httpx.HTTPError) as exc:
                    reason=f'HTTP {exc.response.status_code}' if isinstance(exc,httpx.HTTPStatusError) else str(exc)[:150]
                    failures.append({'url':hit['url'],'reason':reason});continue
                if len(sources)>=5:break
            ctx.artifact(f'research/candidate_{idx}_sources.json',sources)
            ctx.artifact(f'research/candidate_{idx}_fetch_errors.json',failures)
        domains={urllib.parse.urlsplit(s['url']).hostname for s in sources}
        if len(domains)<2:
            reject(f'Sources insuffisantes: {len(sources)} page(s), {len(domains)} domaine(s), minimum 2 domaines. Voir sources et fetch_errors.');continue
        dossierfile=ctx.path/'research'/f'candidate_{idx}_dossier.json'
        dossier=read(dossierfile) if dossierfile.exists() else None
        errors=evidence_errors(dossier,sources) if dossier else []
        for attempt in range(2):
            if dossier and not errors:break
            dossier=llm.ask('documentalist',
              'Construis un dossier de faits exploitables. Chaque fait a un id C1... et une citation EXACTE copiee du texte source. Aucune citation paraphrasee, aucun snippet de recherche. Si un dossier precedent et ses erreurs sont fournis, corrige les references et citations en lisant les textes; supprime les faits non prouves. Ne fabrique aucune preuve.',
              {'candidate':candidate,'sources':sources,'previous_dossier':dossier,'errors':errors},Dossier)
            errors=evidence_errors(dossier,sources)
            ctx.artifact(f'research/candidate_{idx}_dossier.json',dossier)
            ctx.artifact(f'research/candidate_{idx}_evidence_check.json',{'errors':errors,'attempt':attempt+1})
        if errors:reject('Citations non verifiables: '+'; '.join(errors[:4]));continue
        review=llm.ask('fact_checker',
          'Pour CHAQUE fait, verifie si les citations impliquent reellement affirmation, date, quantite et causalite. Repere contradictions et sources se recopiant. independent_sources vrai uniquement si au moins deux sources credibles semblent independantes. Rejette les legendes non etablies. Retourne claims avec un verdict pour chaque claim_id.',
          {'dossier':dossier,'sources':sources},FactReview,temperature=0.1)
        ctx.artifact(f'research/candidate_{idx}_facts.json',review)
        expected={c['id'] for c in dossier['claims']}
        issues=[]
        if set(x['claim_id'] for x in review['claims'])!=expected:issues.append('Certains faits ne sont pas evalues ou leurs identifiants sont incorrects')
        issues += [x['claim_id']+': '+x['reason'] for x in review['claims'] if not x['supported']]
        if not review['independent_sources']:issues.append('Independance/fiabilite des sources non validee')
        if issues:reject('; '.join(issues+review['issues'])[:1200]);continue
        editorial=llm.ask('topic_editor','Evalue interet grand public pour une video courte: accroche, contexte simple, denouement, richesse visuelle. Score 0..10; accepte seulement >=7 sans probleme majeur. Ne predis pas les vues.',dossier,Verdict)
        ctx.artifact(f'research/candidate_{idx}_editorial.json',editorial)
        if not editorial['accepted'] or editorial['score']<ctx.cfg['production']['min_editorial_score']:
            reject(f"Interet editorial {editorial['score']}/10: "+'; '.join(editorial['issues']+[editorial['correction']]));continue
        result={'dossier':dossier,'sources':sources,'fact_review':review,'editorial_review':editorial}
        ctx.artifact(f'research/result_{key}.json',{'accepted':True,'research':result})
        return result
    raise ReviewNeeded('Aucun sujet valide parmi les candidats examines. '+ ' | '.join(reasons)[-1700:]+' Details: research/last_rejections.json')
