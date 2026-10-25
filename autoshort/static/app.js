let token='',selected=null,renderedStatus='',busy=false;
const $=id=>document.getElementById(id);
const labels={AWAITING_APPROVAL:'À valider',QUEUED:'En attente',RUNNING:'En cours',READY:'Prête à visionner',NEEDS_REVIEW:'À revoir',FAILED:'Erreur',CANCELLED:'Arrêtée',INTERRUPTED:'Interrompue'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-AutoShort-Token':token},body:JSON.stringify(body)});if(!r.ok){let data=await r.json();throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));}return r.json();}
function notice(text){$('notice').textContent=text;}
async function health(){const data=await api('/api/health');$('checks').replaceChildren();for(const c of data.checks)$('checks').append(el('div',(c.ok?'✓ ':'✕ ')+c.name+' — '+c.detail,'check '+(c.ok?'':'bad')));if(!data.ok)$('settings').open=true;}
async function refresh(){if(busy)return;busy=true;try{const list=await api('/api/runs');$('runs').replaceChildren();for(const r of list){const box=el('div',undefined,'run '+(r.id===selected?'active':''));box.append(el('span',labels[r.status]||r.status,'badge'),el('strong',r.theme),el('small',r.step,'muted'));box.onclick=()=>{selected=r.id;renderedStatus='';refreshDetail();};$('runs').append(box);}if(!list.length)$('runs').append(el('p','Aucune production. Lance ta première histoire.','muted'));if(selected)await refreshDetail();}catch(e){notice(e.message);}finally{busy=false;}}
async function refreshDetail(){const r=await api('/api/runs/'+selected);const signature=r.id+r.status+r.progress.number+(r.progress.pending?.input_hash||'')+(r.progress.live?.revision||0)+r.files.join(',');if(signature!==renderedStatus){renderedStatus=signature;const d=$('detail');d.replaceChildren(el('span',labels[r.status]||r.status,'badge'),el('h3',r.theme));showProgress(d,r);if(r.error)d.append(el('p',r.error,'bad'));if(r.files.includes('video.mp4')){if(r.status!=='READY')d.append(el('p','Brouillon non validé — consulter les contrôles.','bad'));const v=el('video');v.controls=true;v.preload='metadata';v.src='/api/runs/'+r.id+'/files/video.mp4';d.append(v);}const actions=el('div',undefined,'actions');if(['QUEUED','RUNNING','AWAITING_APPROVAL'].includes(r.status)){const b=el('button','Arrêter');b.onclick=async()=>{await api('/api/runs/'+r.id+'/cancel',{});await refresh();};actions.append(b);}if(['FAILED','INTERRUPTED','CANCELLED','NEEDS_REVIEW'].includes(r.status)){const b=el('button','Reprendre');b.onclick=async()=>{await api('/api/runs/'+r.id+'/resume',{});await refresh();};actions.append(b);}for(const f of r.files){const a=el('a',f);a.href='/api/runs/'+r.id+'/files/'+encodeURIComponent(f);a.target='_blank';a.rel='noopener';actions.append(a);}const log=el('a','Journaux');log.href='/api/runs/'+r.id+'/logs';log.target='_blank';actions.append(log);d.append(actions,el('h4','Journal technique'));const e=el('div',undefined,'events');e.id='events';d.append(e);}const events=$('events');events.replaceChildren(...r.events.map(x=>el('p',new Date(x.time*1000).toLocaleTimeString()+' · '+x.stage+' · '+x.message)));}
$('create').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{const r=await api('/api/runs',{theme:$('theme').value,auto:$('auto').checked});selected=r.id;renderedStatus='';notice('Production ajoutée. Tu peux suivre les étapes ci-dessous.');await refresh();}catch(e){notice(e.message);}finally{b.disabled=false;}};
$('keyform').onsubmit=async e=>{e.preventDefault();try{await api('/api/settings',{brave_key:$('key').value});$('key').value='';notice('Clé enregistrée localement.');await health();}catch(e){notice(e.message);}};
$('refresh').onclick=()=>health().catch(e=>notice(e.message));
(async()=>{try{token=(await api('/api/session')).token;await health();await refresh();setInterval(refresh,1000);}catch(e){notice('Connexion impossible : '+e.message);}})();

