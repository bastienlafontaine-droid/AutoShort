import ipaddress, socket, urllib.parse, hashlib, json, re
import httpx
from .core import secret, normalize, ReviewNeeded, runs, DATA, read
from .schemas import Candidates,Dossier,FactReview,Verdict,Strict
from pydantic import Field
from difflib import SequenceMatcher

class ReferencedClaim(Strict):
    id: str
    text: str
    passage_ids: list[str] = Field(min_length=1,max_length=4)

class ReferencedDossier(Strict):
    title: str
    summary: str
    claims: list[ReferencedClaim] = Field(min_length=4,max_length=8)
    uncertainties: list[str]

class EventScope(Strict):
    event: str
    protagonist: str
    location: str
    action_period: str
    passage_ids: list[str] = Field(min_length=1)
    exclusions: list[str]

def scoped_passages(scope,passages):
    byid={p['passage_id']:p for p in passages}
    if any(ref not in byid for ref in scope['passage_ids']):raise ValueError('Reference de passage inexistante dans la selection evenement')
    return [byid[ref] for ref in dict.fromkeys(scope['passage_ids'])]

def source_passages(sources):
    passages=[]
    for source in sources:
        text=source['text'];start=0;index=1
        while start<len(text):
            end=min(start+850,len(text))
            if end<len(text):
                boundary=text.rfind(' ',start+400,end)
                if boundary>start:end=boundary
            quote=text[start:end].strip()
            if len(quote)>=20:
                passages.append({'passage_id':f"{source['id']}:P{index}",
                    'source_id':source['id'],'title':source.get('title',''),
                    'url':source['url'],'quote':quote})
                index+=1
            start=end
    return passages

