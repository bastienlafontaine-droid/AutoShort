// DOM regression only (no browser/layout). Optional: npm install jsdom.
const {JSDOM}=require('jsdom'),fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
  const root=path.join(__dirname,'..','autoshort','static');
  const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'http://127.0.0.1:8765',runScripts:'outside-only'}),win=dom.window;
  win.structuredClone=structuredClone;win.setInterval=()=>0;
  win.HTMLDialogElement.prototype.showModal=function(){this.open=true;};win.HTMLDialogElement.prototype.close=function(){this.open=false;};
  const w={stage:'ideas',revision:1,prompts:{ideas:'Prompt initial des idees',script:'Prompt script',storyboard:'Prompt decoupage'},proposals:{ideas:[{id:'i1',data:{title:'Idee un',angle:'Angle un',query:'source'},prompt:'Prompt initial des idees',score:80}],script:[],storyboard:[],images:[],short:[]},jobs:[{id:'j2',stage:'ideas',kind:'proposal',status:'running',manual:false}],chosen:{},image_choices:{},rejected:{}};
  const r={id:'aaaaaaaaaaaaaaaa',status:'RUNNING',theme:'Theme test',step:'ideas',files:[],events:[],progress:{auto:false,number:1,live:w}};
  const calls=[];
  win.fetch=async(url,opts)=>{
    const body=opts?.body?JSON.parse(opts.body):null;calls.push({url,body});let result;
    if(url==='/api/session')result={token:'fixture'};
    else if(url==='/api/health')result={ok:true,checks:[]};
    else if(url==='/api/runs')result=[r];
    else if(url===`/api/runs/${r.id}`)result=r;
    else if(url.endsWith('/generate')){result={id:'manual'};w.revision++;w.jobs.push({id:'manual',stage:body.stage,kind:'proposal',status:'queued',manual:true,target:body.target});}
    else if(url.endsWith('/edit')){result={id:'edited'};w.proposals[body.stage].push({id:'edited',data:body.data,prompt:body.prompt,score:null});w.revision++;}
    else if(url.endsWith('/choose')){result={ok:true};w.chosen[body.stage]=body.proposal_id;w.stage='storyboard';w.revision++;}
    else throw Error('Unexpected request '+url);
    return {ok:true,json:async()=>structuredClone(result)};
  };
  win.eval(fs.readFileSync(path.join(root,'live.js'),'utf8')+'\n'+fs.readFileSync(path.join(root,'app.js'),'utf8'));
  const flush=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
  const q=s=>win.document.querySelector(s),all=s=>[...win.document.querySelectorAll(s)];
  const button=(container,text)=>[...container.querySelectorAll('button')].find(b=>b.textContent===text);
  await flush();if(!q('.run'))throw Error(q('#notice').textContent+' '+JSON.stringify(calls));q('.run').click();await flush();
  assert.equal(all('.live-stage .proposal-card').length,1);assert.ok(q('[data-status=running]'));
  button(q('.live-stage'),'+ Nouvelle proposition').click();await flush();
  let editor=q('#proposal-editor');if(!editor)throw Error(q('#notice').textContent);assert.equal(editor.querySelector('textarea').value,'Prompt initial des idees');
  editor.querySelector('textarea').value='Mon prompt personnel';w.revision++;await win.eval('refreshDetail()');
  assert.equal(editor.querySelector('textarea').value,'Mon prompt personnel');
  button(editor,'Générer').click();await flush();
  assert.equal(calls.findLast(c=>c.url.endsWith('/generate')).body.prompt,'Mon prompt personnel');
  assert.equal(all('.live-stage .proposal-card').length,1);assert.ok(q('[data-status=queued]'));
  w.proposals.ideas.push({...w.proposals.ideas[0],id:'i2'});w.revision++;await win.eval('refreshDetail()');
  assert.equal(all('.live-stage .proposal-card').length,2);
  w.stage='script';r.progress.number=2;w.revision++;
  const narrative={title:'Titre initial',description:'Description',scenes:[1,2,3,4,5].map(id=>({id,narration:'Texte '+id,claim_ids:['C1']}))};
  w.proposals.script=[{id:'s1',data:{narrative},prompt:'Prompt du script',score:80}];
  await win.eval('refreshDetail()');button(q('.live-stage'),'Modifier').click();await flush();
  editor=q('#proposal-editor');editor.querySelector('textarea').value='Titre modifie';
  button(editor,'Valider cette version').click();await flush();
  assert.equal(w.proposals.script.length,2);assert.equal(w.proposals.script[1].data.narrative.title,'Titre modifie');
  assert.equal(w.chosen.script,'edited');assert.equal(w.proposals.script[0].data.narrative.title,'Titre initial');
  const board={title:'Titre',description:'Desc',visual_bible:'Style',scenes:narrative.scenes.map(s=>({...s,visual:'Visuel '+s.id,image_prompt:'Image prompt '+s.id}))};
  w.proposals.storyboard=[{id:'b1',data:{script:board},prompt:'Prompt decoupage'}];w.revision++;await win.eval('refreshDetail()');
  assert.equal(all('.live-stage button[aria-label^="Nouvelle version du plan"]').length,5);
  w.chosen.storyboard='b1';w.stage='images';r.progress.number=4;w.revision++;
  w.proposals.images=[{id:'im1',data:{path:'fixture.png'},target:1,prompt:'Image prompt 1',score:80}];w.image_choices={'1':'im1'};
  await win.eval('refreshDetail()');assert.equal(all('.image-plan').length,5);
  assert.equal(button(q('.live-stage'),'Valider l’ensemble des images').disabled,true);
  q('button[aria-label="Nouvelle image pour le plan 2"]').click();await flush();
  editor=q('#proposal-editor');assert.equal(editor.querySelector('textarea').value,'Image prompt 2');
  editor.querySelector('textarea').value='New plan two';button(editor,'Générer').click();await flush();
  const imageRequest=calls.findLast(c=>c.url.endsWith('/generate'));assert.equal(imageRequest.body.target,2);assert.equal(imageRequest.body.prompt,'New plan two');
  r.progress={auto:true,number:3};r.status='RUNNING';await win.eval('refreshDetail()');assert.equal(all('.live-stage,.approval').length,0);
  dom.window.close();console.log('PASS DOM: incremental cards, prompt prefilling/editing, polling-safe dialog, version preservation, edited selection, per-plan +, disabled incomplete image validation, no manual controls in Auto.');
})().catch(e=>{console.error(e);process.exit(1)});
