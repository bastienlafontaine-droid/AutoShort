"""Incremental queue contracts, including real concurrent UI requests during a job."""
from copy import deepcopy
from pathlib import Path
from threading import Event,Thread
import pytest
from fastapi.testclient import TestClient
from autoshort import core,api,pipeline,live,live_generation
from test_guided import services


def fake_generator(ctx,llm,job,w):
    """Shared with the isolated browser fixture; no real AI, paid API or user data."""
    kind=job['kind'];stage=job['stage']
    if kind=='research':
        value={'dossier':{'title':'Un fait','claims':[{'id':'C1','text':'Fait documente'}]},'sources':[]}
        core.dump(ctx.path/'research.json',value);return value
    if kind=='audio':
        value={'scenes':[],'duration':1};core.dump(ctx.path/'audio.json',value);return value
    if kind=='render':
        return original_generate(ctx,llm,job,w)
    if stage=='ideas':return {'data':{'title':'Une idee '+job['id'][:4],'angle':'Un angle documentable','query':'test'},'score':85}
    if stage=='script':
        n={'title':'Un script '+job['id'][:4],'description':'Images de reconstitution.',
           'scenes':[{'id':i,'narration':' '.join(['histoire']*20),'claim_ids':['C1']} for i in range(1,6)]}
        return {'data':{'narrative':n,'review':{'score':8}},'score':80}
    if stage=='storyboard':
        n=live.proposal(w,'script',w['chosen']['script'])['data']['narrative']
        return {'data':{'script':{**deepcopy(n),'visual_bible':'Illustration','scenes':[{**s,'visual':'Un objet ancien','image_prompt':'An old object'} for s in n['scenes']]}}}
    if stage=='images':
        from PIL import Image
        p=ctx.path/'guided_media'/job['id']/'image.png';p.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(90,160),(job['target']*40,100,100)).save(p)
        return {'data':{'scene':job['target'],'path':str(p),'sha256':core.digest(p),'score_100':80,'attempt':1,'prompt':job['prompt']},'score':80}
    raise AssertionError(job)

original_generate=live_generation.generate

@pytest.fixture
def setup(workspace,monkeypatch):
    services(monkeypatch)
    for mod in (pipeline,api):monkeypatch.setattr(mod,'DATA',core.DATA)
    monkeypatch.setattr(api,'ROOT',core.ROOT)
    monkeypatch.setattr(live_generation,'generate',fake_generator)
    rid=core.new_run('Histoires vraies de test',auto=False)
    client=TestClient(api.app);headers={'Origin':'http://127.0.0.1:8765','X-AutoShort-Token':api.TOKEN}
    def post(path,body=None):return client.post(f'/api/runs/{rid}/{path}',headers=headers,json=body or {})
    return rid,core.DATA/'runs'/rid,post,client

def test_progressive_priority_no_preemption_and_cancel_background(setup,monkeypatch):
    rid,folder,post,client=setup;second_started=Event();release=Event();calls=[]
    def generate(ctx,llm,job,w):
        calls.append((job['stage'],job['manual'],job['prompt']))
        if len(calls)==2:second_started.set();assert release.wait(8)
        return fake_generator(ctx,llm,job,w)
    monkeypatch.setattr(live_generation,'generate',generate)
    thread=Thread(target=pipeline.execute,args=(rid,));thread.start()
    try:
        assert second_started.wait(8)
        detail=client.get('/api/runs/'+rid).json();w=detail['progress']['live']
        assert len(w['proposals']['ideas'])==1
        assert sum(j['status']=='running' for j in w['jobs'])==1
        for prompt in ['MANUAL ONE','MANUAL TWO']:
            assert post('generate',{'stage':'ideas','prompt':prompt}).status_code==200
        assert len(calls)==2 # requests cannot interrupt or overlap the running generation
    finally:release.set();thread.join(10)
    assert not thread.is_alive()
    assert [c[2] for c in calls[2:4]]==['MANUAL ONE','MANUAL TWO']
    assert calls[-1][1] is False
    assert len(live.snapshot(folder)['proposals']['ideas'])==5


def advance(post,folder,stage):
    w=live.snapshot(folder);pid=w['proposals'][stage][0]['id']
    assert post('choose',{'stage':stage,'proposal_id':pid}).status_code==200
    return pid