function field(parent,label,value,rows=3){
  const wrap=el('label',label,'editor-field'),input=el('textarea');input.value=value;input.rows=rows;
  wrap.append(input);parent.append(wrap);return input;
}
function showProgress(parent,r){
  const p=r.progress,names=['Choisir l’idée','Valider le script','Valider les plans','Valider les images','Le Short'];
  parent.append(el('p',(p.auto?'Mode Auto · ':'Mode guidé · ')+`Étape ${p.number} sur 5 — ${names[p.number-1]}`,'stage-title'));
  const steps=el('ol',undefined,'steps');names.forEach((name,i)=>{const li=el('li',`${i+1}. ${name}`,i+1===p.number?'current':i+1<p.number?'complete':'');if(i+1===p.number)li.setAttribute('aria-current','step');steps.append(li);});parent.append(steps);
  if(p.live){showLive(parent,r);return;}
  if(!p.pending)return;
  const pending=p.pending,value=pending.value,box=el('section',undefined,'approval');parent.append(box);
  async function submit(changes,button){
    button.disabled=true;
    try{await api('/api/runs/'+r.id+'/approve',{stage:pending.stage,input_hash:pending.input_hash,changes});renderedStatus='';await refresh();}
    catch(e){notice(e.message);button.disabled=false;}
  }
  function validate(label,getChanges){const b=el('button',label);b.onclick=()=>submit(getChanges(),b);box.append(b);}
  if(pending.stage==='idea'){
    box.append(el('h4','Choisis un sujet avant la recherche approfondie'),el('p','Notes indicatives de pertinence, avant vérification des sources.','muted'));
    for(const reason of Object.values(value.rejected||{}))box.append(el('p',reason,'bad'));
    const cards=el('div',undefined,'idea-cards');box.append(cards);
    for(const idea of value.ideas){const card=el('article',undefined,'idea-card');card.append(el('h4',idea.candidate.title),el('p',idea.candidate.angle),el('strong',`${idea.score}/100`),el('p',idea.reason,'muted'));const b=el('button','Choisir');b.onclick=()=>submit({id:idea.id},b);card.append(b);cards.append(card);}
  }else if(pending.stage==='script'){
    box.append(el('h4','Relis et modifie le texte, puis valide'),el('p','Les modifications sont conservées après validation. Les faits et sources restent consultables dans le rapport final.','muted'));
    if(value.review?.score!==undefined)box.append(el('strong',`Note éditoriale : ${value.review.score}/10`));
    const title=field(box,'Titre',value.narrative.title,1),description=field(box,'Description',value.narrative.description,2);
    const scenes=value.narrative.scenes.map(s=>({scene:s,input:field(box,`Scène ${s.id} · texte dit`,s.narration)}));
    validate('Valider le script',()=>({narrative:{...value.narrative,title:title.value,description:description.value,scenes:scenes.map(x=>({...x.scene,narration:x.input.value}))}}));
  }else if(pending.stage==='storyboard'){
    box.append(el('h4','Vérifie le découpage plan par plan'));
    const plans=value.script.scenes.map(s=>{const card=el('article',undefined,'plan');card.append(el('h4',`Plan ${s.id}`),el('p',s.narration));box.append(card);return {id:s.id,visual:field(card,'Ce qu’on voit',s.visual),prompt:field(card,'Idée d’image / prompt',s.image_prompt)};});
    validate('Valider les plans',()=>({scenes:plans.map(p=>({id:p.id,visual:p.visual.value,image_prompt:p.prompt.value}))}));
  }else if(pending.stage==='images'){
    box.append(el('h4','Choisis une image pour chaque plan'),el('p','Tous les essais disponibles sont affichés avec leurs notes.','muted'));
    const choices={};
    for(const selectedImage of value.scenes){
      choices[selectedImage.scene]=selectedImage.attempt;
      const card=el('article',undefined,'plan');card.append(el('h4',`Plan ${selectedImage.scene}`));box.append(card);
      const plan=(value.plans||[]).find(p=>p.id===selectedImage.scene);if(plan)card.append(el('p',plan.narration),el('p',plan.visual,'muted'));
      const trials=el('div',undefined,'image-trials');card.append(trials);
      for(const c of value.candidates.filter(x=>x.scene===selectedImage.scene)){
        const label=el('label',undefined,'image-choice'),radio=el('input');radio.type='radio';radio.name=`scene-${c.scene}`;radio.checked=c.attempt===selectedImage.attempt;radio.onchange=()=>{choices[c.scene]=c.attempt;};
        const img=el('img');img.src=`/api/runs/${r.id}/images/${c.scene}/${c.attempt}`;img.alt=`Plan ${c.scene}, essai ${c.attempt}`;img.loading='lazy';
        label.append(img,radio,el('span',`Essai ${c.attempt} · ${c.score_100}/100`));
        if(c.review?.issues?.length)label.append(el('small',c.review.issues.join(' · '),'muted'));
        trials.append(label);
      }
    }
    validate('Valider les images et monter le Short',()=>({choices}));
  }
}
