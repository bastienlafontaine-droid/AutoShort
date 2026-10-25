import zipfile,datetime
from pathlib import Path
root=Path(__file__).resolve().parents[1]
output=root/('diagnostic-autoshort-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
ids=('220d50286eea40cf','63f3ad50c54e454e')
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
    for rid in ids:
        folder=root/'data'/'runs'/rid
        for p in folder.rglob('*'):
            if p.is_file() and p.suffix in ('.json','.jsonl','.log'):
                z.write(p,Path(rid)/p.relative_to(folder))
print('Diagnostic cree: '+str(output))
print('Contient scripts, sources et traces de ces deux runs; aucun fichier .env ni cle Brave.')
