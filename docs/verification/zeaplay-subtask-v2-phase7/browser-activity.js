async page => {
  await page.unroute('**/*');
  await page.route('**/*',async route=>{const u=new URL(route.request().url());if((u.hostname==='127.0.0.1'&&u.port==='6325')||u.hostname==='cdn.tailwindcss.com')return route.continue();return route.fulfill({status:200,body:''});});
  await page.goto('http://127.0.0.1:6325/checks/phase7.html');
  await page.getByRole('group',{name:'Subtask Additional reward',exact:true}).waitFor();
  const seeded=await page.evaluate(async()=>{
    const {headers}=window.__phase7;
    const call=async(path,body)=>{const r=await fetch('/api'+path,{method:body?'POST':'GET',headers,body:body?JSON.stringify(body):undefined});const data=await r.json();if(!r.ok)throw Error(JSON.stringify(data));return data;};
    const old=await call('/tasks/activity');
    for(const c of old.contexts.filter(c=>c.status==='RUNNING'))await call(`/tasks/${c.task_id}/activity`,{action:'STOP',subtask_id:c.subtask_id,expected_version:c.version,request_id:crypto.randomUUID()});
    const ids=[];
    for(let i=0;i<6;i++){const [task]=await call('/tasks',{title:`Browser slot ${i+1}`,team:'IT Support',priority:'HIGH',assigned_to_id:'owner'});ids.push(task.id);}
    for(const id of ids.slice(0,5))await call(`/tasks/${id}/activity`,{action:'START',expected_version:0,request_id:crypto.randomUUID()});
    const denied=await fetch(`/api/tasks/${ids[5]}/activity`,{method:'POST',headers,body:JSON.stringify({action:'START',expected_version:0,request_id:crypto.randomUUID()})});
    return {ids,denied:denied.status,before:await call('/tasks/activity')};
  });
  if(seeded.denied!==409 || seeded.before.active_count!==5)throw Error('Five-slot backend enforcement');
  await page.reload();
  await page.getByRole('button',{name:'Close modal',exact:true}).click();
  const control=page.getByRole('button',{name:'Task activity 5 out of five',exact:true});
  await control.waitFor();
  await control.click();
  const dialog=page.getByRole('dialog',{name:'Task activity and workload',exact:true});
  await dialog.waitFor();
  const names=await dialog.innerText();
  if(![1,2,3,4,5].every(n=>names.includes(`Browser slot ${n}`)))throw Error('Popup must show all five persisted slots');
  await dialog.getByRole('button',{name:'Pause',exact:true}).first().click();
  await dialog.getByText('Phase 7 owner: 4/5 active parents',{exact:true}).waitFor();
  const after=await page.evaluate(async()=>{const {headers}=window.__phase7;return await(await fetch('/api/tasks/activity',{headers})).json();});
  if(after.active_count!==4)throw Error('Pause must free a persisted slot');
  const kept=after.contexts.filter(c=>c.status==='RUNNING');
  if(!kept.every(c=>c.elapsed_seconds>0))throw Error('Server elapsed clocks must survive reload');
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Task activity 4 out of five',exact:true}).waitFor();
  return {checks:5,sixth:seeded.denied,activeAfterReload:5,activeAfterPause:after.active_count,clockSource:'Server-persisted elapsed activity; manual productive time remains separate',minimumRunningElapsedSeconds:Math.min(...kept.map(c=>c.elapsed_seconds))};
}
