import json, subprocess, sys, time, hashlib
from pathlib import Path
from .core import dump, read, digest, ReviewNeeded, Cancelled, ROOT
from .audio import spoken, word_error
from .schemas import Verdict

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
        jobs=[{'text':spoken(s['narration']),'output':str(folder/f"{s['id']:02d}_{attempt}.wav"),'speed':speed} for s in pending]
        child(ctx,'tts',{'jobs':jobs})
        child(ctx,'transcribe',{'jobs':[{'input':j['output'],'output':j['output']+'.json'} for j in jobs]})
        for s,j in zip(pending,jobs):
            x,rate=sf.read(j['output']); asr=read(j['output']+'.json');duration=len(x)/rate
            wer=word_error(s['narration'],asr['text']);peak=float(np.max(np.abs(x))) if len(x) else 0
            silence=float(np.mean(np.abs(x)<0.003)) if len(x) else 1
            ok=(wer<=ctx.cfg['production']['max_asr_error'] and 1<duration<35 and 0.01<peak<1 and silence<0.65 and bool(asr['words']))
            report={'scene':s['id'],'path':j['output'],'sha256':digest(j['output']),'duration':duration,'wer':wer,'peak':peak,'silence_ratio':silence,'asr':asr,'accepted':ok}
            ctx.artifact(f"audio/review_{s['id']}_{attempt}.json",report)
            if ok:results[s['id']]=report
        if len(results)==len(scenes):
            total=sum(x['duration'] for x in results.values())
            if ctx.cfg['production']['min_seconds']<=total<=ctx.cfg['production']['max_seconds']:break
            # Un seul changement global de debit; la duree n'est jamais corrigee en coupant des mots.
            speed=max(0.85,min(1.2,speed*total/75));results={}
        else:speed=0.95
    if len(results)!=len(scenes):raise ReviewNeeded('Audio non valide ou duree hors cible apres les reprises autorisees')
    total=sum(x['duration'] for x in results.values())
    if not ctx.cfg['production']['min_seconds']<=total<=ctx.cfg['production']['max_seconds']:
        raise ReviewNeeded(f'Duree {total:.1f}s hors cible')
    return {'scenes':[results[s['id']] for s in scenes],'duration':total}

def image_assets(ctx,llm,script):
    from PIL import Image
    folder=ctx.path/'images';folder.mkdir(exist_ok=True)
    approved={}; corrections={}; models=ctx.cfg['models']
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
            if s['id'] in corrections:prompt=corrections[s['id']]+'. '+prompt
            jobs.append({'prompt':prompt,'style':style,'seed':seed,'output':str(folder/f"{s['id']:02d}_{attempt}.png")})
        # Reutiliser uniquement les images reliees a une requete identique de ce run.
        previous=[]
        for request in (ctx.path/'requests').glob('images_*.json'):
            saved=read(request)
            if saved.get('cfg')==ctx.cfg:previous.extend(saved.get('jobs',[]))
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
            report=ctx.path/'images'/f"review_{s['id']}_{attempt}.json"
            verdict=None
            if j['output'] in reusable and report.is_file():
                try:verdict=Verdict.model_validate(read(report)).model_dump()
                except ValueError:pass
            if verdict is None:
                ctx.event('images',f"Scene {s['id']}: evaluation visuelle")
                verdict=llm.ask('visual_judge',
              '''Reponds brievement: 3 problemes maximum, une correction de 40 mots maximum. Inspecte l'image jointe par rapport a l'intention visuelle. Detecte texte parasite, incoherences
majeures, mauvais objets/epoque, composition illisible, anatomie grossierement incorrecte.
Une illustration est autorisee; ne demande pas de photorealisme. score 0..10; accepte seulement >=7
et sans defaut majeur. correction EN ANGLAIS, courte et actionnable pour le generateur d'images.
Tu ne peux pas certifier l'exactitude historique d'une image.''',
              {'scene':s,'visual_bible':script['visual_bible']},Verdict,image=p,temperature=0.1)
            ctx.artifact(f"images/review_{s['id']}_{attempt}.json",verdict)
            ctx.event('images',f"Scene {s['id']}: score {verdict['score']}/10, accepte={verdict['accepted']}")
            if verdict['accepted'] and verdict['score']>=ctx.cfg['production']['min_visual_score']:
                approved[s['id']]={'scene':s['id'],'path':str(p),'sha256':digest(p),'seed':j['seed'],'prompt':j['prompt'],'effective_generation':read(str(p)+'.generation.json'),'review':verdict}
            else:corrections[s['id']]=verdict['correction']
    llm.unload()
    if len(approved)!=len(script['scenes']):raise ReviewNeeded('Certaines images ne passent pas le controle. Voir les evaluations.')
    return {'scenes':[approved[s['id']] for s in script['scenes']]}
