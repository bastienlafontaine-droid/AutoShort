from __future__ import annotations
import html,json,traceback,os,subprocess
from pathlib import Path
from typing import TypedDict
from langgraph.graph import StateGraph,START,END
from filelock import FileLock
from .core import Context,DATA,ROOT,ReviewNeeded,Cancelled,update,read,dump,digest
from .llm import LLM
from .research import discover,research
from .editorial import write_script
from .assets import audio_assets,image_assets
from .render import render,final_check,command
from .schemas import Verdict

class State(TypedDict,total=False):
    candidates:dict
    research:dict
    editorial:dict
    audio:dict
    images:dict
    render:dict
    final:dict

STAGES=['discover','research','editorial','audio','images','render','final']

def verify_cached(ctx):
    # Le contenu valide est immutable. Un fichier manquant ou altere invalide ses descendants.
    for stage in ('audio','images','render'):
        p=ctx.path/f'{stage}.json'
        if not p.exists():continue
        payload=read(p);assets=payload.get('scenes',[payload])
        if any(not Path(a['path']).is_file() or digest(a['path'])!=a['sha256'] for a in assets):
            invalidate(ctx.path,stage)
            ctx.event(stage,'Cache invalide: regeneration des dependances')

def invalidate(folder,stage):
    for name in STAGES[STAGES.index(stage):]:(folder/f'{name}.json').unlink(missing_ok=True)
    (folder/'export'/'quality_report.html').unlink(missing_ok=True)
    (folder/'export'/'manifest.json').unlink(missing_ok=True)

