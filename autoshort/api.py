import asyncio,contextlib,json,os,secrets,signal,subprocess,sys
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel,Field
from filelock import FileLock,Timeout
from .core import ROOT,DATA,new_run,runs,run_info,update,read
from .doctor import diagnose
from . import guided,live

TOKEN=secrets.token_urlsafe(32)
ALLOWED_ORIGINS={'http://127.0.0.1:8765','http://localhost:8765'}

async def dispatcher(stop):
    while not stop.is_set():
        queued=[x for x in runs() if x['status']=='QUEUED' and not x['cancel']]
        if not queued:
            await asyncio.sleep(1);continue
        run=queued[-1];update(run['id'],status='RUNNING')
        p=DATA/'runs'/run['id'];f=(p/'worker.log').open('a',encoding='utf-8')
        proc=subprocess.Popen([sys.executable,'-m','autoshort.cli','worker',run['id']],cwd=ROOT,stdout=f,stderr=f,
                              start_new_session=(os.name!='nt'))
        try:
            while proc.poll() is None:
                if stop.is_set():
                    if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    else:os.killpg(proc.pid,signal.SIGTERM)
                    await asyncio.to_thread(proc.wait,10)
                    update(run['id'],status='INTERRUPTED',error='Application fermee; reprendre la production')
                    break
                await asyncio.sleep(.5)
            if run_info(run['id'])['status']=='RUNNING':update(run['id'],status='FAILED',error='Worker interrompu. Consulter worker.log puis reprendre.')
        finally:f.close()

@asynccontextmanager
async def lifespan(app):
    DATA.mkdir(exist_ok=True)
    lock=FileLock(str(DATA/'server.lock'),timeout=0)
    lock.acquire()
    # Reprise explicite apres arret brutal, jamais double execution automatique.
    for r in runs():
        if r['status']=='RUNNING':update(r['id'],status='INTERRUPTED',error='Execution interrompue. Cliquer Reprendre.')
    stop=asyncio.Event();task=asyncio.create_task(dispatcher(stop))
    try:yield
    finally:
        stop.set();await task;lock.release()

app=FastAPI(title='AutoShort Local',lifespan=lifespan,docs_url=None,redoc_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','testserver'])

@app.middleware('http')
async def protect(request:Request,call_next):
    from fastapi.responses import JSONResponse
    if request.method in ('POST','PUT','DELETE','PATCH'):
        if request.headers.get('origin') not in ALLOWED_ORIGINS or not secrets.compare_digest(request.headers.get('x-autoshort-token',''),TOKEN):
            return JSONResponse({'detail':'Requete non autorisee'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    return response

@app.get('/')
def index():return FileResponse(Path(__file__).parent/'static'/'index.html')
@app.get('/app.js')
def js():return FileResponse(Path(__file__).parent/'static'/'app.js',media_type='text/javascript')
@app.get('/live.js')
def live_js():return FileResponse(Path(__file__).parent/'static'/'live.js',media_type='text/javascript')
@app.get('/style.css')
def css():return FileResponse(Path(__file__).parent/'static'/'style.css',media_type='text/css')
@app.get('/api/session')
def session():return {'token':TOKEN}
@app.get('/api/health')
def health():return diagnose()
@app.get('/api/runs')
def list_runs():return runs()
class Create(BaseModel):
    theme:str=Field(min_length=5,max_length=300)
    auto:bool=False
@app.post('/api/runs')
def create(body:Create):
    if len([r for r in runs() if r['status'] in ('QUEUED','RUNNING')])>=10:raise HTTPException(409,'File pleine (10 productions)')
    return {'id':new_run(body.theme,auto=body.auto)}
class Settings(BaseModel):brave_key:str=Field(min_length=10,max_length=300)
@app.post('/api/settings')
def settings(body:Settings):
    if '\n' in body.brave_key or '\r' in body.brave_key:raise HTTPException(400,'Cle invalide')
    path=ROOT/'.env';tmp=ROOT/'.env.tmp'
    lines=path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    lines=[l for l in lines if not l.startswith('BRAVE_API_KEY=')]+['BRAVE_API_KEY='+body.brave_key.strip()]
    tmp.write_text('\n'.join(lines)+'\n',encoding='utf-8');os.replace(tmp,path)
    return {'ok':True}

def existing(rid):
    try:return run_info(rid)
    except ValueError:raise HTTPException(404,'Production introuvable')
@app.get('/api/runs/{rid}')
def details(rid:str):
    info=existing(rid);p=DATA/'runs'/rid/'events.jsonl'
    info['events']=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()[-80:]] if p.exists() else []
    info['files']=[x.name for x in (DATA/'runs'/rid/'export').glob('*') if x.is_file() and x.suffix in ('.mp4','.jpg','.html','.json','.srt','.md','.txt') and not x.name.startswith(('scene_','assembled','sample_'))]
    folder=DATA/'runs'/rid
    info['progress']=guided.progress(info,folder)
    if not guided.is_auto(folder) and live.enabled(folder):
        w=live.snapshot(folder)
        info['progress']={'auto':False,'number':live.STAGES.index(w['stage'])+1,'live':w}
        if any(j['kind']=='research' and j['status'] in ('queued','running') for j in w['jobs']):info['progress']['number']=1
    return info
@app.post('/api/runs/{rid}/cancel')
def cancel(rid:str):
    existing(rid)
    folder=DATA/'runs'/rid
    lock_name='live.lock' if live.enabled(folder) and not guided.is_auto(folder) else 'approval.lock'
    with FileLock(str(folder/lock_name),timeout=5):
        r=existing(rid)
        if r['status'] in ('QUEUED','AWAITING_APPROVAL'):update(rid,status='CANCELLED',cancel=1)
        elif r['status']=='RUNNING':update(rid,cancel=1)
    return {'ok':True}
@app.post('/api/runs/{rid}/resume')
def resume(rid:str):
    existing(rid);folder=DATA/'runs'/rid
    lock_name='live.lock' if live.enabled(folder) and not guided.is_auto(folder) else 'approval.lock'
    with FileLock(str(folder/lock_name),timeout=5):
        r=existing(rid)
        if r['status'] in ('RUNNING','QUEUED','READY','AWAITING_APPROVAL'):raise HTTPException(409,'Etat incompatible')
        update(rid,status='QUEUED',error='',cancel=0)
    return {'ok':True}
@app.get('/api/runs/{rid}/files/{name}')
def file(rid:str,name:str):
    existing(rid)
    if name not in ('video.mp4','cover.jpg','subtitles.srt','script.md','sources.json','manifest.json','quality_report.html','contact_sheet.jpg','timeline.json','description.txt','technical_report.json','final_visual_review.json'):
        raise HTTPException(404)
    p=DATA/'runs'/rid/'export'/name
    if not p.is_file():raise HTTPException(404)
    return FileResponse(p)
@app.get('/api/runs/{rid}/logs')
def logs(rid:str):
    from fastapi.responses import PlainTextResponse
    existing(rid);folder=DATA/'runs'/rid;chunks=[]
    for name in ('error.log','worker.log','media.log','render.log'):
        p=folder/name
        if p.exists():chunks.append(name+'\n'+p.read_text(encoding='utf-8',errors='replace')[-12000:])
    return PlainTextResponse('\n\n'.join(chunks))


class Approval(BaseModel):
    stage:str
    input_hash:str
    changes:dict=Field(default_factory=dict)

@app.post('/api/runs/{rid}/approve')
def approve(rid:str,body:Approval):
    existing(rid)
    folder=DATA/'runs'/rid
    with FileLock(str(folder/'approval.lock'),timeout=5):
        if existing(rid)['status']!='AWAITING_APPROVAL':raise HTTPException(409,'La production n’attend pas de validation.')
        try:guided.approve(folder,body.stage,body.input_hash,body.changes)
        except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc))
        update(rid,status='QUEUED',error='',cancel=0)
    return {'ok':True}

