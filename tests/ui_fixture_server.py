"""Isolated browser-test server. AI stand-ins only; never points at user data.
Run: python tests/ui_fixture_server.py (then node tests/browser_guided.cjs).
"""
import asyncio,os,sys,tempfile,shutil,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
workspace=tempfile.TemporaryDirectory(prefix='autoshort-ui-')
os.environ['AUTOSHORT_ROOT']=workspace.name
shutil.copy(root/'config.toml',Path(workspace.name)/'config.toml')
from pytest import MonkeyPatch
from test_guided import services
from autoshort import api,core,pipeline,live_generation
from test_live import fake_generator
patch=MonkeyPatch();calls=services(patch)
def progressive(ctx,llm,job,w):
    if job['kind']=='proposal':time.sleep(3)
    return fake_generator(ctx,llm,job,w)
live_generation.generate=progressive
api.diagnose=lambda:{'ok':True,'checks':[{'ok':True,'name':'Test interface','detail':'Services IA simules, donnees temporaires'}]}
def render(ctx,script,audio,images):
    calls.append('render');folder=ctx.path/'export';folder.mkdir(exist_ok=True)
    path=folder/'video.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=teal:s=180x320:d=1','-f','lavfi','-i','anullsrc=r=24000:cl=mono','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)],check=True)
    (folder/'description.txt').write_text(script['description'])
    return {'path':str(path),'sha256':core.digest(path),'duration':1}
pipeline.render=render
async def dispatcher(stop):
    while not stop.is_set():
        queued=[r for r in core.runs() if r['status']=='QUEUED' and not r['cancel']]
        if queued:await asyncio.to_thread(pipeline.execute,queued[-1]['id'])
        await asyncio.sleep(.1)
api.dispatcher=dispatcher
if __name__=='__main__':
    import uvicorn
    uvicorn.run(api.app,host='127.0.0.1',port=8765)