def test_choose_during_second_variant_then_next_stage(setup,monkeypatch):
    rid,folder,post,client=setup;started=Event();release=Event();calls=[]
    def generate(ctx,llm,job,w):
        calls.append((job['stage'],job['kind']))
        if len(calls)==2:started.set();assert release.wait(8)
        return fake_generator(ctx,llm,job,w)
    monkeypatch.setattr(live_generation,'generate',generate)
    t=Thread(target=pipeline.execute,args=(rid,));t.start()
    try:
        assert started.wait(8);advance(post,folder,'ideas')
        w=live.snapshot(folder)
        assert w['jobs'][1]['status']=='running' and w['jobs'][2]['status']=='cancelled'
    finally:release.set();t.join(10)
    assert calls[2]==('script','research')
    assert len(live.snapshot(folder)['proposals']['ideas'])==2
    assert len(live.snapshot(folder)['proposals']['script'])==2


def test_full_live_edits_images_resume_and_render(setup):
    rid,folder,post,client=setup
    pipeline.execute(rid);advance(post,folder,'ideas');pipeline.execute(rid)
    w=live.snapshot(folder);p=w['proposals']['script'][0];data=deepcopy(p['data']);data['narrative']['title']='Titre humain'
    response=post('edit',{'stage':'script','proposal_id':p['id'],'data':data,'prompt':'Revoir la chute'})
    assert response.status_code==200
    assert len(live.snapshot(folder)['proposals']['script'])==3
    assert post('choose',{'stage':'script','proposal_id':response.json()['id']}).status_code==200
    pipeline.execute(rid);advance(post,folder,'storyboard');pipeline.execute(rid)
    w=live.snapshot(folder);initial_count=5*core.read(folder/'config.json')['production']['image_attempts'];assert len(w['proposals']['images'])==initial_count
    assert post('generate',{'stage':'images','target':1,'prompt':'An entirely new image'}).status_code==200
    pipeline.execute(rid)
    w=live.snapshot(folder);assert len(w['proposals']['images'])==initial_count+1
    chosen=w['proposals']['images'][-1]
    assert post('choose',{'stage':'images','proposal_id':chosen['id']}).status_code==200
    post('cancel');post('resume');pipeline.execute(rid)
    assert live.snapshot(folder)['image_choices']['1']==chosen['id']
    assert post('validate-images').status_code==200
    pipeline.execute(rid)
    assert core.run_info(rid)['status']=='READY'
    m=core.read(folder/'export/manifest.json')
    assert m['state']['editorial']['script']['title']=='Titre humain'
    assert m['state']['images']['scenes'][0]['prompt']=='An entirely new image'


def test_images_first_visible_plus_preempts_other_plans(setup,monkeypatch):
    rid,folder,post,client=setup
    pipeline.execute(rid);advance(post,folder,'ideas');pipeline.execute(rid);advance(post,folder,'script');pipeline.execute(rid);advance(post,folder,'storyboard')
    started=Event();release=Event();calls=[]
    def generate(ctx,llm,job,w):
        calls.append((job['target'],job['manual']))
        if len(calls)==2:started.set();assert release.wait(8)
        return fake_generator(ctx,llm,job,w)
    monkeypatch.setattr(live_generation,'generate',generate)
    t=Thread(target=pipeline.execute,args=(rid,));t.start()
    try:
        assert started.wait(8)
        assert len(live.snapshot(folder)['proposals']['images'])==1
        assert post('validate-images').status_code==422
        assert post('generate',{'stage':'images','target':1,'prompt':'Close-up'}).status_code==200
        assert post('choose',{'stage':'images','proposal_id':live.snapshot(folder)['proposals']['images'][0]['id']}).status_code==200
    finally:release.set();t.join(10)
    assert calls[:4]==[(1,False),(2,False),(1,True),(3,False)]


def test_failure_preserves_cards_retry_and_research_fallback(setup,monkeypatch):
    rid,folder,post,client=setup
    pipeline.execute(rid)
    original=live.snapshot(folder)['proposals']['ideas']
    def fail(*args):raise RuntimeError('Service indisponible')
    monkeypatch.setattr(live_generation,'generate',fail)
    jid=post('generate',{'stage':'ideas','prompt':'Autre'}).json()['id'];pipeline.execute(rid)
    assert live.snapshot(folder)['proposals']['ideas']==original
    assert any(j.get('error') for j in live.snapshot(folder)['jobs'])
    monkeypatch.setattr(live_generation,'generate',fake_generator)
    assert post('retry-job/'+jid).status_code==200;pipeline.execute(rid)
    assert len(live.snapshot(folder)['proposals']['ideas'])==4
    pid=advance(post,folder,'ideas')
    def reject(*args):raise core.ReviewNeeded('Aucun sujet valide parmi les candidats examines. Preuves insuffisantes')
    monkeypatch.setattr(live_generation,'generate',reject);pipeline.execute(rid)
    w=live.snapshot(folder)
    assert w['stage']=='ideas' and pid in w['rejected'] and len(w['proposals']['ideas'])==4