@app.get('/api/runs/{rid}/images/{scene}/{attempt}')
def preview_image(rid:str,scene:int,attempt:int):
    existing(rid);folder=DATA/'runs'/rid
    p=folder/'images/selection.json'
    if not p.exists():raise HTTPException(404)
    candidate=next((c for c in read(p).get('candidates',[]) if c['scene']==scene and c['attempt']==attempt),None)
    if candidate is None:raise HTTPException(404)
    path=Path(candidate['path']).resolve()
    if not path.is_relative_to((folder/'images').resolve()) or not path.is_file():raise HTTPException(404)
    return FileResponse(path,media_type='image/png')


class GenerateRequest(BaseModel):
    stage:str
    prompt:str=Field(min_length=1,max_length=6000)
    target:int|None=None
    base_id:str|None=None
class ChooseRequest(BaseModel):
    stage:str
    proposal_id:str
class EditRequest(ChooseRequest):
    data:dict
    prompt:str=Field(default='',max_length=6000)

def live_action(rid,fn,*args):
    existing(rid);folder=DATA/'runs'/rid
    if guided.is_auto(folder) or not live.enabled(folder):raise HTTPException(409,'Action reservee au mode guide progressif.')
    try:return fn(folder,rid,*args)
    except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc))

@app.post('/api/runs/{rid}/generate')
def generate_proposal(rid:str,body:GenerateRequest):
    return {'id':live_action(rid,live.request_generation,body.stage,body.prompt,body.target,body.base_id)}
@app.post('/api/runs/{rid}/choose')
def choose_proposal(rid:str,body:ChooseRequest):
    live_action(rid,live.choose,body.stage,body.proposal_id);return {'ok':True}
@app.post('/api/runs/{rid}/edit')
def edit_proposal(rid:str,body:EditRequest):
    return {'id':live_action(rid,live.edit,body.stage,body.proposal_id,body.data,body.prompt)}
@app.post('/api/runs/{rid}/validate-images')
def validate_image_choices(rid:str):
    live_action(rid,live.validate_images);return {'ok':True}
@app.post('/api/runs/{rid}/retry-job/{jid}')
def retry_job(rid:str,jid:str):
    live_action(rid,live.retry,jid);return {'ok':True}
@app.get('/api/runs/{rid}/proposal-image/{pid}')
def proposal_image(rid:str,pid:str):
    existing(rid);folder=DATA/'runs'/rid
    try:
        p=live.proposal(live.snapshot(folder),'images',pid)
        live.check_image(folder,p['data'])
    except (ValueError,KeyError):raise HTTPException(404)
    return FileResponse(p['data']['path'],media_type='image/png')
