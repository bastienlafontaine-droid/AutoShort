"""Sous-processus jetables : toute memoire modele est liberee a la sortie."""
import json, os, sys
from pathlib import Path
from .core import dump, read

def images(request):
    import torch
    from diffusers import StableDiffusionXLPipeline
    if not torch.cuda.is_available(): raise RuntimeError('CUDA indisponible. Verifier pilote NVIDIA et PyTorch cu128.')
    free,total=torch.cuda.mem_get_info()
    if free<9*1024**3: raise RuntimeError('Moins de 9 Go VRAM libres. Fermer autres applications IA puis reprendre.')
    print('Images: chargement du modele SDXL',flush=True)
    cfg=request['cfg']; pipe=StableDiffusionXLPipeline.from_pretrained(cfg['models']['image'],torch_dtype=torch.float16,
                         use_safetensors=True,variant='fp16')
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing(); pipe.enable_vae_tiling()
    for index,job in enumerate(request['jobs'],1):
        print(f'Image {index}/{len(request["jobs"])}: generation',flush=True)
        out=Path(job['output']); out.parent.mkdir(parents=True,exist_ok=True)
        def clipped(tokenizer,text):
            ids=tokenizer(text,truncation=True,max_length=77)['input_ids']
            return tokenizer.decode(ids,skip_special_tokens=True)
        prompt=clipped(pipe.tokenizer,job['prompt'])
        style=clipped(pipe.tokenizer_2,job['prompt']+'. '+job.get('style',''))
        result=pipe(prompt=prompt,prompt_2=style,negative_prompt='text, letters, watermark, logo, collage, split screen, modern objects, deformed hands, extra limbs, blurry',
                    height=cfg['production']['image_height'],width=cfg['production']['image_width'],
                    num_inference_steps=cfg['production']['image_steps'],guidance_scale=6.0,
                    generator=torch.Generator(device='cpu').manual_seed(job['seed']))
        temp=out.with_suffix('.tmp.png'); result.images[0].save(temp); os.replace(temp,out)
        print(f'Image sauvegardee: {out.name}',flush=True)
        dump(Path(str(out)+'.generation.json'),{'prompt':prompt,'prompt_2':style,'model':cfg['models']['image'],'seed':job['seed'],'steps':cfg['production']['image_steps']})

def tts(request):
    import numpy as np, soundfile as sf
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    if not hasattr(EspeakWrapper,'set_data_path'):
        raise RuntimeError('Installer phonemizer-fork via INSTALLER.cmd (conflit phonemizer).')
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    from kokoro import KPipeline
    pipe=KPipeline(lang_code='f',repo_id='hexgrad/Kokoro-82M',device='cpu')
    for job in request['jobs']:
        arrays=[]
        for _,_,audio in pipe(job['text'],voice=request['cfg']['models']['voice'],speed=job.get('speed',1.0),split_pattern=r'\n+'):
            if hasattr(audio,'detach'): audio=audio.detach().cpu().numpy()
            arrays.append(np.asarray(audio,dtype=np.float32))
        if not arrays: raise RuntimeError('Aucun audio produit')
        out=Path(job['output']); out.parent.mkdir(parents=True,exist_ok=True)
        tmp=out.with_suffix('.tmp.wav'); sf.write(tmp,np.concatenate(arrays),24000,subtype='PCM_16'); os.replace(tmp,out)

def transcribe(request):
    from faster_whisper import WhisperModel
    # CPU int8 evite de dependre des DLL CUDA/cuDNN de CTranslate2 sous Windows.
    model=WhisperModel(request['cfg']['models']['asr'],device='cpu',compute_type='int8',cpu_threads=4)
    for job in request['jobs']:
        segments,info=model.transcribe(job['input'],language='fr',word_timestamps=True,beam_size=5,vad_filter=True,
                                      condition_on_previous_text=False)
        words=[]; texts=[]
        for s in segments:
            texts.append(s.text)
            for w in s.words or []: words.append({'word':w.word.strip(),'start':w.start,'end':w.end,'probability':w.probability})
        dump(Path(job['output']),{'text':' '.join(texts),'words':words,'language':info.language})

def prefetch(request):
    from huggingface_hub import snapshot_download
    cfg=request['cfg']
    snapshot_download(cfg['models']['image'],allow_patterns=['model_index.json','scheduler/*','tokenizer/*','tokenizer_2/*',
      'text_encoder/config.json','text_encoder_2/config.json','unet/config.json','vae/config.json','*.fp16.safetensors'])
    # TTS initialise aussi les dependances linguistiques.
    tts({'cfg':cfg,'jobs':[{'text':'Bonjour. Le test de voix française est terminé.','output':request['voice_test']}]})
    transcribe({'cfg':cfg,'jobs':[{'input':request['voice_test'],'output':request['voice_test']+'.json'}]})

if __name__=='__main__':
    action=sys.argv[1]; request=read(sys.argv[2])
    {'images':images,'tts':tts,'transcribe':transcribe,'prefetch':prefetch}[action](request)
