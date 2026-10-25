import shutil
import numpy as np
import soundfile as sf
import pytest
from PIL import Image,ImageDraw
from autoshort.render import render,final_check

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg non installe')
def test_actual_ffmpeg_render_and_quality_checks(ctx):
    ctx.cfg['production'].update(width=180,height=320,fps=10,min_seconds=1,max_seconds=10)
    scenes=[];audio=[];images=[]
    for i in range(1,3):
        img=ctx.path/f'{i}.png';image=Image.new('RGB',(180,320),(40*i,80,110));ImageDraw.Draw(image).ellipse((30,70,150,200),fill=(220,180,90));image.save(img)
        wav=ctx.path/f'{i}.wav';rate=24000;t=np.arange(rate*2)/rate
        sf.write(wav,0.12*np.sin(2*np.pi*330*t),rate)
        scenes.append({'id':i,'narration':'Ceci est un test technique.'})
        audio.append({'duration':2,'path':str(wav),'asr':{'words':[]}})
        images.append({'path':str(img)})
    result=render(ctx,{'title':'Test','description':'Test technique','scenes':scenes},{'scenes':audio},{'scenes':images})
    report=final_check(ctx,result)
    assert report['accepted']
    assert (ctx.path/'export'/'video.mp4').stat().st_size>1000
    assert (ctx.path/'export'/'subtitles.srt').exists()
