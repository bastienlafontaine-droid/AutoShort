from pathlib import Path
import pytest
from autoshort import core
from autoshort.pipeline import invalidate,verify_cached
from autoshort.audio import word_error,captions
from autoshort.render import ts,ass_escape
from autoshort.research import evidence_errors,safe_url

def test_checkpoint_does_not_rerun(ctx):
    count=[]
    assert ctx.stage('x',lambda:count.append(1) or {'ok':True})=={'ok':True}
    assert ctx.stage('x',lambda:count.append(2))=={'ok':True}
    assert count==[1]

def test_budget_survives_restart(ctx):
    ctx.cfg['production']['max_search_calls']=1
    core.dump(ctx.path/'config.json',ctx.cfg)
    ctx.spend('search')
    again=core.Context(ctx.rid)
    with pytest.raises(core.ReviewNeeded):again.spend('search')

def test_cancel(ctx):
    core.update(ctx.rid,cancel=1)
    with pytest.raises(core.Cancelled):ctx.check()

def test_invalidation_preserves_upstream(ctx):
    for stage in ['discover','research','editorial','audio','images','render','final']:core.dump(ctx.path/f'{stage}.json',{})
    invalidate(ctx.path,'images')
    assert (ctx.path/'audio.json').exists()
    assert not (ctx.path/'final.json').exists()

def test_altered_asset_invalidates_dependents(ctx):
    p=ctx.path/'audio.wav';p.write_bytes(b'old')
    core.dump(ctx.path/'audio.json',{'scenes':[{'path':str(p),'sha256':core.digest(p)}]})
    core.dump(ctx.path/'final.json',{})
    p.write_bytes(b'changed')
    verify_cached(ctx)
    assert not (ctx.path/'audio.json').exists()
    assert not (ctx.path/'final.json').exists()

def test_evidence_requires_real_quote():
    d={'claims':[{'id':'C1','evidence':[{'source_id':'S1','quote':'un fait invente'}]}]}
    assert evidence_errors(d,[{'id':'S1','text':'Le document ne dit rien de tel.'}])
    d['claims'][0]['evidence'][0]['quote']='Le document'
    assert not evidence_errors(d,[{'id':'S1','text':'Le document ne dit rien de tel.'}])

@pytest.mark.parametrize('url',['file:///etc/passwd','http://127.0.0.1','http://169.254.169.254/latest','http://[::1]/','http://user:pass@example.com','https://example.com:8000'])
def test_private_urls_rejected(url):
    with pytest.raises(ValueError):safe_url(url)

def test_word_error_normalizes_numbers():
    assert word_error('En 1912, tout change.','En mille neuf cent douze tout change')==0
    assert word_error('Cette histoire est vraie','Le chat dort')>.5

def test_caption_intervals_monotonic():
    caps,coverage=captions('un deux trois quatre cinq six sept huit neuf dix onze',[],7)
    assert coverage==0
    assert all(0<=x['start']<x['end']<=7 for x in caps)
    assert all(a['end']<=b['start'] for a,b in zip(caps,caps[1:]))

def test_timestamp_carry_and_subtitle_injection():
    assert ts(59.9999)=='00:01:00,000'
    assert ts(59.9999,True)=='0:01:00.00'
    assert '{' not in ass_escape(r'{\pos(0,0)}hello')
