from pathlib import Path
import pytest
from PIL import Image
from autoshort import assets,core

class Judge:
    def __init__(self,scores):self.scores=iter(scores);self.calls=0
    def unload(self):pass
    def ask(self,*args,**kwargs):
        self.calls+=1
        score=next(self.scores)
        return {'score':score,'accepted':score>=80,'issues':['visible defect'] if score<80 else [],'correction':'A clear single scene'}

@pytest.fixture
def setup_images(ctx,monkeypatch):
    ctx.cfg['production'].update(story_pipeline=3,image_attempts=3,min_visual_score=8)
    generated=[]
    def child(c,action,payload):
        generated.extend(payload['jobs'])
        core.dump(c.path/'requests'/f'images_{len(generated)}.json',{'cfg':c.cfg,**payload})
        for job in payload['jobs']:
            Image.new('RGB',(16,16),(job['seed']%255,40,70)).save(job['output'])
            core.dump(Path(job['output']+'.generation.json'),{'seed':job['seed'],'model':c.cfg['models']['image']})
    monkeypatch.setattr(assets,'child',child)
    script={'visual_bible':'illustration','scenes':[{'id':i,'narration':'A village in winter','visual':'winter','image_prompt':'Snowy village'} for i in (1,2)]}
    return ctx,script,generated


def test_best_per_scene_selected_not_last_and_resume_is_stable(setup_images):
    ctx,script,generated=setup_images
    # Scene 1 wins on first attempt; scene 2 on second. Every image remains below threshold.
    judge=Judge([70,60,20,30,40,40,65,66,30,30,40,40])
    result=assets.image_assets(ctx,judge,script)
    assert [s['attempt'] for s in result['scenes']]==[1,2]
    assert [s['score_100'] for s in result['scenes']]==[65,65.5]
    assert result['with_reservations']
    assert all(not s['review']['accepted'] for s in result['scenes'])
    assert all(s['selection_reason']=='best_available_after_attempts' for s in result['scenes'])
    assert len(core.read(ctx.path/'images/selection.json')['candidates'])==6
    retry=Judge([])
    assert assets.image_assets(ctx,retry,script)==result
    assert retry.calls==0
    assert len(generated)==6


def test_low_scores_are_not_multiplied_and_good_scene_stops_early(setup_images):
    ctx,script,generated=setup_images
    judge=Judge([90,90,5,10,8,8,6,6])
    result=assets.image_assets(ctx,judge,script)
    assert [s['score_100'] for s in result['scenes']]==[90,8]
    assert [s['attempt'] for s in result['scenes']]==[1,2]
    assert len(generated)==4
    assert result['scenes'][0]['selection_reason']=='threshold_met'
    assert result['scenes'][1]['quality_review']['score']==8


def test_changed_image_is_reevaluated(setup_images):
    ctx,script,generated=setup_images
    ctx.cfg['production']['image_attempts']=1
    result=assets.image_assets(ctx,Judge([90,90,90,90]),script)
    Image.new('RGB',(16,16),'red').save(result['scenes'][0]['path'])
    judge=Judge([30,30])
    result=assets.image_assets(ctx,judge,script)
    assert judge.calls==2
    assert result['scenes'][0]['score_100']==30


def test_final_visual_reservations_do_not_block_export(ctx,monkeypatch):
    from autoshort import pipeline
    folder=ctx.path/'export';folder.mkdir()
    def command(c,args):Image.new('RGB',(270,480),'blue').save(args[-1])
    monkeypatch.setattr(pipeline,'command',command)
    monkeypatch.setattr(pipeline,'final_check',lambda *a:{'accepted':True})
    result=pipeline.final(ctx,Judge([3]),{'render':{'timeline':[{'scene':1,'start':0,'duration':2}]},
        'editorial':{'script':{'title':'Test'}},'images':{'scoring':'mean_quality_relevance_100'}})
    assert result['with_reservations']
    assert result['visual']['accepted'] is False
    assert result['technical']['accepted']
