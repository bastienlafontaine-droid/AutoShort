import json, subprocess, sys, time, hashlib
from pathlib import Path
from .core import dump, read, digest, ReviewNeeded, Cancelled, ROOT
from .audio import spoken, word_error
from .schemas import VisualVerdict

def child(ctx,action,payload):
    ctx.check()
    path=ctx.path/'requests'/f'{action}_{time.time_ns()}.json'; dump(path,{'cfg':ctx.cfg,**payload})
    log=ctx.path/'media.log'
    with log.open('a',encoding='utf-8') as f:
        proc=subprocess.Popen([sys.executable,'-m','autoshort.media',action,str(path)],cwd=ROOT,stdout=f,stderr=f)
        try:
            last_progress=time.monotonic()
            while proc.poll() is None:
                ctx.check(); time.sleep(0.5)
                if action=='images' and time.monotonic()-last_progress>=30:
                    done=sum(Path(j['output']).is_file() for j in payload['jobs'])
                    ctx.event('images',f'Generation en cours: {done}/{len(payload["jobs"])} fichiers disponibles; details dans media.log')
                    last_progress=time.monotonic()
            if proc.returncode:
                raise RuntimeError(f'Echec {action}. Consulter media.log (code {proc.returncode}).')
        except BaseException:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            raise

def audio_assets(ctx,llm,script):
    import soundfile as sf
    import numpy as np
    llm.unload(); folder=ctx.path/'audio';folder.mkdir(exist_ok=True)
    scenes=script['scenes']; speed=1.0; results={}
    for attempt in range(ctx.cfg['production']['audio_attempts']):
        ctx.event('audio',f'Voix / verification {attempt+1}')
        pending=[s for s in scenes if s['id'] not in results]
        if not pending:break
        jobs=[{'text':spoken(s['narration'],ctx.cfg['production'].get('language','fr')),'output':str(folder/f"{s['id']:02d}_{attempt}.wav"),'speed':speed} for s in pending]
        child(ctx,'tts',{'jobs':jobs})
        child(ctx,'transcribe',{'jobs':[{'input':j['output'],'output':j['output']+'.json'} for j in jobs]})
        for s,j in zip(pending,jobs):
            x,rate=sf.read(j['output']); asr=read(j['output']+'.json');duration=len(x)/rate
            wer=word_error(s['narration'],asr['text'],ctx.cfg['production'].get('language','fr'));peak=float(np.max(np.abs(x))) if len(x) else 0
            silence=float(np.mean(np.abs(x)<0.003)) if len(x) else 1
            ok=(wer<=ctx.cfg['production']['max_asr_error'] and 1<duration<35 and 0.01<peak<1 and silence<0.65 and bool(asr['words']))
            report={'scene':s['id'],'path':j['output'],'sha256':digest(j['output']),'duration':duration,'wer':wer,'peak':peak,'silence_ratio':silence,'asr':asr,'accepted':ok}
            ctx.artifact(f"audio/review_{s['id']}_{attempt}.json",report)
            if ok:results[s['id']]=report
        if len(results)==len(scenes):
            total=sum(x['duration'] for x in results.values())
            if ctx.cfg['production']['min_seconds']<=total<=ctx.cfg['production']['max_seconds']:break
            # Un seul changement global de debit; la duree n'est jamais corrigee en coupant des mots.
            speed=max(0.85,min(1.2,speed*total/((ctx.cfg['production']['min_seconds']+ctx.cfg['production']['max_seconds'])/2)));results={}
        else:speed=0.95
    if len(results)!=len(scenes):
        missing=[s['id'] for s in scenes if s['id'] not in results]
        raise ReviewNeeded('Audio non valide ou duree hors cible apres les reprises autorisees'
                           + (f' (scenes {missing})' if missing else ''))
    total=sum(x['duration'] for x in results.values())
    if not ctx.cfg['production']['min_seconds']<=total<=ctx.cfg['production']['max_seconds']:
        raise ReviewNeeded(f'Duree {total:.1f}s hors cible')
    return {'scenes':[results[s['id']] for s in scenes],'duration':total}

def score_100(value):
    score=int(value or 0)
    if score<0:return 0
    if score<=10:return score*10
    return min(100,score)

