import importlib.util,json,shutil,subprocess,sys
import httpx
from .core import config,secret,ROOT,DATA,dump

def diagnose(gpu=False):
    cfg=config();checks=[]
    def add(name,ok,detail):checks.append({'name':name,'ok':bool(ok),'detail':detail})
    add('Python',sys.version_info[:2] in ((3,11),(3,12)),sys.version.split()[0])
    for name in ('ffmpeg','ffprobe'):
        add(name,shutil.which(name),shutil.which(name) or 'Relancer INSTALLER.cmd')
    add('Cle Brave',bool(secret('BRAVE_API_KEY')),'Configuree' if secret('BRAVE_API_KEY') else 'A renseigner dans l interface')
    for module in ('diffusers','kokoro','faster_whisper','langgraph','phonemizer','espeakng_loader'):
        add(module,importlib.util.find_spec(module) is not None,'Module installe' if importlib.util.find_spec(module) else 'Manquant')
    try:
        with httpx.Client(timeout=5,trust_env=False) as c:
            r=c.get(cfg['models']['ollama_url']+'/api/tags');r.raise_for_status();models=r.json()['models']
        names={m['name'] for m in models}
        for name in (cfg['models']['text'],cfg['models']['vision']):add(name,name in names,'Present' if name in names else 'Manquant: ollama pull '+name)
        DATA.mkdir(exist_ok=True);dump(DATA/'ollama_inventory.json',models)
    except Exception:add('Ollama',False,'Demarrer Ollama puis relancer le diagnostic')
    if gpu:
        try:
            code="import torch,json; x=torch.ones(1,device='cuda'); print(json.dumps({'cuda':torch.cuda.is_available(),'torch':torch.__version__,'device':torch.cuda.get_device_name(0),'sum':x.sum().item(),'free_gb':round(torch.cuda.mem_get_info()[0]/1024**3,1)}))"
            r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=60)
            add('CUDA',r.returncode==0,r.stdout.strip() if r.returncode==0 else r.stderr[-1500:])
        except Exception as exc:add('CUDA',False,type(exc).__name__)
    return {'ok':all(c['ok'] for c in checks),'checks':checks}
