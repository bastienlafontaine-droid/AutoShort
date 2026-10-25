"""Workflow contracts exercised with deterministic AI/media stand-ins."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from autoshort import core,pipeline,guided,api


def services(monkeypatch):
    calls=[]
    narrative={'title':'Une invention inattendue','description':'Images de reconstitution.',
               'scenes':[{'id':i,'narration':f'Voici le moment {i} de cette histoire documentee.', 'claim_ids':['C1']} for i in range(1,6)]}
    class LLM:
        def __init__(self,ctx):pass
        def unload(self):pass
        def ask(self,*args,**kw):
            return {'ideas':[{'index':i,'score':90-i*5,'reason':'Un angle clair et documentable.'} for i in range(3)]}
    monkeypatch.setattr(pipeline,'LLM',LLM)
    def discover(*args):
        calls.append('discover')
        return {'candidates':[{'title':f'Idee {i+1}','angle':'Une histoire et son denouement.','query':f'histoire {i}'} for i in range(3)]}
    def research(*args):
        calls.append('research')
        return {'dossier':{'title':'Test','claims':[{'id':'C1','text':'Un fait'}]},'sources':[]}
    def board(ctx,llm,research,payload):
        calls.append('storyboard')
        return {'script':{**payload['narrative'],'visual_bible':'Illustration','scenes':[{**s,'visual':'Un objet ancien','image_prompt':'An old object'} for s in payload['narrative']['scenes']]}}
    def script(ctx,llm,research,narrative_only=False):
        calls.append('script')
        payload={'narrative':narrative,'review':{'score':8},'prefix':'fixture'}
        return payload if narrative_only else board(ctx,llm,research,payload)
    def audio(ctx,llm,script):
        calls.append('audio');return {'scenes':[],'duration':1}
    def images(ctx,llm,script):
        from PIL import Image
        calls.append('images');candidates=[]
        for s in script['scenes']:
            for attempt in (1,2):
                p=ctx.path/'images'/f'{s["id"]}_{attempt}.png';p.parent.mkdir(exist_ok=True)
                Image.new('RGB',(90,160),(50*s['id'],60*attempt,100)).save(p)
                candidates.append({'scene':s['id'],'attempt':attempt,'path':str(p),'sha256':core.digest(p),'score_100':70+attempt*10})
        result={'scenes':candidates[1::2],'threshold_100':80,'scoring':'mean_quality_relevance_100'}
        ctx.artifact('images/selection.json',{**result,'candidates':candidates})
        return result
    def render(ctx,script,audio,images):
        calls.append('render');p=ctx.path/'export/video.mp4';p.parent.mkdir(exist_ok=True);p.write_bytes(b'fixture')
        return {'path':str(p),'sha256':core.digest(p),'duration':1}
    def final(*args):calls.append('final');return {'accepted':True}
    for name,fn in [('discover',discover),('research',research),('write_script',script),('build_storyboard',board),('audio_assets',audio),('image_assets',images),('render',render),('final',final)]:monkeypatch.setattr(pipeline,name,fn)
    return calls

@pytest.fixture
def harness(workspace,monkeypatch):
    for module in (pipeline,api):monkeypatch.setattr(module,'DATA',core.DATA)
    monkeypatch.setattr(api,'ROOT',core.ROOT)
    calls=services(monkeypatch)
    client=TestClient(api.app)
    headers={'Origin':'http://127.0.0.1:8765','X-AutoShort-Token':api.TOKEN}
    return client,headers,calls

def pending(rid):return guided.workflow(core.DATA/'runs'/rid)['pending']

def approve(client,h,rid,changes=None):
    p=pending(rid)
    return client.post(f'/api/runs/{rid}/approve',headers=h,json={'stage':p['stage'],'input_hash':p['input_hash'],'changes':changes or {}})

def test_guided_complete_edit_choose_resume(harness):
    client,h,calls=harness
    rid=client.post('/api/runs',headers=h,json={'theme':'Histoire de test'}).json()['id']
    folder=core.DATA/'runs'/rid
    pipeline.execute(rid)
    assert pending(rid)['stage']=='idea' and calls==['discover']
    assert len(pending(rid)['value']['ideas'])==3
    assert client.post(f'/api/runs/{rid}/resume',headers=h,json={}).status_code==409
    assert approve(client,h,rid,{'id':'1'}).status_code==200
    pipeline.execute(rid)
    assert pending(rid)['stage']=='script' and 'storyboard' not in calls
    edited=pending(rid)['value']['narrative'];edited['title']='Titre modifie';edited['scenes'][0]['narration']='Texte modifie par le createur.'
    assert approve(client,h,rid,{'narrative':edited}).status_code==200
    pipeline.execute(rid)
    assert pending(rid)['stage']=='storyboard' and 'audio' not in calls
    assert pending(rid)['value']['script']['title']=='Titre modifie'
    plans=pending(rid)['value']['script']['scenes'];plans[0]['visual']='Correction du plan'
    assert approve(client,h,rid,{'scenes':plans}).status_code==200
    pipeline.execute(rid)
    assert pending(rid)['stage']=='images' and 'render' not in calls
    # An ordinary stop/resume preserves approved steps, but cannot bypass image approval.
    client.post(f'/api/runs/{rid}/cancel',headers=h,json={})
    client.post(f'/api/runs/{rid}/resume',headers=h,json={})
    pipeline.execute(rid)
    assert pending(rid)['stage']=='images'
    assert calls.count('research')==calls.count('script')==calls.count('storyboard')==calls.count('images')==1
    assert approve(client,h,rid,{'choices':{'1':1}}).status_code==200
    pipeline.execute(rid)
    assert core.run_info(rid)['status']=='READY'
    manifest=core.read(folder/'export/manifest.json')
    assert manifest['state']['images']['scenes'][0]['attempt']==1
    assert manifest['state']['editorial']['script']['scenes'][0]['visual']=='Correction du plan'
    assert calls[-2:]==['render','final']

def test_auto_no_pause_and_legacy_default(harness):
    client,h,calls=harness
    rid=client.post('/api/runs',headers=h,json={'theme':'Histoire de test','auto':True}).json()['id']
    pipeline.execute(rid)
    assert core.run_info(rid)['status']=='READY'
    assert not guided.workflow(core.DATA/'runs'/rid).get('pending')
    assert calls[-1]=='final'
    folder=core.DATA/'runs'/rid;request=core.read(folder/'request.json');request.pop('auto');core.dump(folder/'request.json',request)
    assert guided.is_auto(folder)

def test_rejected_subject_offers_alternatives(harness,monkeypatch):
    client,h,calls=harness;rid=core.new_run('Histoire de test',auto=False)
    pipeline.execute(rid);approve(client,h,rid,{'id':'0'})
    def reject(*a):raise core.ReviewNeeded('Aucun sujet valide parmi les candidats examines. Sources insuffisantes')
    monkeypatch.setattr(pipeline,'research',reject)
    pipeline.execute(rid)
    assert core.run_info(rid)['status']=='AWAITING_APPROVAL'
    assert [i['id'] for i in pending(rid)['value']['ideas']]==['1','2']
    assert '0' in pending(rid)['value']['rejected']
    assert 'script' not in calls

def test_stale_invalid_and_duplicate_approvals(harness):
    client,h,calls=harness;rid=core.new_run('Histoire de test',auto=False)
    pipeline.execute(rid)
    p=pending(rid)
    assert client.post(f'/api/runs/{rid}/approve',headers=h,json={'stage':'images','input_hash':p['input_hash']}).status_code==422
    assert approve(client,h,rid,{'id':'missing'}).status_code==422
    assert approve(client,h,rid,{'id':'0'}).status_code==200
    assert client.post(f'/api/runs/{rid}/approve',headers=h,json={'stage':'idea','input_hash':p['input_hash'],'changes':{'id':'0'}}).status_code==409

def test_failure_resume_preserves_script(harness,monkeypatch):
    client,h,calls=harness;rid=core.new_run('Histoire de test',auto=False)
    pipeline.execute(rid);approve(client,h,rid,{'id':'0'});pipeline.execute(rid);approve(client,h,rid)
    original=pipeline.build_storyboard
    def fail(*a):raise RuntimeError('temporary')
    monkeypatch.setattr(pipeline,'build_storyboard',fail);pipeline.execute(rid)
    assert core.run_info(rid)['status']=='FAILED'
    monkeypatch.setattr(pipeline,'build_storyboard',original)
    client.post(f'/api/runs/{rid}/resume',headers=h,json={});pipeline.execute(rid)
    assert pending(rid)['stage']=='storyboard' and calls.count('script')==1

def test_selected_alternate_missing_invalidates_only_media(harness):
    client,h,calls=harness;rid=core.new_run('Histoire de test',auto=False)
    pipeline.execute(rid);approve(client,h,rid,{'id':'0'});pipeline.execute(rid);approve(client,h,rid)
    pipeline.execute(rid);approve(client,h,rid);pipeline.execute(rid);approve(client,h,rid,{'choices':{'1':1}})
    folder=core.DATA/'runs'/rid
    selected=guided.workflow(folder)['approvals']['images']['value']['scenes'][0]
    Path(selected['path']).unlink()
    pipeline.execute(rid)
    assert pending(rid)['stage']=='images'
    assert calls.count('script')==1 and calls.count('storyboard')==1
    assert 'render' not in calls

def test_budget_error_does_not_reject_chosen_idea(harness,monkeypatch):
    client,h,calls=harness;rid=core.new_run('Histoire de test',auto=False)
    pipeline.execute(rid);approve(client,h,rid,{'id':'0'})
    def fail(*a):raise core.ReviewNeeded('Budget search atteint')
    monkeypatch.setattr(pipeline,'research',fail);pipeline.execute(rid)
    w=guided.workflow(core.DATA/'runs'/rid)
    assert w['rejected']=={} and 'idea' in w['approvals']
    assert core.run_info(rid)['status']=='NEEDS_REVIEW'

def test_actual_story_writer_stops_before_visual_generation(ctx):
    from autoshort import storytelling
    ctx.cfg['production']['story_pipeline']=3
    narrative={'title':'Titre','description':'Description','scenes':[{'id':i,'narration':' '.join(['histoire']*20),'claim_ids':['C1']} for i in range(1,6)]}
    calls=[]
    class LLM:
        def ask(self,role,*args,**kwargs):
            calls.append(role)
            if role=='writer':return narrative
            if role=='story_selector':return {'selected':1,'reason':'Clair','corrections':[]}
            raise AssertionError('Visual generation before approval')
    result=storytelling.write_story(ctx,LLM(),{'dossier':{'claims':[{'id':'C1','text':'Fait'}]}},narrative_only=True)
    assert result['narrative']==narrative
    assert calls==['writer','writer','writer','story_selector']
