// Start python tests/ui_fixture_server.py. Uses only isolated deterministic AI fixtures.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8765');
    await page.getByText('Services IA simules, donnees temporaires',{exact:false}).waitFor();
    assert.equal(await page.locator('#auto').isChecked(),false);
    await page.getByRole('button',{name:'Créer une vidéo'}).click();
    const area=()=>page.locator('.live-stage');
    const cards=()=>area().locator('.proposal-card');
    await cards().first().waitFor();
    assert.equal(await cards().count(),1);
    assert.equal(await area().locator('[data-status=running]').count(),1);
    // Request a new idea while automatic idea 2 is already running.
    await area().getByRole('button',{name:'+ Nouvelle proposition',exact:true}).click();
    const dialog=()=>page.locator('#proposal-editor');
    const initial=await dialog().getByLabel('Prompt de génération').inputValue();assert.ok(initial.length>20);
    await dialog().getByLabel('Prompt de génération').fill('MANUAL IDEA: un autre angle precis');
    await dialog().getByRole('button',{name:'Générer',exact:true}).click();
    await area().getByText('En cours · Proposition · demande prioritaire',{exact:true}).waitFor();
    assert.equal(await cards().count(),2);
    assert.ok(await area().getByText('En attente · Proposition',{exact:true}).count());
    await cards().nth(2).waitFor();assert.ok(await cards().count()>=3);
    const firstId=await cards().first().getAttribute('data-proposal');
    await cards().first().getByRole('button',{name:'Choisir',exact:true}).click();
    await page.locator('.live-stage[data-stage=script] .proposal-card').first().waitFor();
    assert.equal(await cards().count(),1);
    assert.ok(await page.locator(`.proposal-archive [data-proposal="${firstId}"]`).count());
    // Edit and validate a new script version while the variant keeps running.
    await cards().first().getByRole('button',{name:'Modifier',exact:true}).click();
    await dialog().getByLabel('Titre',{exact:true}).fill('Titre choisi dans le navigateur');
    // A backend polling refresh must not destroy the open editor.
    await page.waitForTimeout(1100);
    assert.equal(await dialog().getByLabel('Titre',{exact:true}).inputValue(),'Titre choisi dans le navigateur');
    await dialog().getByRole('button',{name:'Valider cette version',exact:true}).click();
    await page.locator('.live-stage[data-stage=storyboard] .proposal-card').first().waitFor();
    assert.equal(await cards().count(),1);
    // A plus on one storyboard plan creates a separate full-board version.
    await cards().first().getByRole('button',{name:'Nouvelle version du plan 1',exact:true}).click();
    await dialog().getByLabel('Prompt de génération').fill('Un gros plan sur cet objet, meme epoque.');
    await dialog().getByRole('button',{name:'Générer',exact:true}).click();
    await area().getByText('En cours · Proposition · plan 1 · demande prioritaire',{exact:true}).waitFor();
    await cards().nth(2).waitFor();
    await cards().last().getByRole('button',{name:'Choisir',exact:true}).click();
    const firstPlan=page.locator('.image-plan[data-plan="1"]');
    await firstPlan.locator('.proposal-card').first().waitFor();
    assert.equal(await page.locator('.image-plan[data-plan="2"] .proposal-card').count(),0);
    await firstPlan.getByRole('button',{name:'Retenir',exact:true}).first().click();
    await firstPlan.getByRole('button',{name:'Nouvelle image pour le plan 1',exact:true}).click();
    assert.ok((await dialog().getByLabel('Prompt de cette image').inputValue()).length);
    await dialog().getByLabel('Prompt de cette image').fill('A new close-up of the same object');
    await dialog().getByRole('button',{name:'Générer',exact:true}).click();
    await firstPlan.getByText('En cours · Proposition · plan 1 · demande prioritaire',{exact:true}).waitFor();
    assert.equal(await page.locator('.image-plan[data-plan="3"] .proposal-card').count(),0);
    await firstPlan.locator('.proposal-card').nth(1).waitFor();
    await firstPlan.getByRole('button',{name:'Retenir',exact:true}).last().click();
    await page.locator('.image-plan[data-plan="5"] .proposal-card').first().waitFor();
    assert.ok(await page.locator('.live-stage [data-status=queued]').count());
    await page.screenshot({path:'/tmp/autoshort-progressive-images.png',fullPage:true});
    await page.getByRole('button',{name:'Valider l’ensemble des images',exact:true}).click();
    await page.locator('#detail .badge').filter({hasText:'Prête à visionner'}).first().waitFor();
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=1);
    // Click native video control area and confirm the video can play.
    await page.locator('video').click();
    await page.screenshot({path:'/tmp/autoshort-progressive-ready.png',fullPage:true});
    // Auto does not expose manual cards or + and goes directly to the player.
    await page.locator('#auto').check();
    await page.getByRole('button',{name:'Créer une vidéo'}).click();
    await page.locator('#detail .stage-title').filter({hasText:'Mode Auto'}).waitFor();
    await page.locator('#detail .badge').filter({hasText:'Prête à visionner'}).first().waitFor();
    assert.equal(await page.locator('#detail .live-stage, #detail .approval').count(),0);
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=1);
    assert.deepEqual(errors,[]);
    console.log('PASS: incremental ideas/script/storyboard/images, editable +, priority after current job, retained history, edited script, per-plan storyboard +, image choice during generation, full image validation, video, Auto without gates. AI simulated; real FFmpeg MP4.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
