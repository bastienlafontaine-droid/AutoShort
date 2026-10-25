/* Progressive cards and a separate persistent editor: polling never resets typed text. */
const liveStageNames={ideas:'Idées',script:'Script',storyboard:'Découpage',images:'Images',short:'Short'};
const liveJobNames={proposal:'Proposition',research:'Recherche et sources',audio:'Préparation de la voix',render:'Montage du Short'};
const archiveOpen=new Set();
async function livePost(r,path,body={}){
  try{const result=await api(`/api/runs/${r.id}/${path}`,body);renderedStatus='';await refresh();return result;}
  catch(e){notice(e.message);throw e;}
}
function liveButton(parent,text,action,disabled=false){
  const b=el('button',text);b.type='button';b.disabled=disabled;
  b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){notice(e.message);}finally{b.disabled=disabled;}};
  parent.append(b);return b;
}
function liveEditor(r,stage,p=null,target=null,edit=false){
  let dialog=$('proposal-editor');
  if(!dialog){dialog=el('dialog');dialog.id='proposal-editor';document.body.append(dialog);}
  dialog.replaceChildren();
  dialog.append(el('h3',(edit?'Modifier':'Nouvelle proposition')+' · '+liveStageNames[stage]));
  const error=el('p','','bad');error.setAttribute('role','alert');
  const source=structuredClone(p?.data||{}),fields=[];
  if(edit && stage==='ideas')for(const [key,label] of [['title','Titre'],['angle','Angle / résumé'],['query','Recherche de sources']])fields.push([key,field(dialog,label,source[key],2)]);
  if(edit && stage==='script'){
    for(const [key,label] of [['title','Titre'],['description','Description']])fields.push([key,field(dialog,label,source.narrative[key],2)]);
    for(const s of source.narrative.scenes)fields.push([s.id,field(dialog,`Scène ${s.id} · texte dit`,s.narration)]);
  }
  if(edit && stage==='storyboard'){
    for(const s of source.script.scenes.filter(s=>target===null||s.id===target)){dialog.append(el('h4',`Plan ${s.id}`),el('p',s.narration));fields.push([s.id,field(dialog,'Ce qu’on voit',s.visual),field(dialog,'Idée d’image / prompt',s.image_prompt)]);}
  }
  const w=r.progress.live;
  const board=w.proposals.storyboard.find(x=>x.id===w.chosen.storyboard)?.data.script;
  const initialPrompt=(stage==='storyboard'&&target!==null?p?.data.script.scenes.find(s=>s.id===target)?.image_prompt:null)||p?.prompt||(stage==='images'?board?.scenes.find(s=>s.id===target)?.image_prompt:w.prompts?.[stage])||'';
  const prompt=field(dialog,stage==='images'?'Prompt de cette image':'Prompt de génération',initialPrompt,5);
  dialog.append(el('p','La nouvelle version s’ajoute aux précédentes. Le calcul en cours finit ; ta demande passe ensuite en priorité.','muted'),error);
  const actions=el('div',undefined,'actions');dialog.append(actions);
  function editedData(){
    if(stage==='ideas')for(const [k,input] of fields)source[k]=input.value;
    if(stage==='script')for(const [k,input] of fields){if(typeof k==='string')source.narrative[k]=input.value;else source.narrative.scenes.find(s=>s.id===k).narration=input.value;}
    if(stage==='storyboard')for(const [id,visual,imagePrompt] of fields){const s=source.script.scenes.find(s=>s.id===id);s.visual=visual.value;s.image_prompt=imagePrompt.value;}
    return source;
  }
  async function save(){
    const result=await api(`/api/runs/${r.id}/edit`,{stage,proposal_id:p.id,data:editedData(),prompt:prompt.value});return result.id;
  }
  async function act(action){try{await action();dialog.close();renderedStatus='';await refresh();}catch(e){error.textContent=e.message;}}
  if(edit && stage!=='images'){
    liveButton(actions,'Enregistrer une version',()=>act(save));
    liveButton(actions,'Valider cette version',()=>act(async()=>{const id=await save();await api(`/api/runs/${r.id}/choose`,{stage,proposal_id:id});}));
  }
  liveButton(actions,'Générer',()=>act(async()=>{
    const base_id=edit && stage!=='images'?await save():p?.id||null;
    await api(`/api/runs/${r.id}/generate`,{stage,prompt:prompt.value,target,base_id});
  }));
  liveButton(actions,'Fermer',()=>dialog.close());dialog.showModal();
}
function liveCard(parent,r,stage,p,active){
  const w=r.progress.live,card=el('article',undefined,'proposal-card');card.dataset.proposal=p.id;
  const chosen=stage==='images'?w.image_choices[String(p.target)]===p.id:w.chosen[stage]===p.id;
  card.append(el('span',chosen?'✓ Retenue · prête':'Prête','badge'));
  if(p.score!==null && p.score!==undefined)card.append(el('strong',`Note : ${p.score}/100`,'proposal-score'));
  else if(p.edited_from)card.append(el('small','Version modifiée · non renotée','muted'));
  const data=p.data;
  if(stage==='ideas')card.append(el('h4',data.title),el('p',data.angle));
  if(stage==='script'){
    card.append(el('h4',data.narrative.title),el('p',data.narrative.description,'muted'));
    for(const s of data.narrative.scenes)card.append(el('p',`${s.id}. ${s.narration}`));
  }
  if(stage==='storyboard'){
    for(const s of data.script.scenes){const plan=el('section',undefined,'plan');plan.append(el('h4',`Plan ${s.id} · prêt`),el('p',s.narration),el('p',s.visual),el('small',s.image_prompt,'muted'));if(active){const buttons=el('div',undefined,'actions');plan.append(buttons);liveButton(buttons,'Modifier ce plan',()=>liveEditor(r,stage,p,s.id,true));const plus=liveButton(buttons,'+ Ce plan',()=>liveEditor(r,stage,p,s.id));plus.setAttribute('aria-label',`Nouvelle version du plan ${s.id}`);}card.append(plan);}
  }
  if(stage==='images'){
    const img=el('img');img.src=`/api/runs/${r.id}/proposal-image/${p.id}`;img.alt=`Plan ${p.target} · proposition ${p.id.slice(0,6)}`;img.loading='lazy';card.append(img);
    if(data.review?.issues?.length)card.append(el('p',data.review.issues.join(' · '),'muted'));
    if(chosen)card.classList.add('retained');
  }
  if(w.rejected[p.id])card.append(el('p',w.rejected[p.id],'bad'));
  if(active){
    const actions=el('div',undefined,'actions');card.append(actions);
    liveButton(actions,stage==='images'?'Retenir':'Choisir',()=>livePost(r,'choose',{stage,proposal_id:p.id}),Boolean(w.rejected[p.id]));
    liveButton(actions,stage==='images'?'Modifier le prompt':'Modifier',()=>liveEditor(r,stage,p,p.target,true));
    const plus=liveButton(actions,'+',()=>liveEditor(r,stage,p,p.target));plus.setAttribute('aria-label','Nouvelle version de cette proposition');
  }
  parent.append(card);
}
function liveQueue(parent,r,stage,target=undefined){
  const w=r.progress.live;
  const jobs=w.jobs.filter(j=>j.stage===stage&&(target===undefined||j.target===target)&&['queued','running','failed'].includes(j.status));
  const queue=el('div',undefined,'live-queue');queue.setAttribute('aria-live','polite');parent.append(queue);
  for(const j of jobs){
    const line=el('div',undefined,'queue-item');line.dataset.job=j.id;line.dataset.status=j.status;
    const label=j.status==='running'?'En cours':j.status==='failed'?'Erreur':'En attente';
    line.append(el('span',`${label} · ${liveJobNames[j.kind]}${j.target?' · plan '+j.target:''}${j.manual?' · demande prioritaire':''}`));
    if(j.error){line.append(el('p',j.error,'bad'));liveButton(line,'Réessayer',()=>livePost(r,'retry-job/'+j.id));}
    queue.append(line);
  }
}
function showLive(parent,r){
  const w=r.progress.live,stage=w.stage,active=!['CANCELLED','INTERRUPTED','READY'].includes(r.status);
  const area=el('section',undefined,'live-stage');area.dataset.stage=stage;parent.append(area);
  area.append(el('h3',liveStageNames[stage]),el('p','Les propositions apparaissent au fil des calculs. Tu peux choisir dès qu’une version est prête.','muted'));
  if(w.message)area.append(el('p',w.message,'bad'));
  if(stage==='images'){
    const board=w.proposals.storyboard.find(p=>p.id===w.chosen.storyboard)?.data.script;
    for(const plan of board?.scenes||[]){
      const section=el('section',undefined,'image-plan');section.dataset.plan=plan.id;area.append(section);
      const items=w.proposals.images.filter(p=>p.target===plan.id);
      const ongoing=w.jobs.some(j=>j.stage==='images'&&j.target===plan.id&&j.status==='running');
      section.append(el('h4',`Plan ${plan.id} · ${items.length?'prêt':ongoing?'en cours':'en attente'}`),el('p',plan.narration),el('p',plan.visual,'muted'));
      if(active){const b=liveButton(section,'+ Nouvelle image',()=>liveEditor(r,'images',null,plan.id));b.setAttribute('aria-label',`Nouvelle image pour le plan ${plan.id}`);}
      if(active){
        const settings=el('div',undefined,'actions');section.append(settings);
        const movementNames=['push_in','pull_out','pan_left','pan_right','tilt_up','tilt_down','diagonal','still','reveal'];
        for(let i=1;i<=3;i++){
          const shotId='s'+String(plan.id).padStart(2,'0')+'-p'+String(i).padStart(2,'0');
          const opts=w.shot_overrides?.[shotId]||{};
          const selector=el('select');selector.setAttribute('aria-label','Mouvement '+shotId);
          for(const value of movementNames){const option=el('option',value);option.value=value;selector.append(option);}
          selector.value=opts.camera_movement||movementNames[(plan.id+i-2)%movementNames.length];
          const media=el('select');media.setAttribute('aria-label','Média '+shotId);
          for(const value of ['animated_image','generated_video']){const option=el('option',value==='generated_video'?'Vidéo IA locale (si disponible)':'Image animée');option.value=value;media.append(option);}
          media.value=opts.media_type||'animated_image';
          const save=liveButton(settings,'Enregistrer '+i,()=>livePost(r,'shot-settings',{shot_id:shotId,camera_movement:selector.value,media_type:media.value}));
          settings.append(selector,media);
        }
        section.append(el('small','Plans 1 à 3 possibles selon la durée réelle de la voix. Les réglages absents utilisent la réalisation automatique.','muted'));
      }
      const grid=el('div',undefined,'proposal-images');section.append(grid);
      for(const p of items)liveCard(grid,r,'images',p,active);
      liveQueue(section,r,'images',plan.id);
    }
    if(active)liveButton(area,'Valider l’ensemble des images',()=>livePost(r,'validate-images'),!(board?.scenes.every(s=>w.image_choices[String(s.id)])));
  }else{
    if(active&&stage!=='short')liveButton(area,'+ Nouvelle proposition',()=>liveEditor(r,stage));
    const cards=el('div',undefined,'proposal-list');area.append(cards);
    // Ideas retain arrival order while displaying relevance scores; no disappearing/reordering cards.
    for(const p of w.proposals[stage])liveCard(cards,r,stage,p,active);
    liveQueue(area,r,stage);
  }
  // Voice or a requested old-stage version can finish behind the current stage.
  const behind=w.jobs.filter(j=>j.stage!==stage&&['running','failed'].includes(j.status));
  if(behind.length){const aside=el('section',undefined,'background-jobs');aside.append(el('h4','En arrière-plan'));for(const s of new Set(behind.map(j=>j.stage)))liveQueue(aside,r,s);area.append(aside);}
  for(const previous of ['ideas','script','storyboard','images']){
    if(previous===stage||!w.proposals[previous].length)continue;
    const archive=el('details',undefined,'proposal-archive'),key=r.id+previous;
    archive.open=archiveOpen.has(key);archive.ontoggle=()=>{if(archive.open)archiveOpen.add(key);else archiveOpen.delete(key);};
    archive.append(el('summary',`${liveStageNames[previous]} · propositions conservées (${w.proposals[previous].length})`));
    for(const p of w.proposals[previous])liveCard(archive,r,previous,p,false);parent.append(archive);
  }
}
