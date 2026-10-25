"""One proposal per work item, reusing research, schemas, media judges and renderer."""
from copy import deepcopy
from .core import read,ReviewNeeded
from .schemas import Candidate,Verdict,Script
from .editorial import Narrative,Storyboard,VisualPlan
from .storytelling import errors as narrative_errors
from .research import search,research
from .assets import image_assets,audio_assets,score_100
from .live import proposal

class MediaContext:
    """Unique durable namespace per image attempt; existing asset cache remains usable."""
    def __init__(self,ctx,job):
        self.parent=ctx;self.path=ctx.path/'guided_media'/job['id'];self.path.mkdir(parents=True,exist_ok=True)
        self.rid=ctx.rid+':'+job['id'];self.cfg=deepcopy(ctx.cfg);self.cfg['production']['image_attempts']=1
    def __getattr__(self,name):return getattr(self.parent,name)
    def artifact(self,name,value):
        from .core import dump
        dump(self.path/name,value)

def generate(ctx,llm,job,w):
    stage=job['stage'];kind=job['kind'];prompt=job['prompt']
    if kind=='research':
        return ctx.stage('research',lambda:research(ctx,llm,{'candidates':[job['base']['candidate']],'guided':True}))
    if kind=='audio':
        return ctx.stage('audio',lambda:audio_assets(ctx,llm,job['base']['narrative']))
    if kind=='video':
        from pathlib import Path
        from .video_provider import provider_from_config, VideoGenerationError
        from .render import probe
        from .core import digest
        from .live import check_image
        image_id=job['base']['image_id']
        image=proposal(w,'images',image_id)['data']
        check_image(ctx.path,image)
        provider=provider_from_config(ctx.cfg['production'])
        if not provider.available() or not provider.capabilities()['image_to_video']:
            raise ReviewNeeded('ComfyUI local indisponible ou workflow API absent.')
        llm.unload()
        output=ctx.path/'generated_clips'/f"{job['id']}.mp4"
        if not output.exists():
            provider.generate(image['path'],output,
                timeout=int(ctx.cfg['production'].get('video_generation',{}).get('timeout_seconds',600)),
                cancellation=ctx.check)
        info=probe(output)
        if not any(stream.get('codec_type')=='video' for stream in info.get('streams',[])):
            raise VideoGenerationError('Le media produit ne contient pas de flux video.')
        return {'path':str(output),'sha256':digest(output),'shot_id':job['base']['shot_id'],
                'image_id':image_id,'duration':float(info['format']['duration'])}
    if kind=='render':
        from .pipeline import render,final,report
        from .live import check_image
        editorial=proposal(w,'storyboard',w['chosen']['storyboard'])['data']
        images=[]
        from .live import check_video
        overrides=deepcopy(w.get('shot_overrides',{}))
        for shot_id,jid in w.get('video_choices',{}).items():
            result=read(ctx.path/'live_results'/f'{jid}.json')
            check_video(ctx.path,result)
            override=overrides.setdefault(shot_id,{})
            override['media_type']='generated_video'
            override['video_path']=result['path']
        for scene in editorial['script']['scenes']:
            item=proposal(w,'images',w['image_choices'][str(scene['id'])])['data']
            check_image(ctx.path,item);images.append({**item,'selection_reason':'human_choice'})
        threshold=score_100(ctx.cfg['production']['min_visual_score'])
        state={'research':read(ctx.path/'research.json'),'editorial':editorial,'audio':read(ctx.path/'audio.json'),
               'images':{'scenes':images,'threshold_100':threshold,'scoring':'mean_quality_relevance_100',
                         'with_reservations':any(i['score_100']<threshold for i in images),
                         'shot_overrides':overrides}}
        state['render']=ctx.stage('render',lambda:render(ctx,editorial['script'],state['audio'],state['images']))
        state['final']=ctx.stage('final',lambda:final(ctx,llm,state));report(ctx,state)
        return state['render']
    previous=[p['data'] for p in w['proposals'][stage]]
    if stage=='ideas':
        hits=ctx.stage('idea_search',lambda:{'hits':search(ctx,ctx.info['theme']+' histoire vraie sources')+search(ctx,ctx.info['theme']+' true story original report')})['hits']
        item=llm.ask('discover',prompt,{'theme':ctx.info['theme'],'pistes':hits,'deja_proposes':previous,'a_reviser':job['base']},Candidate,temperature=.6)
        review=llm.ask('topic_editor','Note indicative 0..10 de pertinence et potentiel narratif. Les extraits ne sont pas des preuves. Justifie brievement en francais. Pas de prediction de vues.',{'theme':ctx.info['theme'],'idee':item},Verdict,temperature=.1)
        return {'data':item,'score':review['score']*10,'review':review}
    if stage=='script':
        dossier=read(ctx.path/'research.json')
        language=ctx.cfg['production'].get('language','fr')
        item=llm.ask('writer',prompt+' Langue de narration: '+language,
            {'research':dossier,'versions_precedentes':previous,'a_reviser':job['base']},Narrative,temperature=.5)
        problems=narrative_errors(item,dossier['dossier'])
        if problems:raise ReviewNeeded('; '.join(problems)+' : modifier le prompt et utiliser +.')
        review=llm.ask('script_judge','Evalue clarte, rythme et fidelite au dossier. Note 0..10; signale contradictions ou inventions sans inventer de details manquants. Conseils courts en francais.',{'script':item,'research':dossier},Verdict,temperature=.1)
        return {'data':{'narrative':item,'review':review},'score':review['score']*10}
    if stage=='storyboard':
        if job['target'] is not None:
            data=deepcopy(job['base']);scene=next(s for s in data['script']['scenes'] if s['id']==job['target'])
            plan=llm.ask('storyboard',prompt+' Retourne uniquement visual (francais) et image_prompt (anglais). Un seul cadre, sans texte.',
                {'scene':scene,'decoupage':data['script']},VisualPlan,temperature=.4)
            if not plan['visual'].strip() or not plan['image_prompt'].strip():raise ReviewNeeded('Plan vide; utiliser + pour reessayer.')
            scene.update(plan);return {'data':data}
        selected=proposal(w,'script',w['chosen']['script'])['data']
        narrative=selected['narrative']
        board=llm.ask('storyboard',prompt,{'narration_validee':narrative,'versions_precedentes':previous,'a_reviser':job['base']},Storyboard,temperature=.4)
        if [s['id'] for s in board['scenes']]!=[s['id'] for s in narrative['scenes']]:raise ReviewNeeded('Decoupage incomplet : tous les plans doivent etre presents dans leur ordre.')
        if any(not s['visual'].strip() or not s['image_prompt'].strip() for s in board['scenes']):raise ReviewNeeded('Un plan est vide : utiliser + pour reessayer.')
        script=Script.model_validate({**narrative,'visual_bible':board['visual_bible'],
            'scenes':[{**s,**v} for s,v in zip(narrative['scenes'],board['scenes'])]}).model_dump()
        return {'data':{'script':script,'review':selected.get('review',{}),'human_edited':selected.get('human_edited',False)}}
    if stage=='images':
        script=deepcopy(proposal(w,'storyboard',w['chosen']['storyboard'])['data']['script'])
        scene=next(s for s in script['scenes'] if s['id']==job['target']);scene['image_prompt']=prompt;script['scenes']=[scene]
        result=image_assets(MediaContext(ctx,job),llm,script)['scenes'][0]
        return {'data':result,'score':result['score_100']}
    raise ValueError('Calcul inconnu')