def resolve_passages(draft,passages):
    byid={p['passage_id']:p for p in passages};claims=[]
    for claim in draft['claims']:
        evidence=[]
        for ref in claim['passage_ids']:
            if ref not in byid:raise ValueError(f"Passage inexistant: {ref} pour {claim['id']}")
            passage=byid[ref]
            evidence.append({'source_id':passage['source_id'],'quote':passage['quote']})
        claims.append({'id':claim['id'],'text':claim['text'],'evidence':evidence})
    return Dossier.model_validate({**{k:draft[k] for k in ('title','summary','uncertainties')},'claims':claims}).model_dump()

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
    if ctx.cfg['production'].get('story_pipeline',1)>=2:
        hits=search(ctx,theme+" histoire vraie sources")+search(ctx,theme+" true story original report")
    else:
        hits=search(ctx,theme+" histoire vraie archives musee")+search(ctx,theme+" unusual history museum archive")
    prior=[]
    for run in runs():
        p=DATA/"runs"/run["id"]/"research.json"
        if p.exists(): prior.append(read(p)["dossier"]["title"])
    guided_mode=not read(ctx.path/'request.json').get('auto',True)
    instruction=('Propose au moins 3 sujets distincts, pertinents pour la thematique; titre et angle en francais. ' if guided_mode else 'Si le theme nomme deja un evenement precis, reste sur cet evenement et propose moins de candidats plutot que des histoires similaires. ')
    result=llm.ask("discover",instruction+"Propose "+str(ctx.cfg['production']['candidates'])+" sujets reels precis et differents a partir des pistes. Respecte la thematique precise. Les extraits ne sont pas des preuves. Privilegie sujets racontables en 75 secondes, sans gore, sans accusations sur personnes vivantes. Evite les sujets deja traites. query doit permettre de trouver une source fiable.",
                   {"theme":theme,"results":hits,"already_used":prior},Candidates,temperature=0.6)
    result["candidates"]=[x for x in result["candidates"] if all(SequenceMatcher(None,normalize(x["title"]),normalize(t)).ratio()<0.78 for t in prior)]
    if not result["candidates"]: raise ReviewNeeded("Aucun sujet nouveau trouve")
    if guided_mode and len(result['candidates'])<3:raise ReviewNeeded('Moins de trois idees nouvelles. Preciser ou elargir la thematique puis relancer.')
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
        key=hashlib.sha256(json.dumps({'candidate':candidate,'contract':'event-v2' if ctx.cfg['production'].get('story_pipeline',1)>=2 else 'passages-v1','model':ctx.cfg['models']['text']},sort_keys=True).encode()).hexdigest()[:16]
        if candidates.get('guided'):idx=key
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
        v2=ctx.cfg['production'].get('story_pipeline',1)>=2
        dossierfile=ctx.path/'research'/f'candidate_{idx}_dossier{"_v2" if v2 else ""}.json'
        dossier=read(dossierfile) if dossierfile.exists() else None
        errors=evidence_errors(dossier,sources) if dossier else []
        passages=source_passages(sources)
        ctx.artifact(f'research/candidate_{idx}_passages.json',passages)
        scope={}
        if v2:
            scopefile=ctx.path/'research'/f'candidate_{idx}_scope.json'
            if scopefile.exists():scope=read(scopefile)
            else:
                scope=llm.ask('event_selector',
                  'Isole UN evenement precis correspondant au candidat. Identifie protagoniste, lieu et epoque de l ACTION. Selectionne uniquement les passage_ids parlant de CET evenement. Exclue les anecdotes analogues, autres pays, autres personnes et contenu de coffres differents. Si un passage est ambigu, ne le selectionne pas. Ne devine pas les champs inconnus: indique inconnu.',
                  {'candidate':candidate,'passages':passages},EventScope,temperature=0.1)
                ctx.artifact(f'research/candidate_{idx}_scope.json',scope)
            try:passages=scoped_passages(scope,passages)
            except ValueError as exc:reject(str(exc));continue
            if len({urllib.parse.urlsplit(p['url']).hostname for p in passages})<2:
                reject('Evenement non recoupe par deux domaines dans les passages retenus');continue
        draft=None
        for attempt in range(2):
            if dossier and not errors:break
            draft=llm.ask('documentalist',
              'Construis 4 a 8 faits solidement documentes sur UN SEUL evenement. Respecte event_scope si fourni; exclue faits concernant les autres personnages, pays ou affaires, meme sur le meme theme. Pour chaque fait, selectionne les passage_ids qui le prouvent directement. Ne recopie aucune citation: le programme les extraira. N invente aucun identifiant. Ne transforme pas une hypothese ou une legende en fait etabli. Conserve les dates et nuances; signale les incertitudes. Si les sources sont insuffisantes, ne fabrique pas de preuve.',
              {'candidate':candidate,'event_scope':scope,'passages':passages,'previous_draft':draft,'errors':errors},ReferencedDossier,temperature=0.1)
            try:
                dossier=resolve_passages(draft,passages)
                errors=evidence_errors(dossier,sources)
            except ValueError as exc:
                dossier=None;errors=[str(exc)]
            ctx.artifact(f'research/candidate_{idx}_passage_selection.json',draft)
            if dossier:ctx.artifact(str(dossierfile.relative_to(ctx.path)),dossier)
            ctx.artifact(f'research/candidate_{idx}_evidence_check.json',{'errors':errors,'attempt':attempt+1})
        if errors:reject('Citations non verifiables: '+'; '.join(errors[:4]));continue
        review_sources=sources
        if v2:
            review_sources=[{**source,'text':'\n'.join(p['quote'] for p in passages if p['source_id']==source['id'])} for source in sources if any(p['source_id']==source['id'] for p in passages)]
        review=llm.ask('fact_checker',
          'Pour CHAQUE fait, verifie son appartenance meme evenement, protagoniste, lieu et periode que event_scope si fourni. Un fait exact concernant une AUTRE affaire est non soutenu ici. Ensuite verifie si les citations impliquent reellement affirmation, date, quantite et causalite. Repere contradictions et sources se recopiant. independent_sources vrai uniquement si au moins deux sources credibles semblent independantes. Rejette les legendes non etablies. Retourne claims avec un verdict pour chaque claim_id.',
          {'dossier':dossier,'sources':review_sources,'event_scope':scope},FactReview,temperature=0.1)
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
        if scope:result['event_scope']=scope
        ctx.artifact(f'research/result_{key}.json',{'accepted':True,'research':result})
        return result
    raise ReviewNeeded('Aucun sujet valide parmi les candidats examines. '+ ' | '.join(reasons)[-1700:]+' Details: research/last_rejections.json')
