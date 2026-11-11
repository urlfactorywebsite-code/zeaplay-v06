async (page) => {
  page.setDefaultTimeout(7000); page.setDefaultNavigationTimeout(15000);
  await page.setViewportSize({width:1440,height:1000});
  await page.route('**/*', async route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1' && u.port === '6325') return u.pathname.startsWith('/api/') ? route.fulfill({json:[]}) : route.continue();
    if (u.hostname === 'cdn.tailwindcss.com') return route.continue();
    return route.fulfill({status:200,body:''});
  });
  await page.addInitScript(() => {
    localStorage.removeItem('zea:notification-seen:phase6-user');
    const intervals = new Map(), timeouts = new Map();
    const interval = window.setInterval.bind(window), clearInterval = window.clearInterval.bind(window);
    const timeout = window.setTimeout.bind(window), clearTimeout = window.clearTimeout.bind(window);
    window.setInterval = (fn, ms, ...args) => {
      const id = interval(fn, ms, ...args); intervals.set(id,{fn,ms,stack:new Error().stack}); return id;
    };
    window.clearInterval = id => {intervals.delete(id);clearInterval(id);};
    window.setTimeout = (fn, ms, ...args) => {
      const id = timeout(()=>{timeouts.delete(id);if(typeof fn==='function')fn(...args);},ms);
      timeouts.set(id,{fn,ms,stack:new Error().stack});return id;
    };
    window.clearTimeout = id => {timeouts.delete(id);clearTimeout(id);};
    window.__phase6Timers={intervals,timeouts};
  });
  const checks=[];
  const check=(name,ok)=>{if(!ok)throw Error(name);checks.push({name,result:'PASS'});};
  await page.goto('http://127.0.0.1:6325/checks/phase6.html');await page.waitForTimeout(1300);
  const state=()=>page.evaluate(()=>{const s=window.__phase6.state;return {calls:s.calls,activity:s.activityCalls,maxInFlight:s.maxInFlight,maxActivityFlight:s.maxActivityFlight,sockets:s.sockets.filter(x=>x.readyState===1).length,prompts:s.prompts};});
  const first=await state();
  await page.evaluate(()=>{for(let n=0;n<10;n++)for(const entry of window.__phase6Timers.intervals.values())if(entry.ms>=30000&&entry.ms<35000)entry.fn();});
  await page.waitForTimeout(400);
  check('Healthy socket has no periodic inbox or workload HTTP polling',(await state()).calls===first.calls&&(await state()).activity===first.activity);
  const beforeBurst=await state();
  await page.evaluate(()=>{const f=window.__phase6;f.state.delay=450;f.state.activityDelay=450;f.state.burst=setInterval(()=>f.emit(),20);});
  await page.waitForTimeout(1050);
  check('Continuous events refresh before the burst stops',(await state()).calls>=beforeBurst.calls+2);
  await page.evaluate(()=>clearInterval(window.__phase6.state.burst));await page.waitForTimeout(1400);
  const afterBurst=await state();
  check('Slow reads stay single flight with one pending refresh',afterBurst.maxInFlight===1&&afterBurst.calls-beforeBurst.calls<=5);
  check('Slow workload queries are not canceled and restarted by every event',afterBurst.maxActivityFlight===1);
  await page.evaluate(()=>{window.__phase6.state.delay=0;window.__phase6.state.activityDelay=0;Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});});
  const hidden=await state();
  await page.evaluate(()=>{for(let n=0;n<100;n++)window.__phase6.emit();});await page.waitForTimeout(650);
  check('Inactive tabs do not refetch inbox or workload for activity bursts',(await state()).calls===hidden.calls&&(await state()).activity===hidden.activity);
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});window.__phase6.state.unread=777;document.dispatchEvent(new Event('visibilitychange'));});
  await page.waitForTimeout(650);
  check('Returning to the tab restores authoritative unread badge',await page.getByRole('button',{name:/Notifications, 777 unread/}).isVisible());
  const beforeReconnect=await state();
  await page.evaluate(()=>{window.__phase6.state.sockets.find(s=>s.readyState===1).close();});
  await page.waitForFunction(()=>window.__phase6.state.sockets.filter(s=>s.readyState===1).length===1);
  await page.waitForTimeout(700);
  check('Socket reconnect keeps one connection and refetches both projections',(await state()).sockets===1&&(await state()).calls>beforeReconnect.calls&&(await state()).activity>beforeReconnect.activity);
  const boundaries=await page.evaluate(()=>[...window.__phase6Timers.timeouts.values()].filter(x=>x.ms>60000&&x.stack.includes('useTaskActivity.ts')).length);
  check('Local-day recovery uses one scheduled boundary instead of clock polling',boundaries===1);
  const beforeBoundary=await state();
  await page.evaluate(()=>{const e=[...window.__phase6Timers.timeouts.values()].find(x=>x.ms>60000&&x.stack.includes('useTaskActivity.ts'));e.fn();});await page.waitForTimeout(600);
  check('Boundary event refetches workload once',(await state()).activity===beforeBoundary.activity+1);
  const beforeUnmount=await state();await page.evaluate(()=>window.__phase6.state.toggle(false));await page.waitForTimeout(150);
  await page.evaluate(()=>{window.__phase6.notify();window.dispatchEvent(new Event('online'));});await page.waitForTimeout(400);
  check('Closed activity UI leaves no socket or inbox requests',(await state()).sockets===0&&(await state()).calls===beforeUnmount.calls);
  check('Denied browser never prompts during reconnect, inactivity or bursts',(await state()).prompts===0);
  return {checks,counts:{beforeBurst,afterBurst},note:'Real hooks/Header and synthetic API; interval callbacks invoked for deterministic polling proof.'};
}
