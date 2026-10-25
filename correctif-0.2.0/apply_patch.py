import argparse,datetime,json,os,re,shutil,sys,tomllib
from pathlib import Path
from filelock import FileLock,Timeout


def upgrade_config(text):
    config=tomllib.loads(text)
    values={'story_pipeline':2,'shot_seconds':3.3,'min_seconds':35,'max_seconds':95,
            'progress_bar':False,'style':'clean cinematic editorial illustration, clear subject, restrained colors',
            'max_search_calls':max(40,config['production']['max_search_calls']),
            'max_llm_calls':max(120,config['production']['max_llm_calls']),
            'max_run_minutes':max(360,config['production']['max_run_minutes'])}
    match=re.search(r'(?ms)^\[production\]\s*\n(.*?)(?=^\[|\Z)',text)
    if not match:raise RuntimeError('Section production absente')
    body=match.group(1)
    for key,value in values.items():
        line=key+' = '+json.dumps(value,ensure_ascii=False)
        pattern=r'(?m)^'+key+r'\s*=.*$'
        if re.search(pattern,body):body=re.sub(pattern,lambda m:line,body)
        else:body+='\n'+line+'\n'
    text=text[:match.start(1)]+body+text[match.end(1):]
    tomllib.loads(text)
    return text


def apply(root):
    root=Path(root).resolve();data=root/'data'
    if not (root/'LANCER.cmd').is_file() or not (root/'autoshort/core.py').is_file():raise RuntimeError('Extraire a cote de LANCER.cmd')
    data.mkdir(exist_ok=True)
    with FileLock(str(data/'server.lock'),timeout=0),FileLock(str(data/'gpu.lock'),timeout=0):
        changes={}
        for name in ('research.py','editorial.py','storytelling.py','audio.py','assets.py','render.py'):
            source=Path(__file__).parent/name
            compile(source.read_text(encoding='utf-8'),str(source),'exec')
            target=root/'autoshort'/name
            if name!='storytelling.py' and not target.is_file():raise RuntimeError('Module absent: '+name)
            changes[target]=source.read_bytes()
        config=root/'config.toml'
        changes[config]=upgrade_config(config.read_text(encoding='utf-8-sig')).encode('utf-8')
        backup=data/'code-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True)
        originals={p:p.read_bytes() if p.exists() else None for p in changes}
        for p,content in originals.items():
            if content is not None:
                out=backup/p.relative_to(root);out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(content)
        try:
            for p,content in changes.items():
                tmp=p.with_name(p.name+'.patch-tmp');tmp.write_bytes(content);os.replace(tmp,p)
        except Exception:
            for p,content in originals.items():
                if content is None:p.unlink(missing_ok=True)
                else:p.write_bytes(content)
            raise
        result={'patch':'0.2.0','backup':str(backup),'existing_runs':'preserved','next_action':'Creer une nouvelle production'}
        (backup/'patch-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
    try:print(json.dumps(apply(a.root),indent=2))
    except Timeout:
        print('Fermer la console AutoShort puis relancer ce correctif.',file=sys.stderr);sys.exit(1)
    except Exception as exc:
        print('Echec: '+str(exc),file=sys.stderr);sys.exit(1)
