/* Real Chromium + current React build + real HTTP/PG/Redis/presence. No auth mocks. */
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');
const state = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const { chromium } = require(process.env.ZEA_PLAYWRIGHT_MODULE);
const root = path.resolve(__dirname, '../..');
const evidenceDir = state.evidence || path.join(root, 'backend/checks');
const evidence = path.join(evidenceDir, 'browser'+(process.env.ZEA_PHASE15_EVIDENCE_SUFFIX || '')+'.json');
const origin = state.origin;
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/);
assert.equal(execFileSync('docker', ['inspect', '--format', '{{index .Config.Labels "zea.phase15"}}', state.backend], {encoding:'utf8'}).trim(), state.run);
const results = [], requests = [], blocked = new Set(), errors = [];
const safe = value => String(value).replaceAll(state.password, '[REDACTED]').replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,'[REDACTED_TOKEN]');
const mode = process.argv.includes('--smoke') ? 'smoke' : process.env.ZEA_PHASE15_FILTER ? 'filtered' : 'full';
let suiteCompleted = false;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const claims = token => JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
function control(action, values = {}) {
  const output = execFileSync('docker', ['exec', state.backend, 'python', '-B', '/tests/mcp_phase1_5_backend.py', action, JSON.stringify(values)], {encoding:'utf8', timeout:15000, windowsHide:true});
  return JSON.parse(output.trim().split('\n').at(-1));
}
async function eventually(work, timeout=20000, label='the stated integration condition') {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) { if(await work()) return; await sleep(350); }
  throw new Error('Timed out waiting for '+label);
}
async function tokens(page) {
  return page.evaluate(() => ({access:localStorage.getItem('vee_access_token'), refresh:localStorage.getItem('vee_refresh_token')}));
}
async function raw(page, endpoint, method='GET', body, token) {
  assert(endpoint.startsWith('/') && !endpoint.startsWith('//'));
  return page.evaluate(async ({endpoint,method,body,token}) => {
    const response=await fetch('/api'+endpoint,{method,headers:{'Content-Type':'application/json',
      Authorization:'Bearer '+(token ?? localStorage.getItem('vee_access_token'))},body:body===undefined?undefined:JSON.stringify(body)});
    const text=await response.text();let data;try{data=JSON.parse(text)}catch{data=text}
    return {status:response.status,data};
  }, {endpoint,method,body,token});
}
async function apiLogin(page,user,password=state.password) {
  const response=await raw(page,'/auth/login','POST',{email:user+'@phase15.example.com',password},'');
  assert.equal(response.status,200,'Real API fixture login');
  return response.data.token;
}
async function login(page,user='life',password=state.password) {
  await page.goto(origin+'/#/login');
  await page.locator('#email-address').fill(user+'@phase15.example.com');
  await page.locator('#password').fill(password);
  const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/login' && r.request().method()==='POST');
  await page.locator('#password').press('Enter');
  assert.equal((await response).status(),200,'UI password login succeeds');
  // Login first navigates to '/', whose index route then redirects to the
  // role's landing page. Do not let that pending redirect overwrite the next
  // test navigation (notably Users, where the real presence hook is mounted).
  await page.waitForURL(url=>url.hash && url.hash!=='#/' && url.hash!=='#' && !url.hash.includes('/login'));
  await page.waitForFunction(()=>!!localStorage.getItem('vee_access_token'));
  assert.equal(claims((await tokens(page)).access).sub,state.fixture.users[user]);
}
async function logout(page,user) {
  // Desktop profile menu is the actual application logout action.
  const button=page.getByRole('button').filter({hasText:'Fixture '+user}).first();
  await button.click();
  const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/logout');
  await page.getByRole('button',{name:'Logout',exact:true}).first().click();
  assert.equal((await response).status(),204);
  await page.waitForURL(url=>url.hash.includes('/login'));
  assert.equal((await tokens(page)).access,null);
}

