// Optional browser regression: npm-installed Playwright + Chromium required.
// Start python tests/ui_fixture_server.py first. Never run against real production data.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8765');
    await page.getByText('Services IA simules, donnees temporaires',{exact:false}).waitFor();
    assert.equal(await page.locator('#auto').isChecked(),false);
    await page.getByRole('button',{name:'Créer une vidéo'}).click();
    await page.getByRole('button',{name:'Choisir',exact:true}).first().waitFor();
    assert.equal(await page.getByRole('button',{name:'Choisir',exact:true}).count(),3);
    await page.getByRole('button',{name:'Choisir',exact:true}).nth(1).click();
    await page.getByRole('button',{name:'Valider le script',exact:true}).waitFor();
    await page.getByLabel('Titre',{exact:true}).fill('Titre valide dans le navigateur');
    await page.getByLabel('Scène 1 · texte dit').fill('Cette narration a ete modifiee dans le navigateur.');
    // Polling must not erase a draft while the user edits it.
    await page.waitForTimeout(3200);
    assert.equal(await page.getByLabel('Titre',{exact:true}).inputValue(),'Titre valide dans le navigateur');
    await page.getByRole('button',{name:'Valider le script',exact:true}).click();
    await page.getByRole('button',{name:'Valider les plans',exact:true}).waitFor();
    await page.getByLabel('Ce qu’on voit',{exact:true}).first().fill('Plan corrige a la souris');
    await page.getByRole('button',{name:'Valider les plans',exact:true}).click();
    await page.getByRole('button',{name:'Valider les images et monter le Short'}).waitFor();
    assert.equal(await page.locator('.image-choice img').count(),10);
    await page.locator('.image-choice').first().click();
    assert.equal(await page.locator('.image-choice input').first().isChecked(),true);
    // Stop then resume the selected production; image approval remains mandatory.
    await page.getByRole('button',{name:'Arrêter',exact:true}).click();
    await page.getByRole('button',{name:'Reprendre',exact:true}).click();
    await page.getByRole('button',{name:'Valider les images et monter le Short'}).waitFor();
    await page.locator('.image-choice').first().click();
    await page.getByRole('button',{name:'Valider les images et monter le Short'}).click();
    await page.locator('#detail .badge').filter({hasText:'Prête à visionner'}).waitFor();
    assert.equal(await page.locator('#detail video').count(),1);
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=1);
    await page.locator('video').click();
    await page.screenshot({path:'/tmp/autoshort-guided.png',fullPage:true});
    // Auto must reach the video without another approval click.
    await page.locator('#auto').check();
    await page.getByRole('button',{name:'Créer une vidéo'}).click();
    await page.locator('#detail .badge').filter({hasText:'Prête à visionner'}).waitFor();
    assert.equal(await page.locator('.approval').count(),0);
    await page.locator('#detail .stage-title').filter({hasText:'Mode Auto'}).waitFor();
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=1);
    await page.screenshot({path:'/tmp/autoshort-auto.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('PASS: guided five steps, editing, image selection, stop/resume, video playback, Auto without approvals; no browser errors. AI services simulated.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
