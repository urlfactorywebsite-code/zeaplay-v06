/* Independent real-browser authentication audit. No issued-token/clock/auth mocks. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const execFile=require('node:util').promisify(require('node:child_process').execFile);
const {chromium}=require(process.env.ZEA_PLAYWRIGHT_MODULE);
const state=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const appBase=process.env.ZEA_PHASE2A1_AUDIT_BASE_PATH||'';
assert(['','/audit-legacy'].includes(appBase));
const expectBootstrapFailure=process.env.ZEA_PHASE2A1_AUDIT_EXPECT_BOOTSTRAP_FAILURE==='1';
assert(!expectBootstrapFailure||appBase==='/audit-legacy');
assert.match(state.origin,/^http:\/\/127\.0\.0\.1:\d+$/);
assert.equal(execFileSync('docker',['inspect','--format','{{index .Config.Labels "zea.phase15"}}',state.backend],{encoding:'utf8',windowsHide:true}).trim(),state.run);
const sleep=ms=>new Promise(r=>setTimeout(r,ms)), results=[],blocked=new Set();
const safe=s=>String(s).replaceAll(state.password,'[REDACTED]').replace(/\beyJ[\w-]+\.[\w-]+\.[\w-]+/g,'[REDACTED_TOKEN]');
const claims=t=>JSON.parse(Buffer.from(t.split('.')[1],'base64url').toString());
async function info(id){const r=await execFile('docker',['exec',state.backend,'python','-B','/tests/mcp_phase2a1_audit_state.py',id],{encoding:'utf8',timeout:15000,windowsHide:true});return JSON.parse(r.stdout.trim().split('\n').at(-1));}
async function eventually(work,label,ms=20000){const end=Date.now()+ms;while(Date.now()<end){if(await work())return;await sleep(200)}throw Error('Timed out: '+label)}
async function bounded(promise,label){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Timed out: '+label)),20000)})])}finally{clearTimeout(timer)}}
async function api(p,endpoint,token='',method='GET',body){return p.evaluate(async({endpoint,token,method,body})=>{
  const r=await fetch('/api'+endpoint,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:body===undefined?undefined:JSON.stringify(body)});
  let data;try{data=await r.json()}catch{}return{status:r.status,data};
},{endpoint,token,method,body});}
const tokens=p=>p.evaluate(()=>({access:localStorage.getItem('vee_access_token'),refresh:localStorage.getItem('vee_refresh_token')}));
async function login(p,email){await p.goto(state.origin+appBase+'/#/login');await p.locator('#email-address').fill(email);await p.locator('#password').fill(state.password);await p.locator('#password').press('Enter');await p.waitForURL(u=>u.hash && !['#/','#'].includes(u.hash) && !u.hash.includes('/login'));}
function save(){fs.writeFileSync(path.join(state.evidence,'independent-auth-audit'+(process.env.ZEA_PHASE2A1_AUDIT_SUFFIX||'-final')+'.json'),JSON.stringify({run:state.run,app_base:appBase,expected_legacy_failure:expectBootstrapFailure,filter:process.env.ZEA_PHASE2A1_AUDIT_FILTER||null,expected_cases:selected.map(v=>v.name),results,blocked_external_hosts:[...blocked],authentication:'Real UI password login and actual backend-issued tokens; no auth or clock mocks'},null,2));}
const variants=[
  {name:'A01_two_tabs_natural_expiry',tabs:2},
  {name:'A02_three_tabs_slow_retried_bootstrap',tabs:3,getDelay:9000},
  {name:'A03_four_tabs_waiter_reload_during_rotation',tabs:4,responseDelay:1250,reloadWaiter:true},
  {name:'A04_three_tabs_delayed_expired_response',tabs:3,late401:true},
  {name:'A05_issuing_tab_reload_after_backend_consumption',tabs:2,issuerReload:true},
  {name:'A06_new_login_wins_over_held_old_rotation',tabs:2,newLogin:true},
  {name:'A07_revocation_during_held_rotation',tabs:2,revoke:true},
  {name:'A08_bootstrap_timeout_after_completed_rotation',tabs:2,bootstrapTimeout:true},
];
const selected=variants.filter(v=>!process.env.ZEA_PHASE2A1_AUDIT_FILTER||new RegExp(process.env.ZEA_PHASE2A1_AUDIT_FILTER).test(v.name));
(async()=>{
 let browser;
 async function run(v){
  const began=Date.now(), trace=[],http=[],pendingBodies=[],pageErrors=[];let user,ctx,releaseHeld,releaseOld;const details={variant:v};
  try{
   ctx=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
   await ctx.exposeBinding('__auditRecord',({page},event)=>{trace.push({page:ctx.pages().indexOf(page),...event});});
   await ctx.addInitScript(()=>{
    const meta=t=>{try{const c=JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));return{sid:c.sid,exp:c.exp,epoch:c.auth_epoch}}catch{return null}};
    const record=e=>void window.__auditRecord({at:Date.now(),...e});
    for(const op of ['setItem','removeItem']){const original=Storage.prototype[op];Storage.prototype[op]=function(key,...args){
     if(['vee_access_token','vee_refresh_token','vee_refresh_attempt'].includes(key)) record({op,key,value:key==='vee_refresh_attempt'?Boolean(args[0]):meta(args[0]),stack:new Error().stack.split('\n').slice(1,9).join('\n')});
     return original.call(this,key,...args);
    }}
    addEventListener('auth:expired',()=>record({event:'auth:expired'}));
    addEventListener('storage',e=>{if(['vee_access_token','vee_refresh_token'].includes(e.key))record({event:'storage',key:e.key,value:meta(e.newValue)});});
    const listen=window.addEventListener.bind(window);
    window.addEventListener=function(type,...args){
      if(type==='storage'){
        const stack=new Error().stack;
        if(stack.includes('waitForTokenChange'))record({event:'receipt_wait_started',stack});
      }
      return listen(type,...args);
    };
   });
   await ctx.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin===state.origin || ['data:','blob:'].includes(u.protocol))return r.continue();blocked.add(u.hostname);return r.abort();});
   ctx.on('page',p=>{p.on('pageerror',e=>pageErrors.push(safe(e.message)));p.on('crash',()=>pageErrors.push('Renderer crash'));
    p.on('response',r=>{
    if(!r.url().startsWith(state.origin+'/api/'))return;
    const e={path:new URL(r.url()).pathname,status:r.status(),at:Date.now(),page:ctx.pages().indexOf(p)};http.push(e);
    if(e.path==='/api/auth/refresh')pendingBodies.push(r.json().then(d=>{
     const meta=t=>{try{const c=claims(t);return{sid:c.sid,exp:c.exp,epoch:c.auth_epoch}}catch{return null}};
     e.issued={access:meta(d.access_token),refresh:meta(d.refresh_token)};
    }).catch(()=>{}));
   });});
   const admin=await ctx.newPage();await admin.goto(state.origin+'/runtime-config.js');
   const signed=await api(admin,'/auth/login','','POST',{email:'owner@phase15.example.com',password:state.password});assert.equal(signed.status,200);
   const authority=signed.data.token.access_token;
   const email='phase2a1-audit-'+state.run.slice(0,8)+'-'+v.name.slice(0,3).toLowerCase()+'-'+Date.now().toString(36)+'@phase15.example.com';
   const created=await api(admin,'/users',authority,'POST',{name:'Phase2A1Audit '+v.name,email,password:state.password,role:'manager',status:'ACTIVE',department_id:state.fixture.department});assert.equal(created.status,201,'Create synthetic actor; validation locations: '+(created.data?.detail||[]).map?.(e=>e.loc?.join('.')).join(','));user=created.data;
   const pages=[await ctx.newPage()];await login(pages[0],email);await pages[0].goto(state.origin+appBase+'/#/admin/users');
   for(let i=1;i<v.tabs;i++){const p=await ctx.newPage();await p.goto(state.origin+appBase+'/#/admin/users');pages.push(p);}
   await eventually(async()=>(await info(user.id)).presence_sockets>=v.tabs,'initial real presence');
   let alternate;
   if(v.newLogin){
    // Render the real login form while the initial bearer is still valid.
    // Reloading a bootstrap while its refresh response is held would itself wait
    // for that response, preventing the intended competing-login interaction.
    alternate=await ctx.newPage();await alternate.goto(state.origin+'/#/login');
    await alternate.locator('#email-address').fill('foreign@phase15.example.com');
    await alternate.locator('#password').fill(state.password);
   }
   const before=await tokens(pages[0]),initial=claims(before.access),sid=initial.sid;
   if(v.bootstrapTimeout)await pages[1].goto(state.origin+appBase+'/#/login');
   let releaseRotation,arrivedResolve,lateResolve;
   const arrived=new Promise(r=>arrivedResolve=r),held=new Promise(r=>releaseRotation=r);releaseHeld=releaseRotation;
   const old=new Promise(r=>releaseOld=r),lateArrived=new Promise(r=>lateResolve=r);
   let posts=0;
   await ctx.route(state.origin+'/api/auth/refresh',async route=>{
    posts++; const response=await route.fetch(); // Actual verifier and PostgreSQL rotation, exactly once.
    details.refresh_status=response.status();arrivedResolve(route.request().frame().page());
    if(v.issuerReload||v.newLogin||v.revoke)await held;
    if(v.responseDelay)await sleep(v.responseDelay);
    await route.fulfill({response}).catch(()=>{});
   });
   if(v.getDelay){let reads=0;await pages[1].route(state.origin+'/api/auth/me',async r=>{if(++reads===2)await sleep(v.getDelay);await r.continue().catch(()=>{});});}
   if(v.late401){let first=true;await pages[1].route(state.origin+'/api/auth/me',async r=>{
    if(!first)return r.continue();first=false;const response=await r.fetch();assert.equal(response.status(),401);lateResolve();await old;await r.fulfill({response}).catch(()=>{});
   });}
   const gate=await ctx.newPage();await gate.goto(state.origin+'/runtime-config.js');
   await gate.evaluate(()=>{void navigator.locks.request('zeaplay-session-refresh',()=>new Promise(r=>{window.__release=r;window.__locked=true;}));});
   await gate.waitForFunction(()=>window.__locked);
   console.log('WAIT '+v.name+' actual token expiry');
   while(Date.now()<initial.exp*1000+1100)await sleep(300);
   assert.equal((await api(admin,'/auth/me',before.access)).status,401);
   await Promise.all((v.bootstrapTimeout?[pages[0]]:pages).map(p=>p.reload()));
   const needed=v.bootstrapTimeout?1:v.late401?v.tabs-1:v.tabs;
   await eventually(()=>gate.evaluate(async n=>(await navigator.locks.query()).pending.filter(l=>l.name==='zeaplay-session-refresh').length>=n,needed),'native lock waiters');
   if(v.late401)await bounded(lateArrived,'delayed 401 received');
   await gate.evaluate(()=>window.__release());
   const issuer=await bounded(arrived,'actual backend rotation');assert(pages.includes(issuer));
   if(v.reloadWaiter)await pages.find(p=>p!==issuer).reload();
   if(v.issuerReload){await issuer.reload();releaseRotation();}
   if(v.newLogin){await alternate.locator('#password').press('Enter');await alternate.waitForURL(u=>u.hash&&!['#/','#'].includes(u.hash)&&!u.hash.includes('/login'));releaseRotation();}
   if(v.revoke){const fresh=await api(admin,'/auth/login','','POST',{email:'owner@phase15.example.com',password:state.password});assert.equal(fresh.status,200);assert.equal((await api(admin,'/users/'+user.id,fresh.data.token.access_token,'PATCH',{status:'DEACTIVATED'})).status,200);releaseRotation();}
   if(v.late401){await eventually(async()=>(await tokens(pages[0])).access!==before.access,'first rotation stored');releaseOld();}
   if(v.bootstrapTimeout){
    await eventually(async()=>{const pair=await tokens(pages[0]);return pair.access&&pair.access!==before.access},'rotation completed before slow bootstrap');
    let first=true;await pages[1].route(state.origin+'/api/auth/me',async r=>{if(first){first=false;await sleep(9000)}await r.continue().catch(()=>{});});
    await pages[1].goto(state.origin+appBase+'/#/admin/users');
    await pages[1].reload(); // Hash navigation alone does not re-run AuthProvider bootstrap.
    if(expectBootstrapFailure)await eventually(async()=>!(await tokens(pages[0])).access,'historical slow bootstrap erases successor');
    else await eventually(()=>pages[1].url().includes('/login'),'slow bootstrap returns to login without authority');
    if(!expectBootstrapFailure){
      const pair=await tokens(pages[0]);assert(pair.access&&pair.access!==before.access,'Transport timeout preserves the healthy successor');
      assert.equal((await api(admin,'/auth/me',pair.access)).status,200);await pages[1].reload();await pages[1].goto(state.origin+appBase+'/#/admin/users');
    }
   }
   if(expectBootstrapFailure){
    assert(v.name==='A02_three_tabs_slow_retried_bootstrap'||v.bootstrapTimeout);
    await eventually(async()=>{const pair=await tokens(pages[0]);return !pair.access&&!pair.refresh},'historical bootstrap erases healthy successor');
    const persisted=(await info(user.id)).sessions.find(s=>s.id===sid);
    assert(!persisted.revoked);assert.equal(persisted.refresh_count,2);assert.equal(persisted.consumed_count,1);assert.equal(posts,1);
    assert(trace.some(e=>e.op==='removeItem'&&e.stack.includes('getCurrentUser')),'Erasure attributed to historical bootstrap call stack');
    details.first_erasure=trace.find(e=>e.op==='removeItem')?.stack;
    if(v.bootstrapTimeout)assert(details.first_erasure.includes('getCurrentUser'),'Bootstrap is the first erasure in the serialized control');
    details.reproduced_legacy_defect=true;
   } else if(v.issuerReload||v.revoke){
    if(v.revoke)await eventually(async()=>{const t=await tokens(pages[0]);return !t.access&&!t.refresh},'revoked storage cleared');
    await eventually(()=>Promise.all(pages.map(p=>p.url().includes('/login'))).then(a=>a.every(Boolean)),'all tabs require sign in');
    if(v.issuerReload){
      const retained=await tokens(pages[0]);assert(retained.access===before.access&&retained.refresh===before.refresh,'Uncertain shared state is preserved, not treated as authority');
      assert.equal((await api(admin,'/auth/me',retained.access)).status,401);
    }
    await eventually(async()=>(await info(user.id)).presence_sockets===0,'presence removed');
    assert.equal(posts,v.revoke?2:1,'No replay after lost issuer response; revocation denies the successor once');
   } else if(v.newLogin){
    await eventually(async()=>{const t=await tokens(pages[0]);return t.access&&claims(t.access).sub===state.fixture.users.foreign},'new login retained');
    await sleep(500);assert.equal(claims((await tokens(pages[0])).access).sub,state.fixture.users.foreign);assert.equal(posts,1);
   } else {
    await eventually(async()=>{const t=await tokens(pages[0]);return t.access&&t.access!==before.access},'stored successor');
    await eventually(()=>pages.every(p=>!p.url().includes('/login')),'all routes authenticated');
    await eventually(async()=>(await info(user.id)).presence_sockets>=v.tabs,'restored presence');
    const pair=await tokens(pages[0]);assert.equal((await api(admin,'/auth/me',pair.access)).status,200);
    const persisted=(await info(user.id)).sessions.find(s=>s.id===sid);assert(!persisted.revoked);assert.equal(persisted.refresh_count,2);assert.equal(persisted.consumed_count,1);assert.equal(posts,1);
    const renewalAt=Date.now();await eventually(()=>http.some(r=>r.path==='/api/auth/presence-token'&&r.status===200&&r.at>renewalAt),'real renewal timer',45000);
    assert.equal((await api(admin,'/auth/logout',pair.access,'POST',{})).status,204);
    await eventually(async()=>(await tokens(pages[0])).access===null,'cross-tab server revocation client detection',25000);
    assert.equal((await api(admin,'/auth/me',pair.access)).status,401);await eventually(async()=>(await info(user.id)).presence_sockets===0,'revoked presence',25000);
   }
   details.refresh_posts=posts;details.state=await info(user.id);results.push({name:v.name,status:expectBootstrapFailure?'EXPECTED_REPRODUCTION':'PASS',duration_ms:Date.now()-began,details,trace,http});console.log((expectBootstrapFailure?'EXPECTED_REPRODUCTION ':'PASS ')+v.name);
  }catch(e){const pages=ctx?await Promise.all(ctx.pages().map(p=>p.evaluate(()=>({route:location.pathname+location.hash,ready:document.readyState,login_fields:document.querySelectorAll('#email-address').length})).catch(()=>({unavailable:true})))):[];results.push({name:v.name,status:'FAIL',reason:safe(e.message),duration_ms:Date.now()-began,details,state:user?await info(user.id):null,trace,http,pageErrors,pages});console.log('FAIL '+v.name+': '+safe(e.message));}
  finally{releaseHeld?.();releaseOld?.();await Promise.allSettled(pendingBodies);await ctx?.close();save();}
 }
 try{for(let i=0;i<selected.length;i+=2){
  browser=await chromium.launch({headless:true,executablePath:process.env.ZEA_CHROMIUM_EXE,args:['--disable-background-networking','--no-first-run']});
  try{await Promise.all(selected.slice(i,i+2).map(run));}finally{await browser.close();browser=null;}
 }}finally{await browser?.close();save();process.exitCode=selected.length>0&&results.length===selected.length&&results.every(r=>r.status===(expectBootstrapFailure?'EXPECTED_REPRODUCTION':'PASS'))?0:1;}
})().catch(e=>{console.error(safe(e.message));process.exitCode=1});