def image_assets(ctx,llm,script):
    from PIL import Image
    folder=ctx.path/'images';folder.mkdir(exist_ok=True)
    approved={}; best={}; candidates=[]; corrections={}; models=ctx.cfg['models']
    threshold=score_100(ctx.cfg['production']['min_visual_score'])
    for attempt in range(ctx.cfg['production']['image_attempts']):
        pending=[s for s in script['scenes'] if s['id'] not in approved]
        if not pending:break
        ctx.event('images',f'Lot {attempt+1}: {len(pending)} scenes')
        llm.unload()
        jobs=[]
        for s in pending:
            seed=int(hashlib.sha256(f'{ctx.rid}:{s["id"]}:{attempt}'.encode()).hexdigest()[:8],16)
            prompt=s['image_prompt']
            style=script['visual_bible']+'. '+ctx.cfg['production']['style']
            if s['id'] in corrections:
                prompt=corrections[s['id']] if ctx.cfg['production'].get('story_pipeline',2)>=3 else corrections[s['id']]+'. '+prompt
            jobs.append({'prompt':prompt,'style':style,'seed':seed,'output':str(folder/f"{s['id']:02d}_{attempt}.png")})
        # Reutiliser uniquement les images reliees a une requete identique de ce run.
        previous=[]
        for request in (ctx.path/'requests').glob('images_*.json'):
            saved=read(request)
            if (saved.get('cfg',{}).get('models',{}).get('image')==ctx.cfg['models']['image']
                and all(saved.get('cfg',{}).get('production',{}).get(k)==ctx.cfg['production'].get(k)
                        for k in ('image_width','image_height','image_steps'))):
                previous.extend(saved.get('jobs',[]))
        reusable=set()
        for job in jobs:
            p=Path(job['output']); meta=Path(str(p)+'.generation.json')
            if p.is_file() and meta.is_file() and job in previous:
                generation=read(meta)
                if generation.get('seed')==job['seed'] and generation.get('model')==models['image']:
                    try:
                        with Image.open(p) as im:im.verify()
                        reusable.add(job['output'])
                    except (OSError,ValueError):pass
        missing=[j for j in jobs if j['output'] not in reusable]
        if reusable:ctx.event('images',f'Reprise: {len(reusable)} images existantes dans ce lot')
        if missing:child(ctx,'images',{'jobs':missing})
        for s,j in zip(pending,jobs):
            p=Path(j['output'])
            with Image.open(p) as image:
                image.verify()
            image_hash=digest(p)
            rating_key=hashlib.sha256(json.dumps({'scene':s,'bible':script['visual_bible'],
                'vision':models.get('vision'),'image_hash':image_hash,'policy':2},sort_keys=True).encode()).hexdigest()
            report=ctx.path/'images'/f"rating_{s['id']}_{attempt}.json"
            cached_rating=None
            if report.is_file():
                try:
                    saved=read(report)
                    if saved.get('rating_key')==rating_key:
                        VisualVerdict.model_validate(saved['quality'])
                        if saved.get('relevance') is not None:VisualVerdict.model_validate(saved['relevance'])
                        cached_rating=saved
                except (OSError,ValueError,KeyError,TypeError):pass
            verdict=None
            if cached_rating is not None:verdict=cached_rating['quality']
            if verdict is None:
                ctx.event('images',f"Scene {s['id']}: evaluation visuelle")
                verdict=llm.ask('visual_judge',
              f'''Reponds brievement: 3 problemes maximum, une correction de 40 mots maximum. Inspecte l'image jointe par rapport a l'intention visuelle. Detecte texte parasite, incoherences
majeures, mauvais objets/epoque, composition illisible, anatomie grossierement incorrecte.
Une illustration est autorisee; ne demande pas de photorealisme. score 0..100; accepte seulement >={threshold}
et sans defaut majeur. correction EN ANGLAIS: prompt de remplacement complet, 45 mots maximum, un seul cadre sans collage.
Note explicitement sur 100: 0-19 inutilisable, 20-39 defauts majeurs, 40-59 faible, 60-79 utilisable avec reserves, 80-100 solide. Justifie la note par des defauts visibles.
Tu ne peux pas certifier l'exactitude historique d'une image.''',
              {'scene':s,'visual_bible':script['visual_bible']},VisualVerdict,image=p,temperature=0.1)
            quality=dict(verdict)
            aesthetic=quality['score']
            relevance=None
            note=float(aesthetic)
            if ctx.cfg['production'].get('story_pipeline',2)>=3:
                relevance_path=f"images/relevance_{s['id']}_{attempt}.json"
                relevance=cached_rating['relevance'] if cached_rating is not None else None
                if relevance is None:relevance=llm.ask('visual_judge',
                    f"""Judge the attached image against THIS scene's narration and intended visible action.
Score 0..100: 0-19 unrelated, 20-39 major mismatch, 40-59 weak match, 60-79 usable representation, 80-100 clear match. Explain concrete mismatches in issues, at most 35 words. Empty issues if none.
A frame needs to illustrate ONE main idea, not every narrated clause.
A representative local scene is valid for global consequences; one scientist can represent science.
Do not demand every country, the original cause, or the original setting in each frame.
Reject a generic picture only when unrelated to ALL main ideas of this scene.
Reject wrong roles/uniforms, wrong era, contradictory objects, collages, split screens or illegible staging.
A scene about reactions must communicate reactions, not repeat the opening setting.
Do not demand unverifiable historical facial likeness. Accept only score >={threshold} and no major mismatch.
correction: a complete replacement English image prompt, maximum 45 words, ONE simple frame.
Do not repeat the failed composition. Never invent specific allegations or events.""",
                    {'narration':s['narration'],'intended_image':s['visual'],'prompt':s['image_prompt']},
                    VisualVerdict,image=p,temperature=0.1)
                ctx.artifact(relevance_path,relevance)
                note=round((aesthetic+relevance['score'])/2,1)
            verdict={'score':note,'score_100':note,'aesthetic_100':aesthetic,
                     'relevance_100':relevance['score'] if relevance is not None else None,
                     'accepted':note>=threshold,
                     'issues':quality['issues']+(relevance['issues'] if relevance is not None else []),
                     'correction':(relevance['correction'] if relevance is not None and relevance['score']<=aesthetic
                                   and relevance['correction'].strip() else quality['correction'])}
            ctx.artifact(str(report.relative_to(ctx.path)),{'rating_key':rating_key,'quality':quality,'relevance':relevance,'combined':verdict})
            ctx.artifact(f"images/review_{s['id']}_{attempt}.json",verdict)
            detail=f"qualite {aesthetic}/100"
            if relevance is not None:detail+=f", pertinence {relevance['score']}/100"
            ctx.event('images',f"Scene {s['id']}, essai {attempt+1}: {detail}; moyenne {note}/100")
            candidate={'scene':s['id'],'attempt':attempt+1,'path':str(p),'sha256':image_hash,'seed':j['seed'],
                       'prompt':j['prompt'],'effective_generation':read(str(p)+'.generation.json'),
                       'review':verdict,'quality_review':quality,'relevance_review':relevance,'score_100':note}
            candidates.append(candidate)
            if s['id'] not in best or note>best[s['id']]['score_100']:best[s['id']]=candidate
            if verdict['accepted']:approved[s['id']]=candidate
            elif verdict['correction'].strip():corrections[s['id']]=verdict['correction']
    llm.unload()
    for s in script['scenes']:
        if s['id'] in approved:continue
        if s['id'] not in best:raise ReviewNeeded(f"Aucune image exploitable pour la scene {s['id']}.")
        approved[s['id']]=best[s['id']]
        ctx.event('images',f"Scene {s['id']}: meilleur essai retenu {best[s['id']]['score_100']}/100")
    selected=[]
    for scene in script['scenes']:
        candidate=approved[scene['id']]
        candidate['selection_reason']='threshold_met' if candidate['score_100']>=threshold else 'best_available_after_attempts'
        selected.append(candidate)
    result={'scenes':selected,'threshold_100':threshold,'scoring':'mean_quality_relevance_100',
            'with_reservations':any(c['score_100']<threshold for c in selected)}
    ctx.artifact('images/selection.json',{**result,'candidates':candidates})
    return result
