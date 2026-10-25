"""Mise a jour locale, sans telechargement ni suppression de donnees."""
import argparse,datetime,json,os,py_compile,shutil,sqlite3,sys
from pathlib import Path
from filelock import FileLock,Timeout

DEFAULT_RUN='220d50286eea40cf'

def apply(root,run_id=DEFAULT_RUN):
    root=Path(root).resolve()
    target=root/'autoshort'/'editorial.py'
    source=Path(__file__).parent/'editorial.py'
    if not target.is_file() or not (root/'autoshort'/'core.py').is_file():
        raise RuntimeError('Extraire les fichiers du correctif dans le dossier contenant INSTALLER.cmd et LANCER.cmd.')
    data=root/'data';data.mkdir(exist_ok=True)
    with FileLock(str(data/'server.lock'),timeout=0),FileLock(str(data/'gpu.lock'),timeout=0):
        compile(source.read_text(encoding='utf-8'),str(source),'exec')
        # Les imports de cette mise a jour utilisent uniquement les dependances deja installees.
        sys.path.insert(0,str(root))
        import importlib.util
        spec=importlib.util.spec_from_file_location('autoshort._editorial_patch_check',source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        backup=data/'code-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True)
        shutil.copy2(target,backup/'editorial.py')
        temp=target.with_suffix('.py.patch-tmp')
        shutil.copyfile(source,temp);os.replace(temp,target)
        result={'patch':'0.1.1','backup':str(backup),'run_id':run_id,'requeued':False}
        db=data/'autoshort.sqlite'
        if db.exists():
            with sqlite3.connect(db,timeout=10) as conn:
                row=conn.execute('SELECT status,step FROM runs WHERE id=?',(run_id,)).fetchone()
                checkpoint=data/'runs'/run_id/'editorial.json'
                if row and row[0] in ('NEEDS_REVIEW','FAILED','INTERRUPTED','CANCELLED') and row[1]=='editorial' and not checkpoint.exists():
                    import time
                    conn.execute("UPDATE runs SET status='QUEUED',error='',cancel=0,updated=? WHERE id=?",(time.time(),run_id))
                    result['requeued']=True
                elif row:result['note']='Etat conserve: '+str(row)+'. Utiliser Reprendre si necessaire.'
                else:result['note']='Run non trouve; le correctif sera utilise par les nouvelles productions.'
        (backup/'patch-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--run-id',default=DEFAULT_RUN);a=p.parse_args()
    try:print(json.dumps(apply(a.root,a.run_id),ensure_ascii=False,indent=2))
    except Timeout:
        print('Fermer la fenetre LANCER.cmd / AutoShort puis relancer APPLIQUER-CORRECTIF.cmd. Aucune modification effectuee.',file=sys.stderr);sys.exit(1)
    except Exception as exc:
        print('Correctif interrompu: '+str(exc),file=sys.stderr);sys.exit(1)
