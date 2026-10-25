import json, math, os, shutil, subprocess, time
from pathlib import Path
from .core import ROOT, dump, digest, ReviewNeeded
from .audio import captions

def command(ctx,args,cwd=None):
    ctx.check()
    with (ctx.path/'render.log').open('a',encoding='utf-8') as f:
        proc=subprocess.Popen(args,cwd=cwd or ctx.path,stdout=f,stderr=f)
        try:
            while proc.poll() is None:ctx.check();time.sleep(.3)
            if proc.returncode:raise RuntimeError('FFmpeg a echoue. Consulter render.log.')
        except BaseException:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            raise

def probe(path):
    r=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,text=True,check=True,timeout=30)
    return json.loads(r.stdout)

def ts(sec,ass=False):
    # Arrondi avant decomposition pour eviter 00:00:60,000.
    unit=100 if ass else 1000;n=max(0,round(sec*unit));h,n=divmod(n,3600*unit);m,n=divmod(n,60*unit);s,sub=divmod(n,unit)
    return f'{h}:{m:02}:{s:02}.{sub:02}' if ass else f'{h:02}:{m:02}:{s:02},{sub:03}'

def ass_escape(text):return text.replace('\\','/').replace('{','(').replace('}',')').replace('\n',' ')

def write_subtitles(folder,items,width,height):
    srt='\n\n'.join(f"{i+1}\n{ts(x['start'])} --> {ts(x['end'])}\n{x['text']}" for i,x in enumerate(items))+'\n'
    (folder/'subtitles.srt').write_text(srt,encoding='utf-8')
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{round(height*.039)},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,{round(width*.10)},{round(width*.16)},{round(height*.20)},1
Style: Label,Arial,{round(height*.016)},&H00EEEEEE,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,1,0,8,50,50,{round(height*.06)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    body='\n'.join(f"Dialogue: 0,{ts(x['start'],True)},{ts(x['end'],True)},Default,,0,0,0,,{ass_escape(x['text'])}" for x in items)
    duration=max((x['end'] for x in items),default=1)
    body+=f'\nDialogue: 0,0:00:00.00,{ts(duration,True)},Label,,0,0,0,,Reconstitution illustree par IA\n'
    (folder/'subtitles.ass').write_text(header+body,encoding='utf-8')

def render(ctx,script,audio,images):
    cfg=ctx.cfg['production'];w,h,fps=cfg['width'],cfg['height'],cfg['fps']
    folder=ctx.path/'export';folder.mkdir(exist_ok=True)
    items=[];timeline=[];offset=0.0
    for s,a,img in zip(script['scenes'],audio['scenes'],images['scenes']):
        n=s['id'];duration=math.ceil(a['duration']*fps)/fps
        caps,coverage=captions(s['narration'],a['asr']['words'],a['duration'],offset)
        items+=caps;timeline.append({'scene':n,'start':offset,'duration':duration,'subtitle_exact_match_coverage':coverage})
        # Changements de cadrage lisibles, sans regenerer l'image.
        if cfg.get('story_pipeline',1)>=2:
            cycle=max(1,round(cfg.get('shot_seconds',3.3)*fps))
            zoom=f"if(lt(mod(on,{cycle*2}),{cycle}),1.02+mod(on,{cycle})*0.0005,1.16-mod(on,{cycle})*0.0005)"
            vf=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps},format=yuv420p"
            timeline[-1]['reframes']=[round(offset+t/fps,3) for t in range(0,round(duration*fps),cycle)]
        else:
            vf=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,zoompan=z='min(1+on*0.00008,1.04)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps},format=yuv420p"
        command(ctx,['ffmpeg','-hide_banner','-y','-loop','1','-framerate',str(fps),'-i',img['path'],'-i',a['path'],
          '-vf',vf,'-af','apad','-t',str(duration),'-c:v','libx264','-preset','fast','-crf','20','-c:a','aac','-ar','48000','-ac','2',str(folder/f'scene_{n:02d}.mp4')])
        offset+=duration
    write_subtitles(folder,items,w,h)
    (folder/'concat.txt').write_text(''.join(f"file 'scene_{s['id']:02d}.mp4'\n" for s in script['scenes']),encoding='utf-8')
    command(ctx,['ffmpeg','-hide_banner','-y','-f','concat','-safe','1','-i','concat.txt','-c','copy','assembled.mp4'],cwd=folder)
    filters='subtitles=subtitles.ass'
    if cfg.get('progress_bar'):
        # Overlay d'une barre croppee selon t; mouvement deterministe, pas d'IA.
        visual=f"[0:v]{filters}[v];color=c=0x58d6ba:s={w}x8:r={fps}:d={offset}[bar];[v][bar]overlay=x='-w+w*t/{offset}':y={round(h*.12)}:shortest=1[outv]"
    else:visual=f'[0:v]{filters}[outv]'
    args=['ffmpeg','-hide_banner','-y','-i','assembled.mp4']
    music=cfg.get('music','')
    if music:
        path=(ROOT/music).resolve()
        if not path.is_file():raise ReviewNeeded('Fichier musique configure introuvable')
        args+=['-stream_loop','-1','-i',str(path)]
        visual+=';[1:a]volume=0.06[bg];[0:a][bg]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[outa]'
    else:visual+=';[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[outa]'
    args+=['-filter_complex',visual,'-map','[outv]','-map','[outa]','-t',str(offset),'-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-movflags','+faststart','video.tmp.mp4']
    command(ctx,args,cwd=folder)
    os.replace(folder/'video.tmp.mp4',folder/'video.mp4')
    command(ctx,['ffmpeg','-hide_banner','-y','-ss','1','-i','video.mp4','-frames:v','1','cover.jpg'],cwd=folder)
    dump(folder/'timeline.json',timeline)
    (folder/'script.md').write_text('# '+script['title']+'\n\n'+'\n\n'.join(s['narration'] for s in script['scenes']),encoding='utf-8')
    (folder/'description.txt').write_text(script['description'],encoding='utf-8')
    return {'path':str(folder/'video.mp4'),'sha256':digest(folder/'video.mp4'),'duration':offset,'timeline':timeline}

