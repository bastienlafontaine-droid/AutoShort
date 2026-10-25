import copy
import pytest
from autoshort import editorial,core

def draft(words=10):
    return {'title':'Titre','description':'Reconstitution illustree',
      'scenes':[{'id':i,'narration':' '.join(['mot']*words),'claim_ids':['C1']} for i in range(1,8)]}

def sources():return {'dossier':{'title':'Titre','claims':[{'id':'C1','text':'Fait documente','evidence':[]}]},'sources':[]}

def board():return {'visual_bible':'English illustration style','scenes':[{'id':i,'visual':'Un objet','image_prompt':'An object'} for i in range(1,8)]}

class LLM:
    def __init__(self,answers):self.answers=iter(answers);self.calls=[]
    def ask(self,role,instruction,data,schema,**kwargs):
        self.calls.append((role,copy.deepcopy(data)))
        return schema.model_validate(next(self.answers)).model_dump()

def test_revision_receives_previous_text_and_word_deficit(ctx):
    llm=LLM([draft(10),draft(23),{'accepted':True,'score':8,'issues':[],'correction':''},board()])
    result=editorial.write_script(ctx,llm,sources())
    assert editorial.word_count(result['script'])==161
    assert llm.calls[1][1]['previous_draft']==draft(10)
    assert llm.calls[1][1]['length']['words_to_add_to_target']==90
    assert [r for r,d in llm.calls]==['writer','writer','script_judge','storyboard']
    assert result['script']['scenes'][0]['narration']==draft(23)['scenes'][0]['narration']

def test_rejection_contains_actual_reason_and_diagnostics(ctx):
    llm=LLM([draft(10),draft(11),draft(12)])
    with pytest.raises(core.ReviewNeeded,match='84 mots'):
        editorial.write_script(ctx,llm,sources())
    report=core.read(ctx.path/'editorial'/'last_validation.json')
    assert report['words']==84
    assert 'minimum 135' in report['errors'][0]
    assert all(role=='writer' for role,data in llm.calls)

def test_reuses_v01_best_draft_without_overwrite(ctx):
    a=draft(10);b=draft(17)
    for value in (a,b):
        value['visual_bible']='style'
        for s in value['scenes']:s.update(visual='objet',image_prompt='object')
    core.dump(ctx.path/'editorial'/'script_0.json',a)
    core.dump(ctx.path/'editorial'/'script_1.json',b)
    before=(ctx.path/'editorial'/'script_1.json').read_bytes()
    llm=LLM([draft(23),{'accepted':True,'score':8,'issues':[],'correction':''},board()])
    editorial.write_script(ctx,llm,sources())
    assert editorial.word_count(llm.calls[0][1]['previous_draft'])==119
    assert (ctx.path/'editorial'/'script_1.json').read_bytes()==before

def test_storyboard_cannot_overwrite_validated_narration(ctx):
    wrong=board();wrong['scenes'][0]['id']=8
    llm=LLM([draft(23),{'accepted':True,'score':8,'issues':[],'correction':''},wrong,board()])
    result=editorial.write_script(ctx,llm,sources())
    assert llm.calls[-1][1]['feedback']
    assert result['script']['scenes'][0]['narration']==draft(23)['scenes'][0]['narration']

def test_short_script_is_not_accepted_by_lowering_threshold(ctx):
    ctx.cfg['production']['script_attempts']=1
    llm=LLM([draft(19)]) # 133 mots
    with pytest.raises(core.ReviewNeeded,match='133 mots'):editorial.write_script(ctx,llm,sources())

def test_fact_rejection_is_sent_to_writer(ctx):
    bad={'accepted':False,'score':9,'issues':['Date non soutenue'],'correction':'Retirer la date'}
    llm=LLM([draft(23),bad,draft(24),{'accepted':True,'score':8,'issues':[],'correction':''},board()])
    result=editorial.write_script(ctx,llm,sources())
    assert 'Date non soutenue' in llm.calls[2][1]['feedback']
    assert editorial.word_count(result['script'])==168
