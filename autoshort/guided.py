"""Durable human gates. Generated checkpoints and explicit approvals are distinct."""
from pathlib import Path
from pydantic import Field
from .core import read, dump, update, ReviewNeeded, digest
from .schemas import Strict
from .editorial import Narrative, fingerprint

class AwaitingApproval(Exception):
    pass

class RankedIdea(Strict):
    index: int = Field(ge=0)
    score: int = Field(ge=0,le=100)
    reason: str

class Ranking(Strict):
    ideas: list[RankedIdea]

def workflow(folder):
    p=folder/'workflow.json'
    return read(p) if p.exists() else {'approvals':{},'rejected':{}}

def is_auto(folder):
    return read(folder/'request.json').get('auto',True)

def gate(ctx, stage, payload):
    ctx.check()
    w=workflow(ctx.path)
    approval=w['approvals'].get(stage)
    if approval and approval['input_hash']==fingerprint(payload):
        return approval['value']
    w['pending']={'stage':stage,'input_hash':fingerprint(payload),'value':payload}
    dump(ctx.path/'workflow.json',w)
    update(ctx.rid,step=stage)
    raise AwaitingApproval()

def rank_ideas(ctx,llm,candidates):
    items=candidates['candidates']
    result=llm.ask('topic_ranker',
        'Classe ces idees par pertinence pour la thematique et potentiel narratif. Note indicative 0..100, pas une verification factuelle ni une prediction de vues. Evalue chaque index exactement une fois. Justification courte en francais.',
        {'theme':ctx.info['theme'],'ideas':[{'index':i,**c} for i,c in enumerate(items)]},Ranking,temperature=0.1)
    scores={r['index']:r for r in result['ideas']}
    if set(scores)!=set(range(len(items))):raise ReviewNeeded('Classement incomplet des idees; reprendre.')
    ranked=sorted(enumerate(items),key=lambda x:-scores[x[0]]['score'])[:3]
    return {'ideas':[{'id':str(i),'candidate':c,'score':scores[i]['score'],'reason':scores[i]['reason']} for i,c in ranked]}

def choose_research(ctx,llm,ideas,research_fn):
    w=workflow(ctx.path)
    available={'ideas':[i for i in ideas['ideas'] if i['id'] not in w['rejected']], 'rejected':w['rejected']}
    if not available['ideas']:raise ReviewNeeded('Aucun des sujets proposes ne tient. Consulter les motifs; creer une nouvelle production avec une autre thematique.')
    chosen=gate(ctx,'idea',available)
    try:
        return ctx.stage('research',lambda:research_fn(ctx,llm,{'candidates':[chosen['candidate']],'guided':True}))
    except ReviewNeeded as exc:
        # Only a documented rejection exhausts an idea. Budgets, service failures and missing keys remain retryable.
        if not str(exc).startswith('Aucun sujet valide parmi'):raise
        w=workflow(ctx.path);w['rejected'][chosen['id']]=str(exc)
        w['approvals'].pop('idea',None);w.pop('pending',None)
        dump(ctx.path/'workflow.json',w)
        return choose_research(ctx,llm,ideas,research_fn)

def image_options(ctx,images,script=None):
    selection=ctx.path/'images/selection.json'
    candidates=read(selection).get('candidates',[]) if selection.exists() else images['scenes']
    return {**images,'candidates':candidates,'plans':(script or {}).get('scenes',[])}

def approve(folder, stage, input_hash, changes):
    w=workflow(folder);pending=w.get('pending')
    if not pending or pending['stage']!=stage or pending['input_hash']!=input_hash:
        raise ValueError('Cette validation est perimee. Actualiser la production.')
    value=pending['value']
    if stage=='idea':
        value=next((x for x in value['ideas'] if x['id']==changes.get('id')),None)
        if value is None:raise ValueError('Choisir une idee proposee.')
    elif stage=='script':
        original=value['narrative']
        edited=changes.get('narrative',original)
        edited=Narrative.model_validate(edited).model_dump()
        if [(s['id'],s['claim_ids']) for s in edited['scenes']]!=[(s['id'],s['claim_ids']) for s in original['scenes']]:
            raise ValueError('Conserver les plans et leurs references aux faits.')
        if not edited['title'].strip() or any(not s['narration'].strip() for s in edited['scenes']):raise ValueError('Titre et narration obligatoires.')
        if sum(len(s['narration'].split()) for s in edited['scenes'])>200:raise ValueError('Maximum 200 mots de narration.')
        value={**value,'narrative':edited,'human_edited':edited!=original}
    elif stage=='storyboard':
        plans=changes.get('scenes',value['script']['scenes'])
        original=value['script']['scenes']
        if [s['id'] for s in plans]!=[s['id'] for s in original]:raise ValueError('Conserver tous les plans dans leur ordre.')
        scenes=[]
        for old,new in zip(original,plans):
            if not all(isinstance(new.get(k),str) and new[k].strip() for k in ('visual','image_prompt')):raise ValueError('Description et idee d’image obligatoires.')
            scenes.append({**old,**{k:new[k] for k in ('visual','image_prompt')}})
        value={**value,'script':{**value['script'],'scenes':scenes}}
    elif stage=='images':
        choices=changes.get('choices',{})
        scenes=[]
        for old in value['scenes']:
            attempt=choices.get(str(old['scene']),old['attempt'])
            chosen=next((c for c in value['candidates'] if c['scene']==old['scene'] and c['attempt']==attempt),None)
            if chosen is None:raise ValueError('Essai inconnu.')
            p=Path(chosen['path']).resolve()
            if not p.is_relative_to((folder/'images').resolve()) or not p.is_file() or digest(p)!=chosen['sha256']:raise ValueError('Image absente ou modifiee. Reprendre sa generation.')
            scenes.append({**chosen,'selection_reason':'human_choice'})
        value={**value,'scenes':scenes,'with_reservations':any(c['score_100']<value['threshold_100'] for c in scenes)}
    else:raise ValueError('Etape inconnue.')
    w['approvals'][stage]={'input_hash':input_hash,'value':value}
    w.pop('pending',None)
    dump(folder/'workflow.json',w)
    return value

def progress(info,folder):
    auto=is_auto(folder);w=workflow(folder)
    step=info['step']
    number={'discover':1,'ideas':1,'idea':1,'research':1,'narrative':2,'editorial':2,'script':2,'storyboard':3,'audio':4,'images':4,'render':5,'final':5,'done':5}.get(step,1)
    pending=w.get('pending') if info['status']=='AWAITING_APPROVAL' else None
    return {'auto':auto,'number':number,'approved':list(w['approvals']),'pending':pending}
