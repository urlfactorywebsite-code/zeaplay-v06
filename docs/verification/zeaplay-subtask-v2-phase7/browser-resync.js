async page => {
  await page.goto('http://127.0.0.1:6325/checks/phase6.html');
  await page.waitForTimeout(1200);
  const before = await page.evaluate(()=>{
    const s=window.__phase6.state;
    window.__phase7TaskInvalidations=0;
    window.addEventListener('zea:tasks-changed',()=>window.__phase7TaskInvalidations++);
    return {inbox:s.calls,activity:s.activityCalls};
  });
  await page.evaluate(()=>window.__phase6.state.sockets.filter(s=>s.readyState===1).forEach(s=>s.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'tasks.resync',tenant_id:'synthetic-tenant'})}))));
  await page.waitForTimeout(700);
  const after = await page.evaluate(()=>({inbox:window.__phase6.state.calls,activity:window.__phase6.state.activityCalls,tasks:window.__phase7TaskInvalidations}));
  if(after.inbox!==before.inbox+1 || after.activity!==before.activity+1 || after.tasks!==1) throw Error('Redis resubscription must refresh all three authoritative projections once');
  return {checks:3,before,after,scope:'Actual Header recovery handler; synthetic Redis-to-WebSocket frame'};
}
