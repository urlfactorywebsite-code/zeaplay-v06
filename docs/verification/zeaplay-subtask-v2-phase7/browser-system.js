async (page) => {
  page.setDefaultTimeout(10000);
  await page.setViewportSize({width:1280,height:900});
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if ((url.hostname === '127.0.0.1' && url.port === '6325') || url.hostname === 'cdn.tailwindcss.com') return route.continue();
    return route.fulfill({status:200,body:''});
  });
  const checks = [];
  const check = (name, passed) => {if (!passed) throw Error(name); checks.push(name);};
  await page.goto('http://127.0.0.1:6325/checks/phase7.html');
  const child = page.getByRole('group',{name:'Subtask Additional reward',exact:true});
  await child.waitFor();
  check('real authenticated API renders managed rows and available base', (await page.locator('body').innerText()).includes('Uncompleted base available: 30'));
  await page.getByText('Add subtask',{exact:true}).first().click();
  const create = page.locator('form').filter({has:page.getByRole('button',{name:'Add subtask',exact:true})});
  await create.getByLabel('Title *',{exact:true}).fill('Third UI subtask');
  await create.getByRole('button',{name:'Add subtask',exact:true}).click();
  check('browser requires both planned dates', await create.getByLabel('Planned start *',{exact:true}).evaluate(el=>!el.checkValidity()));
  await create.getByLabel('Planned start *',{exact:true}).fill('2026-11-02');
  await create.getByLabel('Planned end *',{exact:true}).fill('2026-11-03');
  await create.getByRole('button',{name:'Add subtask',exact:true}).click();
  await page.getByRole('group',{name:'Subtask Third UI subtask',exact:true}).waitFor();
  check('third subtask creates cumulative base capacity 60', (await page.locator('body').innerText()).includes('Base capacity: 60'));
  for (const [action,status] of [['Start','In Progress'],['Pause','Paused'],['Resume','In Progress'],['Send to Testing','Testing']]) {
    await child.getByRole('button',{name:action,exact:true}).click();
    await child.getByText(new RegExp(`^${status} ·`)).waitFor();
  }
  await child.getByText('Edit details and actual times',{exact:true}).click();
  check('status actions leave manual fields blank', (await child.getByLabel('Actual start',{exact:true}).inputValue()) === '' && (await child.getByLabel('Actual end',{exact:true}).inputValue()) === '');
  await child.getByLabel('Actual start',{exact:true}).fill('2026-11-03T10:00:00');
  await child.getByLabel('Actual end',{exact:true}).fill('2026-11-03T11:00:00');
  await child.getByRole('checkbox',{name:/I confirm these manually entered/}).check();
  await child.getByRole('combobox').selectOption('LOW');
  await child.getByRole('button',{name:'Save changes',exact:true}).click();
  await child.getByText(/^Testing · LOW/).waitFor();
  await child.getByRole('button',{name:'Complete',exact:true}).click();
  await child.getByText(/Completed/).waitFor();
  check('subtask override is LOW', (await child.innerText()).includes('LOW'));
  const raw = await page.evaluate(async()=>{
    const {taskId,headers}=window.__phase7;
    return await (await fetch(`/api/tasks/${taskId}`,{headers})).json();
  });
  const completed = raw.subtasks.find(row=>row.title==='Additional reward');
  check('manual local wall times stored as UTC without status overwrite', completed.actual_start_at.startsWith('2026-11-03T04:30:00') && completed.actual_end_at.startsWith('2026-11-03T05:30:00'));
  check('LOW display override still earns HIGH parent 30 plus existing 15 bonus', raw.subtask_rewards.earned===45);
  await page.getByRole('button',{name:'Task information',exact:true}).click();
  const modal = page.getByRole('dialog',{name:'Task information',exact:true});
  await modal.getByText('Task ID',{exact:true}).waitFor();
  for (const name of ['Overview','Status timeline','Subtasks','Points','Activity']) {
    await modal.getByRole('tab',{name,exact:true}).click();
    await page.waitForTimeout(200);
    check(`authorized ${name} tab loads from aggregation API`, await modal.getByRole('tab',{name,exact:true}).getAttribute('aria-selected')==='true' && await modal.getByRole('alert').count()===0);
  }
  await page.keyboard.press('Escape');
  await modal.waitFor({state:'hidden'});
  check('Escape restores focus to icon', await page.getByRole('button',{name:'Task information',exact:true}).evaluate(el=>el===document.activeElement));
  await page.getByRole('button',{name:'View information',exact:true}).click();
  await modal.waitFor();
  check('details action opens same complete modal', await modal.getByRole('tab').count()===5);
  await modal.getByRole('tab',{name:'Subtasks',exact:true}).click();
  await page.waitForTimeout(200);
  await page.setViewportSize({width:390,height:844});
  check('mobile modal stays within viewport', await modal.evaluate(el=>el.getBoundingClientRect().width<=window.innerWidth+1));
  await page.addScriptTag({url:'http://127.0.0.1:6325/checks/axe.min.js'});
  const accessibility = [];
  for(const name of ['Overview','Status timeline','Subtasks','Points','Activity']) {
    await modal.getByRole('tab',{name,exact:true}).click();
    await page.waitForTimeout(180);
    const scan = await page.evaluate(async()=>await window.axe.run(document.querySelector('[role="dialog"][aria-label="Task information"]') || document.querySelector('[role="dialog"]'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']},rules:{'color-contrast':{enabled:false}}}));
    accessibility.push({tab:name,violations:scan.violations.map(v=>({id:v.id,impact:v.impact,targets:v.nodes.map(n=>n.target)})),incomplete:scan.incomplete.map(v=>v.id)});
  }
  await page.keyboard.press('Escape');
  await page.setViewportSize({width:1280,height:900});
  await child.getByRole('button',{name:'Reopen',exact:true}).click();
  await page.waitForTimeout(200);
  const points = await page.evaluate(async()=>{const {taskId,headers}=window.__phase7;return await(await fetch(`/api/tasks/${taskId}/information?section=points`,{headers})).json();});
  check('reopen posts compensation and returns earned balance to zero',points.points.subtask_earned===0 && points.points.components.REVERSAL===-45);
  return {checks,accessibility,pointExample:{base:30,bonus:15,earned:45,reversed:-45,net:0},transport:'actual localhost FastAPI/JWT/SQL; external sinks and Redis excluded'};
}
