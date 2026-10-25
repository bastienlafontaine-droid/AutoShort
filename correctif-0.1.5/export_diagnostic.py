import datetime,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
runs=sorted((root/'data/runs').glob('*'),key=lambda p:p.stat().st_mtime,reverse=True)[:5]
out=root/('diagnostic-autoshort-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for run in runs:
        for p in run.rglob('*'):
            if p.is_file() and p.suffix in ('.json','.jsonl','.log'):z.write(p,Path(run.name)/p.relative_to(run))
print(out)