(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.ZEA_CHROMIUM_EXE,
    args:['--disable-background-networking','--no-first-run']});
  async function context() {
    const ctx=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
    if (process.env.ZEA_PHASE15_AUTH_TRACE === '1') await ctx.addInitScript(() => {
      window.__authTrace=[];
      for (const method of ['setItem','removeItem']) {
        const original=Storage.prototype[method];
        Storage.prototype[method]=function(key,...args) {
          if (key==='vee_access_token' || key==='vee_refresh_token') window.__authTrace.push({
            method,key,at:Date.now(),stack:new Error().stack.split('\n').slice(1,6).join('\n')});
          return original.call(this,key,...args);
        };
      }
    });
    await ctx.route('**/*', route=> {
      const url=new URL(route.request().url());
      if(url.origin===origin || ['data:','blob:'].includes(url.protocol)) return route.continue();
      blocked.add(url.hostname);return route.abort();
    });
    ctx.on('page', page=>{
      page.on('pageerror',e=>errors.push(safe(e.message).slice(0,180)));
      page.on('response',r=>{if(r.url().startsWith(origin+'/api/')) requests.push({path:new URL(r.url()).pathname,status:r.status(),at:Date.now(),page:ctx.pages().indexOf(page)});});
    });
    return ctx;
  }
  async function test(name, work) {
    if(process.env.ZEA_PHASE15_FILTER && !new RegExp(process.env.ZEA_PHASE15_FILTER).test(name)) return;
    const started=Date.now(), ctx=await context();
    try { await work(ctx); results.push({name,status:'PASS',duration_ms:Date.now()-started});console.log('PASS '+name); }
    catch(e) { const diagnostic = name.startsWith('B02') ? {
        pages: await Promise.all(ctx.pages().map(p=>p.evaluate(async()=>{
          const metadata=token=>{try{const c=JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));return {sid:c.sid,exp:c.exp};}catch{return null;}};
          return {route:location.pathname+location.hash,access:metadata(localStorage.getItem('vee_access_token')),refresh:metadata(localStorage.getItem('vee_refresh_token')),
            refresh_attempt_present:!!localStorage.getItem('vee_refresh_attempt'),trace:window.__authTrace,locks:navigator.locks ? await navigator.locks.query() : null};
        }).catch(()=>({unavailable:true})))), sessions:control('sessions',{user:'renew'})
      } : undefined;
      results.push({name,status:'FAIL',reason:safe(e.message).slice(0,400),duration_ms:Date.now()-started,diagnostic}); console.log('FAIL '+name+': '+safe(e.message).slice(0,250));
      const page=ctx.pages()[0];if(page) await page.screenshot({path:path.join(evidenceDir,'phase15-'+name.replace(/[^a-z0-9]/gi,'-')+'.png')}).catch(()=>{});
    } finally {await ctx.close();fs.writeFileSync(evidence,JSON.stringify({results,blocked_external_hosts:[...blocked],page_errors:errors,request_count:requests.length},null,2));}
  }
  try {
    await test('B01_UI_login_reload_logout_and_durable_session',async ctx=>{
      const p=await ctx.newPage();await login(p);
      const before=await tokens(p), sid=claims(before.access).sid;
      assert.equal((await raw(p,'/auth/me')).status,200);
      await p.reload();await p.waitForFunction(()=>!!localStorage.getItem('vee_access_token'));
      assert.equal((await raw(p,'/auth/me')).status,200);
      assert(control('sessions').sessions.some(s=>s.id===sid && !s.revoked));
      await logout(p,'life');
      assert.equal((await raw(p,'/auth/me','GET',undefined,before.access)).status,401);
      assert.equal((await raw(p,'/auth/refresh','POST',{refresh_token:before.refresh})).status,401);
      assert(control('sessions').sessions.find(s=>s.id===sid).revoked);
    });
    if(process.argv.includes('--smoke')) { suiteCompleted = true; return; }

    await test('B02_natural_expiry_multitab_rotation_and_presence_renewal',async ctx=>{
      const p=await ctx.newPage();await p.goto(origin+'/#/login');
      const fixtureOwner=await apiLogin(p,'owner');
      assert.equal((await raw(p,'/users/'+state.fixture.users.renew,'PATCH',{role:'user'},fixtureOwner.access_token)).status,200);
      assert.equal((await raw(p,'/users/'+state.fixture.users.renew,'PATCH',{role:'manager'},fixtureOwner.access_token)).status,200);
      await login(p,'renew');await p.goto(origin+'/#/admin/users');
      const q=await ctx.newPage();await q.goto(origin+'/#/admin/users');
      await q.waitForFunction(()=>!!localStorage.getItem('vee_access_token'));
      assert(await p.evaluate(()=>!!navigator.locks),'Native Web Locks available');
      const before=await tokens(p), sid=claims(before.access).sid, initial=claims(before.access);
      await eventually(()=>control('presence',{user:'renew'}).sockets>=2);
      // Phase 2A.1: delay a real retried /auth/me request, never its credentials
      // or response. This models latency after another tab has stored rotation.
      const retryDelay=Number(process.env.ZEA_PHASE15_B02_RETRY_DELAY_MS || 0);
      assert(Number.isInteger(retryDelay) && retryDelay>=0 && retryDelay<=10000);
      if(retryDelay) {
        let reads=0;
        await q.route(origin+'/api/auth/me',async route=>{
          if(++reads===2) await sleep(retryDelay);
          await route.continue().catch(()=>{}); // The real XHR may have timed out.
        });
      }
      const holder=await ctx.newPage();await holder.goto(origin+'/runtime-config.js');
      await holder.evaluate(()=>{
        window.__phase15Holding=false;
        navigator.locks.request('zeaplay-session-refresh',()=>new Promise(resolve=>{
          window.__phase15Release=resolve;window.__phase15Holding=true;
        }));
      });
      await holder.waitForFunction(()=>window.__phase15Holding);
      const refreshStart=requests.filter(r=>r.path==='/api/auth/refresh' && r.status===200).length;
      const reloadWaiter=process.env.ZEA_PHASE15_B02_RELOAD_WAITER === '1';
      if(reloadWaiter) await ctx.route(origin+'/api/auth/refresh',async route=>{
        await sleep(750);await route.continue(); // Delay delivery only; real backend rotation.
      });
      const started=Date.now();console.log('WAIT real access expiration and refresh; no browser clock or token mocks');
      while(Date.now()<initial.exp*1000+1200) await sleep(500);
      assert.equal((await raw(p,'/auth/me','GET',undefined,before.access)).status,401);
      await Promise.all([p.reload(),q.reload()]);
      await eventually(()=>holder.evaluate(async()=>(await navigator.locks.query()).pending.filter(x=>x.name==='zeaplay-session-refresh').length>=2));
      console.log('OBSERVED two native Web Lock waiters before releasing simultaneous refresh');
      const post=reloadWaiter ? ctx.waitForEvent('request',{predicate:r=>new URL(r.url()).pathname==='/api/auth/refresh' && r.method()==='POST'}) : null;
      await holder.evaluate(()=>window.__phase15Release());
      if(post) {
        const issuer=(await post).frame().page();
        assert(issuer===p || issuer===q);
        await (issuer===p ? q : p).reload();
        console.log('OBSERVED non-issuing tab reload during delayed real refresh delivery');
      }
      await eventually(async()=>{const pair=await tokens(p);return pair.access && pair.access!==before.access;},20000,'B02 stored successor');
      await eventually(async()=>!p.url().includes('/login') && !q.url().includes('/login'),20000,'B02 both authenticated routes');
      const after=await tokens(p);
      assert(after.refresh!==before.refresh,'Actual refresh rotated');
      assert.equal((await tokens(q)).refresh,after.refresh,'Both native tabs share successor');
      const persisted=control('sessions',{user:'renew'}).sessions.find(s=>s.id===sid);
      assert.equal(persisted.refresh_count,2);assert.equal(persisted.consumed_count,1);assert(!persisted.revoked);
      assert.equal(requests.filter(r=>r.path==='/api/auth/refresh' && r.status===200).length-refreshStart,1,'Exactly one real refresh POST');
      assert.equal((await raw(p,'/auth/me')).status,200);
      await eventually(()=>control('presence',{user:'renew'}).sockets>=2,20000,'B02 two restored presence sockets');
      const renewalStart=requests.filter(r=>r.path==='/api/auth/presence-token' && r.status===200).length;
      // Two-minute real session lifetime caps the unchanged one-hour presence
      // issuer. The actual React renewal timer runs at expiry minus 30 seconds.
      console.log('WAIT real presence renewal timer against live backend/Redis');
      await eventually(()=>requests.filter(r=>r.path==='/api/auth/presence-token' && r.status===200).length>renewalStart,45000);
      assert(control('presence',{user:'renew'}).redis_ping);
      assert(Date.now()-started>25000);
      await logout(p,'renew');
      await q.reload();await q.waitForURL(u=>u.hash.includes('/login'));
      await eventually(()=>control('presence',{user:'renew'}).sockets===0);
    });

    await test('B03_refresh_replay_revokes_successor',async ctx=>{
      const p=await ctx.newPage();await login(p);
      const original=await tokens(p), sid=claims(original.access).sid;
      const rotated=await raw(p,'/auth/refresh','POST',{refresh_token:original.refresh});assert.equal(rotated.status,200);
      assert.equal((await raw(p,'/auth/refresh','POST',{refresh_token:original.refresh})).status,401);
      assert.equal((await raw(p,'/auth/me','GET',undefined,rotated.data.access_token)).status,401);
      assert(control('sessions').sessions.find(s=>s.id===sid).revoked);
      await p.reload();await p.waitForURL(u=>u.hash.includes('/login'));
    });

    await test('B04_deactivation_reactivation_requires_new_login',async ctx=>{
      const p=await ctx.newPage();await login(p);const before=await tokens(p);
      const owner=await apiLogin(p,'owner');
      assert.equal((await raw(p,'/users/'+state.fixture.users.life,'PATCH',{status:'DEACTIVATED'},owner.access_token)).status,200);
      await p.reload();await p.waitForURL(u=>u.hash.includes('/login'));
      assert.equal((await raw(p,'/auth/login','POST',{email:'life@phase15.example.com',password:state.password},'')).status,403);
      assert.equal((await raw(p,'/users/'+state.fixture.users.life,'PATCH',{status:'ACTIVE'},owner.access_token)).status,200);
      assert.equal((await raw(p,'/auth/me','GET',undefined,before.access)).status,401);
      assert.equal((await raw(p,'/auth/refresh','POST',{refresh_token:before.refresh})).status,401);
      await login(p);assert.equal((await raw(p,'/auth/me')).status,200);
    });

    await test('B05_tenant_A_B_A_old_credentials_never_return',async ctx=>{
      const p=await ctx.newPage();await login(p);const a=await tokens(p), epoch=control('sessions').epoch;
      assert(control('tenant',{tenant:'tenant-b'}).committed);
      await p.reload();await p.waitForURL(u=>u.hash.includes('/login'));
      await login(p);const b=await tokens(p);assert.equal(claims(b.access).tenant_id,state.fixture.foreign);
      assert.equal((await raw(p,'/tasks/assigned')).status,404);
      control('tenant',{tenant:'tenant-a'});
      await p.reload();await p.waitForURL(u=>u.hash.includes('/login'));
      for(const pair of [a,b]) {
        assert.equal((await raw(p,'/auth/me','GET',undefined,pair.access)).status,401);
        assert.equal((await raw(p,'/auth/refresh','POST',{refresh_token:pair.refresh})).status,401);
      }
      assert.equal(control('sessions').epoch,epoch+2);
      await login(p);assert.equal(claims((await tokens(p)).access).tenant_id,state.fixture.tenant);
    });

    await test('B06_UI_password_change_and_admin_reset',async ctx=>{
      const p=await ctx.newPage();await login(p);const before=await tokens(p), replacement=state.password+'Z9';
      await p.goto(origin+'/#/settings/profile');
      await p.locator('#profile-field-5').fill(state.password);
      await p.locator('#profile-field-6').fill(replacement);
      await p.locator('#profile-field-7').fill(replacement);
      const changed=p.waitForResponse(r=>new URL(r.url()).pathname==='/api/users/me/change-password');
      await p.getByRole('button',{name:'Update password',exact:true}).click();
      assert.equal((await changed).status(),204);
      assert.equal((await raw(p,'/auth/me','GET',undefined,before.access)).status,401);
      await p.reload();await p.waitForURL(u=>u.hash.includes('/login'));
      await login(p,'life',replacement);const changedPair=await tokens(p);
      const owner=await apiLogin(p,'owner');
      assert.equal((await raw(p,'/users/'+state.fixture.users.life+'/reset-password','POST',{new_password:state.password},owner.access_token)).status,204);
      await p.reload();await p.waitForURL(u=>u.hash.includes('/login'));
      assert.equal((await raw(p,'/auth/refresh','POST',{refresh_token:changedPair.refresh})).status,401);
      await login(p);assert.equal((await raw(p,'/auth/me')).status,200);
    });

    await test('B07_live_presence_revocation_disconnect_and_reauthentication',async ctx=>{
      const p=await ctx.newPage();let connected=0, closed=0;
      p.on('websocket',ws=>{if(ws.url().includes('/socket.io/')){ws.on('framereceived',f=>{if(String(f.payload).startsWith('40')) connected++;});ws.on('close',()=>closed++);}});
      await login(p,'manager');await p.goto(origin+'/#/admin/users');const before=await tokens(p), sid=claims(before.access).sid;
      await eventually(()=>connected>0 && control('presence',{user:'manager'}).sockets>0);
      const admin=await apiLogin(p,'owner'), start=Date.now();
      assert.equal((await raw(p,'/users/'+state.fixture.users.manager,'PATCH',{status:'DEACTIVATED'},admin.access_token)).status,200);
      await eventually(()=>closed>0 && control('presence',{user:'manager'}).sockets===0,20000);
      assert(Date.now()-start<20000,'Live authority disconnect bounded to 20 seconds including measurement overhead');
      assert(control('sessions',{user:'manager'}).epoch>control('sessions',{user:'manager'}).sessions.find(s=>s.id===sid).epoch);
      assert.equal((await raw(p,'/users/'+state.fixture.users.manager,'PATCH',{status:'ACTIVE'},admin.access_token)).status,200);
      assert.equal((await raw(p,'/auth/me','GET',undefined,before.access)).status,401);
      const oldCount=connected;await p.reload();await login(p,'manager');await p.goto(origin+'/#/admin/users');
      await eventually(()=>connected>oldCount && control('presence',{user:'manager'}).sockets>0);
    });

    await test('B08_logout_propagates_to_an_idle_second_tab',async ctx=>{
      const p=await ctx.newPage();await login(p);
      const q=await ctx.newPage();await q.goto(origin+'/#/tasks');
      await q.waitForFunction(()=>!!localStorage.getItem('vee_access_token'));
      await q.waitForTimeout(1500);
      await logout(p,'life');
      assert.equal((await tokens(q)).access,null,'Shared token storage cleared');
      // Do not reload or manually issue a request: observe the real idle UI.
      await q.waitForURL(u=>u.hash.includes('/login'),{timeout:10000});
    });

    await test('B09_parallel_HTTP_refresh_has_one_winner_and_revokes_reuse',async ctx=>{
      const p=await ctx.newPage();await login(p);const pair=await tokens(p),sid=claims(pair.access).sid;
      const responses=await Promise.all([raw(p,'/auth/refresh','POST',{refresh_token:pair.refresh}),
        raw(p,'/auth/refresh','POST',{refresh_token:pair.refresh})]);
      assert.deepEqual(responses.map(r=>r.status).sort(),[200,401]);
      assert(control('sessions').sessions.find(s=>s.id===sid).revoked);
      const winner=responses.find(r=>r.status===200);
      assert.equal((await raw(p,'/auth/me','GET',undefined,winner.data.access_token)).status,401);
    });

    await test('B10_backend_task_websocket_idle_revocation_and_reconnect',async ctx=>{
      const p=await ctx.newPage();await login(p);const pair=await tokens(p);
      // Use a second page without React so an application unmount cannot be
      // mistaken for the server's independent idle heartbeat revocation.
      const q=await ctx.newPage();await q.goto(origin+'/runtime-config.js');
      async function open(token) {
        return q.evaluate(token=>new Promise(resolve=>{
          window.__socketClosed=null;
          const socket=new WebSocket(location.origin.replace('http:','ws:')+'/ws/tasks?token='+encodeURIComponent(token));
          window.__phase15Socket=socket;
          socket.onopen=()=>resolve(true);
          socket.onerror=()=>resolve(false);
          socket.onclose=e=>{window.__socketClosed=e.code;resolve(false);};
        }),token);
      }
      assert(await open(pair.access));
      const started=Date.now();
      assert.equal((await raw(p,'/auth/logout','POST',{})).status,204);
      await q.waitForFunction(()=>window.__socketClosed!==null,{},{timeout:30000});
      assert.equal(await q.evaluate(()=>window.__socketClosed),1008);
      console.log('Task WebSocket idle server revocation observed within '+(Date.now()-started)+' ms');
      assert.equal(await open(pair.access),false,'Revoked handshake denied');
      await p.reload();await p.waitForURL(u=>u.hash.includes('/login'));
      await login(p);assert(await open((await tokens(p)).access));
      await q.evaluate(()=>window.__phase15Socket.close());
    });

    await test('B11_role_change_revokes_session_and_requires_fresh_login',async ctx=>{
      const p=await ctx.newPage();await p.goto(origin+'/#/login');const owner=await apiLogin(p,'owner');
      const endpoint='/users/'+state.fixture.users.manager;
      assert.equal((await raw(p,endpoint,'PATCH',{role:'manager',department_id:state.fixture.department},owner.access_token)).status,200);
      await login(p,'manager');const before=await tokens(p), epoch=control('sessions',{user:'manager'}).epoch;
      assert.equal((await raw(p,endpoint,'PATCH',{role:'user'},owner.access_token)).status,200);
      assert.equal((await raw(p,'/auth/me','GET',undefined,before.access)).status,401);
      assert.equal((await raw(p,'/auth/refresh','POST',{refresh_token:before.refresh})).status,401);
      assert.equal(control('sessions',{user:'manager'}).epoch,epoch+1);
      await p.reload();await p.waitForURL(u=>u.hash.includes('/login'));
      await login(p,'manager');assert.equal((await raw(p,'/tasks/sibling')).status,403);
      assert.equal((await raw(p,endpoint,'PATCH',{role:'manager'},owner.access_token)).status,200);
    });

    await test('R01_cross_tenant_group_ticket_transfer_audit_notice_cache_observer',async ctx=>{
      const p=await ctx.newPage();await login(p,'member');
      const member=await tokens(p), owner=await apiLogin(p,'owner'), foreign=await apiLogin(p,'foreign'),
        peer=await apiLogin(p,'peer'), watcher=await apiLogin(p,'watcher');
      assert.equal((await raw(p,'/tasks/assigned','PATCH',{assigned_to_id:state.fixture.users.member},owner.access_token)).status,200);
      for(const prefix of ['', '/api']) {
        assert.equal((await raw(p,prefix+'/tasks/assigned','GET',undefined,member.access)).status,200);
        assert([403,404].includes((await raw(p,prefix+'/tasks/sibling','GET',undefined,member.access)).status));
        assert.equal((await raw(p,prefix+'/tasks/assigned','GET',undefined,foreign.access_token)).status,404);
        const group=await raw(p,prefix+'/tasks/assigned/group');assert.equal(group.status,200);
        assert(!JSON.stringify(group.data).includes('Synthetic sibling'));
        const creators=await raw(p,prefix+'/tasks/assigned/group','GET',undefined,owner.access_token);
        assert(JSON.stringify(creators.data).includes('Synthetic sibling'));
        for(const sub of ['logs','tasks']) {
          assert.equal((await raw(p,prefix+'/tickets/'+state.fixture.ticket+'/'+sub)).status,200);
          assert([403,404].includes((await raw(p,prefix+'/tickets/'+state.fixture.ticket+'/'+sub,'GET',undefined,peer.access_token)).status));
          assert.equal((await raw(p,prefix+'/tickets/'+state.fixture.foreign_ticket+'/'+sub)).status,404);
        }
        assert.equal((await raw(p,prefix+'/tasks/assigned','PATCH',{description:'denied'},watcher.access_token)).status,403);
        assert([400,403,404].includes((await raw(p,prefix+'/tasks/assigned/transfer-requests','POST',{to_user_id:state.fixture.users.foreign},owner.access_token)).status));
        assert([400,403,404].includes((await raw(p,prefix+'/tickets','POST',{title:'Denied',description:'Synthetic',owner_id:state.fixture.users.foreign})).status));
        const audits=await raw(p,prefix+'/logs/audit?action=PHASE15_FIXTURE','GET',undefined,owner.access_token);assert.equal(audits.status,200);
        assert(JSON.stringify(audits.data).includes('audit-a'));
        assert(!JSON.stringify(audits.data).includes('audit-b'));
        const foreignAudits=await raw(p,prefix+'/logs/audit?action=PHASE15_FIXTURE','GET',undefined,foreign.access_token);
        assert.equal(foreignAudits.status,200);assert(JSON.stringify(foreignAudits.data).includes('audit-b'));
        assert(!JSON.stringify(foreignAudits.data).includes('audit-a'));
        const notices=await raw(p,prefix+'/notifications/inbox');assert.equal(notices.status,200);assert(!JSON.stringify(notices.data).includes('notice-foreign'));
      }
      const ticket='/tickets/'+state.fixture.ticket;
      assert.equal((await raw(p,ticket+'/participants','POST',{add:[{user_id:state.fixture.users.peer,role:'FOLLOWER'}]})).status,200);
      assert.equal((await raw(p,'/tickets','GET',undefined,peer.access_token)).data.data.length,1);
      assert.equal((await raw(p,ticket+'/participants','POST',{remove:[{user_id:state.fixture.users.peer,role:'FOLLOWER'}]})).status,200);
      assert.equal((await raw(p,'/tickets','GET',undefined,peer.access_token)).data.data.length,0);
      const request=await raw(p,'/tasks/assigned/transfer-requests','POST',{to_user_id:state.fixture.users.watcher});assert.equal(request.status,200);
      assert([403,404].includes((await raw(p,'/tasks/transfer-requests/'+request.data.id+'/approve','POST',{decision:'approved'},peer.access_token)).status));
      assert.equal((await raw(p,'/tasks/transfer-requests/'+request.data.id+'/approve','POST',{decision:'approved'},owner.access_token)).status,200);
      assert.equal((await raw(p,'/tasks/sibling','GET',undefined,owner.access_token)).data.assigned_to_id,state.fixture.users.peer);
      const deptsA=await raw(p,'/departments','GET',undefined,owner.access_token),deptsB=await raw(p,'/departments','GET',undefined,foreign.access_token);
      assert.deepEqual(deptsA.data,deptsB.data);
      console.log('DEPARTMENT BLOCKER CONFIRMED: both tenants see the same global catalog');
    });

    await test('D01_shared_department_CRUD_diagnostic_not_tenant_isolation_PASS',async ctx=>{
      const p=await ctx.newPage();await login(p,'owner');const foreign=await apiLogin(p,'foreign');
      const name='Synthetic department '+Date.now();
      const created=await raw(p,'/departments','POST',{name});assert.equal(created.status,201);
      assert.equal((await raw(p,'/departments','POST',{name},foreign.access_token)).status,400);
      const id=created.data.id;
      const foreignNotices=await raw(p,'/notifications/inbox','GET',undefined,foreign.access_token);
      assert.equal(foreignNotices.status,200);
      assert(!JSON.stringify(foreignNotices.data).includes(id),'Existing dispatcher suppresses cross-tenant department notices');
      const linked=[];
      for(const [suffix,token] of [['a',undefined],['b',foreign.access_token]]) {
        const user=await raw(p,'/users','POST',{name:'Synthetic department member '+suffix,
          email:'department-'+Date.now()+suffix+'@phase15.example.com',password:state.password,
          role:'user',status:'ACTIVE',department_id:id},token);
        assert.equal(user.status,201);linked.push([user.data.id,token]);
      }
      const ticket=await raw(p,'/tickets','POST',{title:'Synthetic department-linked ticket',description:'Synthetic only',department_id:id});
      assert.equal(ticket.status,201);assert.equal(ticket.data.department_id,id);
      assert.equal((await raw(p,'/departments/'+id,'PATCH',{name:name+' renamed by B'},foreign.access_token)).status,200);
      assert((await raw(p,'/departments')).data.some(d=>d.id===id && d.name.endsWith('renamed by B')));
      assert.equal((await raw(p,'/departments/'+id,'DELETE',undefined,foreign.access_token)).status,204);
      assert(!(await raw(p,'/departments')).data.some(d=>d.id===id));
      for(const [userId,token] of linked) assert.equal((await raw(p,'/users/'+userId,'GET',undefined,token)).data.department_id,null);
      const retained=await raw(p,'/tickets/'+ticket.data.id);
      assert.equal(retained.status,200);assert.equal(retained.data.department_id,id,'Ticket has no FK: deleted department ID remains');
      console.log('S04 BLOCKED: tenant B can rename/delete a department created by tenant A; ownership decision required');
    });

    await test('R02_department_permission_changes_revoke_cached_authority',async ctx=>{
      const p=await ctx.newPage();await login(p,'owner');
      assert.equal((await raw(p,'/users/'+state.fixture.users.manager,'PATCH',{department_id:state.fixture.department})).status,200);
      const manager=await apiLogin(p,'manager'),epoch=control('sessions',{user:'manager'}).epoch;
      assert.equal((await raw(p,'/tasks/assigned','GET',undefined,manager.access_token)).status,200);
      assert.equal((await raw(p,'/tasks/foreign-task','GET',undefined,manager.access_token)).status,404);
      assert.equal((await raw(p,'/tickets/'+state.fixture.foreign_ticket,'GET',undefined,manager.access_token)).status,404);
      assert.equal((await raw(p,'/users/'+state.fixture.users.manager,'PATCH',{department_id:null})).status,200);
      // Department membership is live object authority, not an epoch-triggering
      // identity field. Assert denial with the SAME still-valid login session.
      assert.equal((await raw(p,'/auth/me','GET',undefined,manager.access_token)).status,200);
      assert.equal((await raw(p,'/tasks/assigned','GET',undefined,manager.access_token)).status,403);
      assert.equal((await raw(p,'/tickets','GET',undefined,manager.access_token)).data.data.length,0);
      assert.equal(control('sessions',{user:'manager'}).epoch,epoch);
      assert.equal((await raw(p,'/users/'+state.fixture.users.manager,'PATCH',{department_id:state.fixture.department})).status,200);
      assert.equal((await raw(p,'/tasks/assigned','GET',undefined,manager.access_token)).status,200);
    });
    suiteCompleted = true;
  } finally {
    await browser.close();
    const executionComplete = suiteCompleted && results.length > 0;
    const fullSuite = executionComplete && mode === 'full' && results.length === 14;
    fs.writeFileSync(evidence,JSON.stringify({run:state.run,completed_at:new Date().toISOString(),filter:process.env.ZEA_PHASE15_FILTER || null,
      mode,execution_complete:executionComplete,full_suite:fullSuite,
      b02_retry_delay_ms:Number(process.env.ZEA_PHASE15_B02_RETRY_DELAY_MS || 0),b02_reload_waiter:process.env.ZEA_PHASE15_B02_RELOAD_WAITER === '1',
      results,blocked_external_hosts:[...blocked],page_errors:errors,
      request_count:requests.length,http_responses:requests,
      browser:'Chromium real headless; native Web Locks; no mocked auth/clock/token issuance'},null,2));
    console.log('RESULT '+JSON.stringify({pass:results.filter(r=>r.status==='PASS').length,fail:results.filter(r=>r.status==='FAIL').length}));
    if (!executionComplete || (mode === 'full' && !fullSuite)) {
      console.log('INCOMPLETE: no tests matched or the requested suite did not finish');
      process.exitCode = 2;
    } else process.exitCode=results.some(r=>r.status==='FAIL')?1:0;
  }
})().catch(e=>{console.error(safe(e.message));process.exitCode=1;});