def test_no_out_of_order_or_auto_controls(setup):
    rid,folder,post,client=setup
    pipeline.execute(rid)
    assert post('generate',{'stage':'images','target':1,'prompt':'Wrong stage'}).status_code==422
    assert post('choose',{'stage':'script','proposal_id':'unknown'}).status_code==422
    assert post('validate-images').status_code==422
    request=core.read(folder/'request.json');request['auto']=True;core.dump(folder/'request.json',request)
    assert post('generate',{'stage':'ideas','prompt':'No manual jobs'}).status_code==409

def test_single_plan_regeneration_preserves_other_plans(setup):
    rid,folder,post,client=setup
    pipeline.execute(rid);advance(post,folder,'ideas');pipeline.execute(rid);advance(post,folder,'script');pipeline.execute(rid)
    w=live.snapshot(folder);p=w['proposals']['storyboard'][0]
    request=post('generate',{'stage':'storyboard','target':2,'base_id':p['id'],'prompt':'Change only this plan'})
    assert request.status_code==200
    job=next(j for j in live.snapshot(folder)['jobs'] if j['id']==request.json()['id'])
    class LLM:
        def ask(self,*a,**kw):return {'visual':'Un plan different','image_prompt':'A different shot'}
    result=original_generate(core.Context(rid),LLM(),job,w)['data']['script']
    original=p['data']['script']
    assert result['scenes'][1]['visual']=='Un plan different'
    assert result['scenes'][1]['narration']==original['scenes'][1]['narration']
    assert result['scenes'][0]==original['scenes'][0] and result['scenes'][2:]==original['scenes'][2:]

def test_missing_media_reopens_images_without_regenerating_chosen_text(setup):
    rid,folder,post,client=setup
    pipeline.execute(rid);advance(post,folder,'ideas');pipeline.execute(rid);advance(post,folder,'script');pipeline.execute(rid);advance(post,folder,'storyboard');pipeline.execute(rid)
    before=live.snapshot(folder);pid=before['image_choices']['1'];image=live.proposal(before,'images',pid)['data']
    assert post('validate-images').status_code==200
    Path(image['path']).unlink();pipeline.execute(rid)
    after=live.snapshot(folder)
    assert after['stage']=='images' and '1' not in after['image_choices']
    assert after['chosen']==before['chosen'] and after['proposals']['script']==before['proposals']['script']

def test_stopped_job_resumes_cached_result_without_repeating_generation(setup,monkeypatch):
    rid,folder,post,client=setup
    count=[]
    def stop(ctx,llm,job,w):
        count.append(job['id']);result=fake_generator(ctx,llm,job,w);core.update(rid,cancel=1);return result
    monkeypatch.setattr(live_generation,'generate',stop);pipeline.execute(rid)
    assert core.run_info(rid)['status']=='CANCELLED'
    first=count[0]
    monkeypatch.setattr(live_generation,'generate',fake_generator)
    assert post('resume').status_code==200;pipeline.execute(rid)
    assert any(p['id']==first for p in live.snapshot(folder)['proposals']['ideas'])
    assert len(live.snapshot(folder)['proposals']['ideas'])==3

def test_completed_render_recovers_ready_after_status_write_interruption(setup):
    rid,folder,post,client=setup
    pipeline.execute(rid);advance(post,folder,'ideas');pipeline.execute(rid);advance(post,folder,'script');pipeline.execute(rid);advance(post,folder,'storyboard');pipeline.execute(rid)
    post('validate-images');pipeline.execute(rid)
    assert core.run_info(rid)['status']=='READY'
    before=live.snapshot(folder)['proposals']
    core.update(rid,status='INTERRUPTED');post('resume');pipeline.execute(rid)
    assert core.run_info(rid)['status']=='READY'
    assert live.snapshot(folder)['proposals']==before