def final(ctx,llm,state):
    technical=final_check(ctx,state['render'])
    from PIL import Image,ImageOps,ImageDraw
    folder=ctx.path/'export';timeline=state['render']['timeline'];thumbs=[]
    for t in timeline:
        out=folder/f"sample_{t['scene']:02d}.jpg"
        command(ctx,['ffmpeg','-hide_banner','-y','-ss',str(t['start']+t['duration']/2),'-i',str(folder/'video.mp4'),'-frames:v','1',str(out)])
        with Image.open(out) as image:thumbs.append(ImageOps.fit(image,(270,480)))
    sheet=Image.new('RGB',(270*3,500*((len(thumbs)+2)//3)),(25,25,25));draw=ImageDraw.Draw(sheet)
    for i,img in enumerate(thumbs):
        x=(i%3)*270;y=(i//3)*500;sheet.paste(img,(x,y));draw.text((x+8,y+482),f'Scene {i+1}',fill='white')
    sheet.save(folder/'contact_sheet.jpg')
    review=llm.ask('final_visual',
       'Controle cette planche de captures du montage: coherence visuelle, sous-titres presents et lisibles, absence de gros artefacts. Une planche ne permet pas de juger la fluidite ni la voix. Refuse uniquement pour des defauts clairement visibles; donne correction concrete.',
       {'title':state['editorial']['script']['title']},Verdict,image=folder/'contact_sheet.jpg',temperature=0.1)
    ctx.artifact('export/final_visual_review.json',review)
    llm.unload()
    if not review['accepted'] or review['score']<ctx.cfg['production']['min_visual_score']:
        raise ReviewNeeded('Controle final visuel non valide: '+'; '.join(review['issues']))
    return {'technical':technical,'visual':review}

def report(ctx,state):
    folder=ctx.path/'export';folder.mkdir(exist_ok=True)
    script=state.get('editorial',{}).get('script',{})
    dossier=state.get('research',{})
    dump(folder/'sources.json',dossier)
    manifest={'version':'0.1.0','run_id':ctx.rid,'config':ctx.cfg,'state':state,'usage':ctx.usage,
      'models_note':'Les tags Ollama et revisions HF doivent etre figes apres benchmark; inventory.json consigne les versions disponibles.',
      'rights':{'images':'SDXL base: licence OpenRAIL++ a respecter; images = reconstitutions.',
               'voice':'Kokoro Apache-2.0; voix ff_siwis issue du corpus SIWIS (CC BY 4.0), voir LICENSES.md.',
               'music':ctx.cfg['production'].get('music','') or 'Aucune'}}
    dump(folder/'manifest.json',manifest)
    title=html.escape(script.get('title',ctx.info['theme']))
    facts=''.join('<li>'+html.escape(c['text'])+'</li>' for c in dossier.get('dossier',{}).get('claims',[]))
    sources=''.join('<li><a href="'+html.escape(s['url'],quote=True)+'">'+html.escape(s['title'])+'</a></li>' for s in dossier.get('sources',[]))
    detail=html.escape(json.dumps({'usage':ctx.usage,'final':state.get('final',{}),'editorial':state.get('editorial',{}).get('review',{})},ensure_ascii=False,indent=2))
    (folder/'quality_report.html').write_text(f'''<!doctype html><html lang="fr"><meta charset="utf-8"><title>{title}</title>
<style>body{{font:16px system-ui;max-width:1000px;margin:40px auto;background:#101722;color:#e5edf5;padding:20px}}a{{color:#61d6be}}video{{max-height:650px;max-width:100%}}pre{{white-space:pre-wrap;background:#192331;padding:20px}}li{{margin:12px 0}}</style>
<h1>{title}</h1><p>Production locale — validation automatique, publication manuelle.</p><video src="video.mp4" controls></video>
<h2>Faits retenus</h2><ul>{facts}</ul><h2>Sources</h2><ul>{sources}</ul>
<h2>Controles et limites</h2><p>Les juges locaux ne garantissent ni la veracite ni les vues. Visionner et ecouter avant publication.
Alignement des sous-titres par ASR et interpolation locale. Images generees: reconstitutions, jamais archives authentiques.</p>
<pre>{detail}</pre><p>Les licences et attributions sont dans LICENSES.md du projet.</p></html>''',encoding='utf-8')

def execute(rid):
    DATA.mkdir(exist_ok=True)
    # Un verrou OS protege tous les sous-processus de CE projet. Il ne reserve pas physiquement le GPU.
    with FileLock(str(DATA/'gpu.lock'),timeout=1):
        ctx=Context(rid);llm=LLM(ctx);state={}
        update(rid,status='RUNNING',error='')
        try:
            verify_cached(ctx)
            graph=StateGraph(State)
            graph.add_node('step_discover',lambda s:{'candidates':ctx.stage('discover',lambda:discover(ctx,llm))})
            graph.add_node('step_research',lambda s:{'research':ctx.stage('research',lambda:research(ctx,llm,s['candidates']))})
            graph.add_node('step_editorial',lambda s:{'editorial':ctx.stage('editorial',lambda:write_script(ctx,llm,s['research']))})
            graph.add_node('step_audio',lambda s:{'audio':ctx.stage('audio',lambda:audio_assets(ctx,llm,s['editorial']['script']))})
            graph.add_node('step_images',lambda s:{'images':ctx.stage('images',lambda:image_assets(ctx,llm,s['editorial']['script']))})
            graph.add_node('step_render',lambda s:{'render':ctx.stage('render',lambda:render(ctx,s['editorial']['script'],s['audio'],s['images']))})
            graph.add_node('step_final',lambda s:{'final':ctx.stage('final',lambda:final(ctx,llm,s))})
            graph.add_edge(START,'step_'+STAGES[0])
            for a,b in zip(STAGES,STAGES[1:]):graph.add_edge('step_'+a,'step_'+b)
            graph.add_edge('step_'+STAGES[-1],END)
            state=graph.compile().invoke({},config={'recursion_limit':30})
            ctx.finish_time();report(ctx,state);update(rid,status='READY',step='done')
        except Cancelled as exc:update(rid,status='CANCELLED',error=str(exc))
        except ReviewNeeded as exc:update(rid,status='NEEDS_REVIEW',error=str(exc))
        except Exception as exc:
            (ctx.path/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
            update(rid,status='FAILED',error=f'{type(exc).__name__}: consulter error.log et media.log')
        finally:
            ctx.finish_time()
            try:llm.unload()
            except Exception:pass
