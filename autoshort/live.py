"""Persistent incremental guided queue. One worker, short locked state transactions.
Never hold the state lock during inference; UI actions remain available while busy.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import time
from filelock import FileLock
from .core import read,dump,run_info,update,Cancelled,ReviewNeeded,digest
from .schemas import Candidate,Script
from .editorial import Narrative

STAGES=['ideas','script','storyboard','images','short']
PROMPTS={
 'ideas':'Propose un sujet reel, precis et different des sujets deja proposes, adapte a la thematique. Titre et angle en francais, recherche de sources possible. Ne presente pas une legende comme un fait.',
 'script':'Ecris une narration complete et captivante sur cet evenement uniquement. Titre, description et 5 a 9 scenes numerotees, 80 a 200 mots au total. Accroche, progression, chute precise. Appuie chaque scene sur les claim_ids du dossier. Aucun fait invente. Images de reconstitution a mentionner dans la description.',
 'storyboard':'Propose un decoupage visuel coherent, une image par scene. Conserve exactement la narration et les faits. Description visuelle en francais, prompt image en anglais. Un seul cadre simple par plan, sans collage ni texte, epoque et objets coherents.',
}

def enabled(folder):return read(folder/'request.json').get('guided_version')==2

def initial():
    return {'version':2,'revision':0,'stage':'ideas','jobs':[],'proposals':{s:[] for s in STAGES},
            'chosen':{},'image_choices':{},'shot_overrides':{},'rejected':{},'message':'','prompts':PROMPTS}

@contextmanager
def transaction(folder):
    with FileLock(str(folder/'live.lock'),timeout=10):
        path=folder/'live.json';w=read(path) if path.exists() else initial()
        yield w
        w['revision']+=1;dump(path,w)

def snapshot(folder):
    with FileLock(str(folder/'live.lock'),timeout=10):
        return read(folder/'live.json') if (folder/'live.json').exists() else initial()

def add_job(w,stage,kind='proposal',prompt=None,target=None,manual=False,base=None):
    j={'id':uuid4().hex,'stage':stage,'kind':kind,'prompt':prompt or PROMPTS.get(stage,''),
       'target':target,'manual':manual,'base':deepcopy(base),'status':'queued','order':len(w['jobs'])}
    w['jobs'].append(j);return j

def initialize(folder):
    with transaction(folder) as w:
        if not w['jobs']:
            for _ in range(3):add_job(w,'ideas')

def proposal(w,stage,pid):
    p=next((p for p in w['proposals'][stage] if p['id']==pid),None)
    if p is None:raise ValueError('Proposition introuvable.')
    return p

def wake(rid):
    info=run_info(rid)
    if info['status'] not in ('RUNNING','QUEUED'):
        update(rid,status='QUEUED',cancel=0,error='')

def require_active(w,stage):
    if stage not in STAGES or w['stage']!=stage or stage=='short':raise ValueError('Cette etape est deja validee ou pas encore ouverte.')

def request_generation(folder,rid,stage,prompt,target=None,base_id=None):
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>6000:raise ValueError('Prompt requis (6000 caracteres maximum).')
    with transaction(folder) as w:
        require_active(w,stage)
        if run_info(rid)['status'] in ('CANCELLED','INTERRUPTED'):raise ValueError('Reprendre la production avant de generer.')
        base=proposal(w,stage,base_id)['data'] if base_id else None
        if stage=='storyboard' and target is not None:
            if not base or target not in [s['id'] for s in base['script']['scenes']]:raise ValueError('Choisir le decoupage et le plan a modifier.')
        if stage=='images':
            board=proposal(w,'storyboard',w['chosen']['storyboard'])['data']['script']
            if target not in [s['id'] for s in board['scenes']]:raise ValueError('Plan inconnu.')
        job=add_job(w,stage,prompt=prompt.strip(),target=target,manual=True,base=base)
        wake(rid)
        return job['id']

def validated_edit(stage,data,original):
    if stage=='ideas':
        item=Candidate.model_validate(data).model_dump()
        if not all(v.strip() for v in item.values()):raise ValueError('Titre, angle et recherche requis.')
        return item
    if stage=='script':
        item=Narrative.model_validate(data['narrative']).model_dump()
        old=original['narrative']
        if [(s['id'],s['claim_ids']) for s in item['scenes']]!=[(s['id'],s['claim_ids']) for s in old['scenes']]:raise ValueError('Conserver les scenes et references.')
        if not item['title'].strip() or any(not s['narration'].strip() for s in item['scenes']):raise ValueError('Titre et narration obligatoires.')
        if sum(len(s['narration'].split()) for s in item['scenes'])>200:raise ValueError('Maximum 200 mots de narration.')
        return {**original,'narrative':item,'human_edited':True}
    if stage=='storyboard':
        item=Script.model_validate(data['script']).model_dump();old=original['script']
        if [(s['id'],s['narration'],s['claim_ids']) for s in item['scenes']]!=[(s['id'],s['narration'],s['claim_ids']) for s in old['scenes']]:raise ValueError('La narration validee doit etre conservee.')
        if any(not s['visual'].strip() or not s['image_prompt'].strip() for s in item['scenes']):raise ValueError('Descriptions et prompts requis.')
        return {**original,'script':item,'human_edited':True}
    raise ValueError('Pour une image, modifier son prompt puis generer un nouvel essai.')

def edit(folder,rid,stage,pid,data,prompt):
    with transaction(folder) as w:
        require_active(w,stage);old=proposal(w,stage,pid)
        value=validated_edit(stage,data,old['data'])
        p={**old,'id':uuid4().hex,'data':value,'prompt':prompt or old['prompt'],'score':None,'edited_from':pid}
        w['proposals'][stage].append(p)
        return p['id']

def cancel_background(w,stage):
    for j in w['jobs']:
        if j['stage']==stage and j['kind']=='proposal' and not j['manual'] and j['status']=='queued':j['status']='cancelled'

def choose(folder,rid,stage,pid):
    with transaction(folder) as w:
        require_active(w,stage);p=proposal(w,stage,pid)
        if stage=='images':
            check_image(folder,p['data']);w['image_choices'][str(p['target'])]=pid;return
        if stage=='ideas' and pid in w['rejected']:raise ValueError('Ce sujet a ete rejete; choisir une autre idee.')
        cancel_background(w,stage);w['chosen'][stage]=pid;w['message']=''
        if stage=='ideas':
            # Research remains step 1 until the chosen subject has usable evidence.
            w['stage']='script';add_job(w,'script',kind='research',base={'idea_id':pid,'candidate':p['data']})
        elif stage=='script':
            w['stage']='storyboard'
            for _ in range(2):add_job(w,'storyboard')
            add_job(w,'script',kind='audio',base=p['data'])
        elif stage=='storyboard':
            w['stage']='images'
            attempts=read(folder/'config.json')['production'].get('image_attempts',3)
            for _ in range(attempts):
                for scene in p['data']['script']['scenes']:
                    add_job(w,'images',target=scene['id'],prompt=scene['image_prompt'])
        else:raise ValueError('Etape inconnue.')
        wake(rid)

VALID_MOVEMENTS={'push_in','pull_out','pan_left','pan_right','tilt_up','tilt_down','diagonal','still','reveal'}
VALID_MEDIA={'animated_image','generated_video','archive_image','archive_video'}

def configure_shot(folder,rid,shot_id,movement,media_type):
    """Human overrides stay durable and never regenerate an accepted image."""
    import re
    with transaction(folder) as w:
        require_active(w,'images')
        if not re.fullmatch(r's[0-9]{2}-p0[1-3]',shot_id):
            raise ValueError('Identifiant de plan invalide.')
        board=proposal(w,'storyboard',w['chosen']['storyboard'])['data']['script']
        scene=int(shot_id[1:3])
        if scene not in [s['id'] for s in board['scenes']]:
            raise ValueError('Scene inconnue.')
        if movement not in VALID_MOVEMENTS or media_type not in VALID_MEDIA:
            raise ValueError('Mouvement ou type de media invalide.')
        # Archive media require a verified import; do not mislabel synthetic art.
        if media_type.startswith('archive_'):
            raise ValueError('Importer et verifier une archive avant de la selectionner.')
        w.setdefault('shot_overrides',{})[shot_id]={
            'camera_movement':movement,'media_type':media_type}
        return {'ok':True}

def check_image(folder,data):
    p=Path(data['path']).resolve()
    if not p.is_relative_to(folder.resolve()) or not p.is_file() or digest(p)!=data['sha256']:raise ValueError('Image absente ou modifiee : generer un nouvel essai pour ce plan.')

def validate_images(folder,rid):
    with transaction(folder) as w:
        require_active(w,'images')
        board=proposal(w,'storyboard',w['chosen']['storyboard'])['data']['script']
        for s in board['scenes']:
            pid=w['image_choices'].get(str(s['id']))
            if not pid:raise ValueError('Choisir une image pour chaque plan.')
            p=proposal(w,'images',pid)
            if p['target']!=s['id']:raise ValueError('Image du mauvais plan.')
            check_image(folder,p['data'])
        cancel_background(w,'images');w['stage']='short';add_job(w,'short',kind='render');wake(rid)

def recover(folder):
    with transaction(folder) as w:
        missing=[]
        for target,pid in w['image_choices'].items():
            try:check_image(folder,proposal(w,'images',pid)['data'])
            except ValueError:missing.append(target)
        if missing:
            for target in missing:w['image_choices'].pop(target,None)
            w['stage']='images';w.pop('finished',None)
            w['message']='Une image choisie est absente ou modifiee. Choisir un autre essai ou utiliser + pour ce plan.'
            for name in ('render','final'):(folder/f'{name}.json').unlink(missing_ok=True)
            for j in w['jobs']:
                if j['kind']=='render':j['status']='cancelled'
        for kind in ('audio','render'):
            jobs=[j for j in w['jobs'] if j['kind']==kind and j['status']=='done']
            checkpoint=folder/f'{kind}.json'
            invalid=bool(jobs) and not checkpoint.exists()
            if checkpoint.exists():
                value=read(checkpoint)
                assets=value.get('scenes',[value])
                invalid=any('path' in a and (not Path(a['path']).is_file() or digest(a['path'])!=a['sha256']) for a in assets)
            if invalid:
                w.pop('finished',None)
                checkpoint.unlink(missing_ok=True)
                for j in jobs:
                    (folder/'live_results'/f"{j['id']}.json").unlink(missing_ok=True)
                    if kind=='audio' or w['stage']=='short':j['status']='queued'
                for name in ('render','final'):(folder/f'{name}.json').unlink(missing_ok=True)
                for j in w['jobs']:
                    if j['kind']=='render':
                        (folder/'live_results'/f"{j['id']}.json").unlink(missing_ok=True)
                        if w['stage']=='short':j['status']='queued'
        for j in w['jobs']:
            if j['status']=='running':j['status']='queued'

def retry(folder,rid,jid):
    with transaction(folder) as w:
        job=next((j for j in w['jobs'] if j['id']==jid),None)
        if not job or job['status']!='failed':raise ValueError('Seul un calcul en erreur peut etre repris.')
        if job['kind']=='proposal':require_active(w,job['stage'])
        job['status']='queued';job.pop('error',None);job['manual']=True;wake(rid)

def claim(folder,rid):
    with transaction(folder) as w:
        if run_info(rid)['cancel']:raise Cancelled('Arret demande')
        jobs=[j for j in w['jobs'] if j['status']=='queued']
        # A renderer cannot race voice production. An audio failure is explicitly retryable.
        jobs=[j for j in jobs if j['kind']!='render' or (folder/'audio.json').exists()]
        jobs=[j for j in jobs if not (j['kind']=='proposal' and j['stage']=='script') or (folder/'research.json').exists()]
        if not jobs:
            update(rid,status='AWAITING_APPROVAL',step=w['stage'])
            return None
        priority=lambda j:(0 if j['manual'] else 2 if j['kind']=='audio' else 1,j['order'])
        job=min(jobs,key=priority);job['status']='running';job['started_at']=time.time()
        return deepcopy(job)

def complete(folder,job,result):
    with transaction(folder) as w:
        current=next(j for j in w['jobs'] if j['id']==job['id']);current['status']='done'
        if job['kind']=='proposal':
            p={'id':job['id'],'data':result['data'],'score':result.get('score'),'prompt':job['prompt'],'target':job['target']}
            if not any(x['id']==p['id'] for x in w['proposals'][job['stage']]):w['proposals'][job['stage']].append(p)
            if job['stage']=='images' and w['stage']=='images':
                # First available is the default; later versions never overwrite a user's choice.
                w['image_choices'].setdefault(str(job['target']),p['id'])
        elif job['kind']=='research':
            for _ in range(2):add_job(w,'script')
        elif job['kind']=='render':w['finished']=True

def failed(folder,job,exc):
    with transaction(folder) as w:
        current=next(j for j in w['jobs'] if j['id']==job['id']);current['status']='failed'
        current['error']=f'{type(exc).__name__}: {str(exc)[:900]}'
        if job['kind']=='research' and isinstance(exc,ReviewNeeded) and str(exc).startswith('Aucun sujet valide parmi'):
            w['rejected'][job['base']['idea_id']]=str(exc);w['stage']='ideas';w['chosen'].pop('ideas',None)
            current['status']='rejected';w['message']='Ce sujet manque de preuves. Choisir une autre idee ou utiliser +.'
            # Refill cancelled alternatives, without discarding any already seen proposal.
            for j in w['jobs']:
                if j['stage']=='ideas' and j['status']=='cancelled':j['status']='queued'

def run(ctx,llm):
    from .live_generation import generate
    initialize(ctx.path);recover(ctx.path)
    if snapshot(ctx.path).get('finished'):
        update(ctx.rid,status='READY',step='done',error='');return
    while True:
        ctx.check();job=claim(ctx.path,ctx.rid)
        if job is None:return
        try:
            # Stable job paths make a crash after inference/before commit resumable.
            result_path=ctx.path/'live_results'/f"{job['id']}.json"
            result=read(result_path) if result_path.exists() else generate(ctx,llm,job,snapshot(ctx.path))
            if not result_path.exists():dump(result_path,result)
            ctx.check();complete(ctx.path,job,result)
            if job['kind']=='render':
                update(ctx.rid,status='READY',step='done',error='');return
        except Cancelled:raise
        except Exception as exc:
            failed(ctx.path,job,exc)
            ctx.event(job['stage'],'Generation en erreur; les propositions disponibles restent conservees.')
            # Do not spin forever on budget exhaustion; UI can still choose already-ready proposals.
            if isinstance(exc,ReviewNeeded) and str(exc).startswith('Budget'):
                update(ctx.rid,status='NEEDS_REVIEW',error=str(exc));return