def final_check(ctx,rendered):
    p=Path(rendered['path']); data=probe(p);cfg=ctx.cfg['production']
    video=[s for s in data['streams'] if s['codec_type']=='video'];audio=[s for s in data['streams'] if s['codec_type']=='audio']
    errors=[]
    if not video or not audio:errors.append('Piste audio ou video manquante')
    if video and (video[0]['width']!=cfg['width'] or video[0]['height']!=cfg['height']):errors.append('Dimensions incorrectes')
    duration=float(data['format']['duration'])
    if abs(duration-rendered['duration'])>0.6:errors.append('Duree export incoherente')
    if not cfg['min_seconds']<=duration<=cfg['max_seconds']+1:errors.append('Duree finale hors cible')
    command(ctx,['ffmpeg','-v','error','-i',str(p),'-f','null','-'])
    scan=ctx.path/'export'/'scan.log'
    with scan.open('w',encoding='utf-8') as f:
        proc=subprocess.run(['ffmpeg','-hide_banner','-i',str(p),'-vf','blackdetect=d=0.5:pix_th=0.05','-af','silencedetect=noise=-45dB:d=2','-f','null','-'],stdout=f,stderr=f,timeout=300)
    if proc.returncode:errors.append('Analyse finale interrompue')
    log=scan.read_text(encoding='utf-8',errors='replace')
    if 'black_start:' in log:errors.append('Passage noir detecte >0.5s')
    if 'silence_start:' in log:errors.append('Silence detecte >2s')
    if digest(p)!=rendered['sha256']:errors.append('Fichier final modifie')
    report={'accepted':not errors,'errors':errors,'duration':duration,'technical':data,
            'limitations':['Le controle factuel automatique ne certifie pas la verite.',
                          'La prosodie et la coherence historique doivent etre calibrees par ecoute/visionnage.',
                          'Sous-titres: alignement ASR avec interpolation locale si correspondance manquante.']}
    dump(ctx.path/'export'/'technical_report.json',report)
    if errors:raise ReviewNeeded('; '.join(errors))
    return report
