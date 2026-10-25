import argparse,datetime,json,os,re,shutil,sqlite3,sys,time,tomllib
from pathlib import Path
from filelock import FileLock,Timeout

def pull_model(root,model):
    import subprocess,tomllib
    import httpx
    cfg=tomllib.loads((root/'config.toml').read_text(encoding='utf-8-sig'))
    url=cfg['models']['ollama_url'].rstrip('/')
    # Stream pull from the same Ollama server as the application.
    print('Preparation de '+model,flush=True)
    with httpx.Client(timeout=httpx.Timeout(120,connect=15),trust_env=False) as client:
        with client.stream('POST',url+'/api/pull',json={'model':model,'stream':True}) as response:
            response.raise_for_status()
            last=None
            for line in response.iter_lines():
                if not line:continue
                entry=json.loads(line)
                if entry.get('error'):raise RuntimeError(entry['error'])
                total=entry.get('total',0)
                percent=int(100*entry.get('completed',0)/total) if total else None
                key=(entry.get('status'),percent//5 if percent is not None else None)
                if key!=last:
                    print(entry.get('status','')+(f' {percent}%' if percent is not None else ''),flush=True);last=key
        check=client.post(url+'/api/show',json={'model':model});check.raise_for_status()
        capabilities=check.json().get('capabilities',[])
        if ('vision' if 'vl:' in model else 'completion') not in capabilities:raise RuntimeError('Capacite du modele manquante: '+model)


def ensure_model(root):
    pull_model(root,'qwen3:32b')
    pull_model(root,'qwen3-vl:8b-instruct')

def upgrade_models(models):
    return dict(models,text='qwen3:32b',vision='qwen3-vl:8b-instruct',context=16384,request_timeout_seconds=1800)

def upgrade_toml(text):
    match=re.search(r'(?ms)^\[models\]\s*\n(.*?)(?=^\[|\Z)',text)
    if not match:raise ValueError('Section models absente')
    body=match.group(1)
    for key,value in upgrade_models({}).items():
        line=key+' = '+json.dumps(value)
        if re.search(r'(?m)^'+key+r'\s*=',body):body=re.sub(r'(?m)^'+key+r'\s*=.*$',lambda m:line,body)
        else:body+=line+'\n'
    result=text[:match.start(1)]+body+text[match.end(1):]
    tomllib.loads(result)
    return result

def apply(root):
    root=Path(root).resolve();data=root/'data'
    if not (root/'autoshort/core.py').is_file():raise RuntimeError('Extraire a cote de LANCER.cmd')
    data.mkdir(exist_ok=True)
    with FileLock(str(data/'server.lock'),timeout=0),FileLock(str(data/'gpu.lock'),timeout=0):
        files=('editorial.py','llm.py','research.py','media.py','assets.py')
        changes={}
        for name in files:
            source=Path(__file__).parent/name;target=root/'autoshort'/name
            compile(source.read_text(encoding='utf-8'),str(source),'exec')
            if not target.exists():raise RuntimeError('Module absent: '+name)
            changes[target]=source.read_bytes()
        config=root/'config.toml'
        changes[config]=upgrade_toml(config.read_text(encoding='utf-8-sig')).encode('utf-8')
        rows=[];db=data/'autoshort.sqlite'
        if db.exists():
            with sqlite3.connect(db) as conn:
                rows=conn.execute("SELECT id,status,step FROM runs ORDER BY created DESC").fetchall()
        incomplete={'QUEUED','RUNNING','FAILED','NEEDS_REVIEW','INTERRUPTED','CANCELLED'}
        for rid,status,step in rows:
            if status not in incomplete:continue
            p=data/'runs'/rid/'config.json'
            if not p.exists():continue
            cfg=json.loads(p.read_text(encoding='utf-8-sig'))
            cfg['models']=upgrade_models(cfg['models'])
            changes[p]=json.dumps(cfg,ensure_ascii=False,indent=2).encode('utf-8')
        # Downloads precede any code/configuration change.
        ensure_model(root)
        backup=data/'code-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        for path in changes:
            dest=backup/path.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,dest)
        try:
            for path,content in changes.items():
                tmp=path.with_name(path.name+'.patch-tmp');tmp.write_bytes(content);os.replace(tmp,path)
        except Exception:
            for path in changes:shutil.copy2(backup/path.relative_to(root),path)
            raise
        requeued=None
        # Resume only the latest interrupted research; no batch execution.
        for rid,status,step in rows:
            if status in {'FAILED','NEEDS_REVIEW','INTERRUPTED'} and step in {'research','documentalist','fact_checker','topic_editor'} and not (data/'runs'/rid/'research.json').exists():
                with sqlite3.connect(db) as conn:
                    conn.execute("UPDATE runs SET status='QUEUED',error='',cancel=0,updated=? WHERE id=?",(time.time(),rid))
                requeued=rid;break
        result={'patch':'0.1.5','backup':str(backup),'requeued':requeued,'model':'qwen3:32b'}
        (backup/'patch-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
    try:print(json.dumps(apply(a.root),indent=2))
    except Timeout:
        print('Fermer la console AutoShort puis relancer. Aucun changement applique.',file=sys.stderr);sys.exit(1)
    except Exception as exc:
        print('Echec: '+str(exc),file=sys.stderr);sys.exit(1)
