import argparse,json,subprocess,sys,webbrowser
from .core import ROOT,DATA,config,dump,new_run,runs,update

def main():
    parser=argparse.ArgumentParser(description='AutoShort Local')
    sub=parser.add_subparsers(dest='cmd',required=True)
    sub.add_parser('serve');sub.add_parser('doctor');sub.add_parser('prefetch')
    p=sub.add_parser('worker');p.add_argument('id')
    p=sub.add_parser('run');p.add_argument('--theme',default='Histoires vraies insolites')
    p=sub.add_parser('retry');p.add_argument('id');p.add_argument('--from-stage',choices=['discover','research','editorial','audio','images','render','final'])
    args=parser.parse_args()
    if args.cmd=='serve':
        import uvicorn
        webbrowser.open('http://127.0.0.1:8765')
        uvicorn.run('autoshort.api:app',host='127.0.0.1',port=8765,workers=1)
    elif args.cmd=='doctor':
        from .doctor import diagnose
        result=diagnose(gpu=True);DATA.mkdir(exist_ok=True);dump(DATA/'diagnostic.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(0 if result['ok'] else 1)
    elif args.cmd=='prefetch':
        DATA.mkdir(exist_ok=True);p=DATA/'prefetch.json';dump(p,{'cfg':config(),'voice_test':str(DATA/'voice-test.wav')})
        subprocess.run([sys.executable,'-m','autoshort.media','prefetch',str(p)],check=True,cwd=ROOT)
    elif args.cmd in ('run','worker'):
        from .pipeline import execute
        rid=new_run(args.theme) if args.cmd=='run' else args.id
        print('Production:',rid);execute(rid)
    elif args.cmd=='retry':
        from .core import run_info
        from .pipeline import invalidate
        info=run_info(args.id)
        if info['status'] in ('RUNNING','QUEUED'):raise SystemExit('Production active; arreter avant modification.')
        if args.from_stage:invalidate(DATA/'runs'/args.id,args.from_stage)
        update(args.id,status='QUEUED',cancel=0,error='')
        print('Reprise en file. Demarrer LANCER.cmd. Les budgets ne sont pas remis a zero.')
if __name__=='__main__':main()
