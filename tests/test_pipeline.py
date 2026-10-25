from autoshort import core,pipeline

def test_graph_end_to_end_orchestration_with_fake_services(ctx,monkeypatch):
    monkeypatch.setattr(pipeline,'DATA',core.DATA)
    calls=[]
    def f(name,value):
        def invoke(*args):calls.append(name);return value
        return invoke
    class FakeLLM:
        def __init__(self,c):pass
        def unload(self):pass
    monkeypatch.setattr(pipeline,'LLM',FakeLLM)
    monkeypatch.setattr(pipeline,'discover',f('discover',{'candidates':[]}))
    monkeypatch.setattr(pipeline,'research',f('research',{'dossier':{'title':'Test','claims':[]},'sources':[]}))
    monkeypatch.setattr(pipeline,'write_script',f('editorial',{'script':{'title':'Test','scenes':[]}}))
    monkeypatch.setattr(pipeline,'audio_assets',f('audio',{'scenes':[]}))
    monkeypatch.setattr(pipeline,'image_assets',f('images',{'scenes':[]}))
    monkeypatch.setattr(pipeline,'render',f('render',{'duration':1}))
    monkeypatch.setattr(pipeline,'final',f('final',{'accepted':True}))
    pipeline.execute(ctx.rid)
    assert core.run_info(ctx.rid)['status']=='READY'
    assert calls==pipeline.STAGES
    assert (ctx.path/'export'/'manifest.json').exists()

def test_graph_failed_judge_never_becomes_ready(ctx,monkeypatch):
    monkeypatch.setattr(pipeline,'DATA',core.DATA)
    class FakeLLM:
        def __init__(self,c):pass
        def unload(self):pass
    monkeypatch.setattr(pipeline,'LLM',FakeLLM)
    monkeypatch.setattr(pipeline,'discover',lambda *a:{'candidates':[]})
    def reject(*a):raise core.ReviewNeeded('Pas assez de preuves')
    monkeypatch.setattr(pipeline,'research',reject)
    pipeline.execute(ctx.rid)
    assert core.run_info(ctx.rid)['status']=='NEEDS_REVIEW'
    assert not (ctx.path/'export'/'video.mp4').exists()
