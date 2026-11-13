/* Independent browser audit: real credentials, idle server revocation, absolute expiry. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.ZEA_PLAYWRIGHT_MODULE);
const state = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const origin = state.origin, root = path.resolve(__dirname, '../..');
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/);
const containers = JSON.parse(execFileSync('docker', ['inspect', ...state.containers], {encoding:'utf8'}));
assert.equal(containers.length, 5);
assert(containers.every(c => c.Config.Labels['zea.phase15'] === state.run));
const frontend = containers.find(c => c.Name.endsWith('-frontend'));
assert.deepEqual(frontend.NetworkSettings.Ports['80/tcp'], [{HostIp:'127.0.0.1', HostPort:new URL(origin).port}]);
assert(containers.filter(c => c !== frontend).every(c => Object.keys(c.NetworkSettings.Ports || {}).every(k => !c.NetworkSettings.Ports[k])));
const evidence = path.join(state.evidence, 'independent-browser.json');
const results = [], blocked = new Set(), requests = [], pageErrors = [];
const claims = token => JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function redact(value) {
  return String(value).split(state.password).join('[REDACTED]').replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,'[REDACTED_TOKEN]');
}
async function raw(page, endpoint, method='GET', body, token) {
  assert(endpoint.startsWith('/') && !endpoint.startsWith('//'));
  return page.evaluate(async ({endpoint,method,body,token}) => {
    const r=await fetch('/api'+endpoint,{method,headers:{'Content-Type':'application/json',Authorization:'Bearer '+(token ?? localStorage.getItem('vee_access_token'))},body:body===undefined?undefined:JSON.stringify(body)});
    const t=await r.text();let data;try{data=JSON.parse(t)}catch{data=t}return {status:r.status,data};
  },{endpoint,method,body,token});
}
async function newUser(page, label) {
  await page.goto(origin+'/#/login');
  const owner=await raw(page,'/auth/login','POST',{email:'owner@phase15.example.com',password:state.password},'');
  assert.equal(owner.status,200);
  const email='audit-'+label+'-'+Date.now()+'@phase15.example.com';
  const created=await raw(page,'/users','POST',{name:'Synthetic audit '+label,email,password:state.password,role:'user',status:'ACTIVE',department_id:state.fixture.department},owner.data.token.access_token);
  assert.equal(created.status,201);
  await page.locator('#email-address').fill(email);await page.locator('#password').fill(state.password);
  const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/login' && r.request().method()==='POST');
  await page.locator('#password').press('Enter');assert.equal((await response).status(),200);
  await page.waitForURL(u=>!u.hash.includes('/login'));
  const tokens=await page.evaluate(()=>({access:localStorage.getItem('vee_access_token'),refresh:localStorage.getItem('vee_refresh_token')}));
  assert.equal(claims(tokens.access).sub,created.data.id);
  return {tokens,id:created.data.id};
}
async function idleSocket(ctx, credential) {
  const page=await ctx.newPage();await page.goto(origin+'/runtime-config.js');
  await page.addScriptTag({path:path.join(root,'frontend/node_modules/socket.io-client/dist/socket.io.js')});
  const connected=await page.evaluate(token=>new Promise(resolve=>{
    window.__auditSocket=null;window.__auditClosedAt=null;window.__auditReason=null;
    const socket=io(location.origin,{auth:{token},transports:['websocket'],reconnection:false,timeout:10000});
    window.__auditSocket=socket;
    socket.on('connect',()=>resolve(true));socket.on('connect_error',()=>resolve(false));
    socket.on('disconnect',reason=>{window.__auditClosedAt=Date.now();window.__auditReason=reason;});
  }),credential);
  return {page,connected};
}
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.ZEA_CHROMIUM_EXE,args:['--disable-background-networking','--no-first-run']});
  async function test(name,work) {
    const started=Date.now(),ctx=await browser.newContext({serviceWorkers:'block',viewport:{width:1440,height:1000}});
    await ctx.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin===origin || ['data:','blob:'].includes(u.protocol))return route.continue();blocked.add(u.hostname);return route.abort();});
    ctx.on('page',p=>{p.on('pageerror',e=>pageErrors.push(redact(e.message)));p.on('response',r=>{if(r.url().startsWith(origin+'/api/'))requests.push({path:new URL(r.url()).pathname,status:r.status()});});});
    try {const observations=await work(ctx);results.push({name,status:'PASS',duration_ms:Date.now()-started,observations});console.log('PASS '+name);}
    catch(e){const reason=redact(e.message).slice(0,600);results.push({name,status:'FAIL',duration_ms:Date.now()-started,reason});console.log('FAIL '+name+': '+reason);}
    finally{await ctx.close();}
  }
  try {
    await test('A01_idle_presence_server_revokes_without_React_or_client_requests',async ctx=>{
      const p=await ctx.newPage();const user=await newUser(p,'revocation');
      const issued=await raw(p,'/auth/presence-token');assert.equal(issued.status,200);
      const credential=issued.data.access_token;
      assert.equal((await raw(p,'/auth/me','GET',undefined,credential)).status,401,'Presence credential cannot authorize ordinary REST');
      const socket=await idleSocket(ctx,credential);assert(socket.connected);
      const start=Date.now();assert.equal((await raw(p,'/auth/logout','POST',{})).status,204);
      // No socket packets, React unmount, reload or disconnect command occurs.
      await socket.page.waitForFunction(()=>window.__auditClosedAt!==null,{},{timeout:20000});
      const observed=await socket.page.evaluate(()=>({at:window.__auditClosedAt,reason:window.__auditReason}));
      assert.equal(observed.reason,'io server disconnect');assert(observed.at-start<20000);
      assert.equal((await raw(p,'/auth/presence/validate','POST',{},credential)).status,401);
      const rejected=await idleSocket(ctx,credential);assert.equal(rejected.connected,false);
      return {server_disconnect_ms:observed.at-start,reason:observed.reason,revoked_presence_validate:401,revoked_reconnect:false};
    });
    await test('A02_absolute_session_expiry_updates_UI_and_expires_idle_presence',async ctx=>{
      const p=await ctx.newPage();const user=await newUser(p,'expiry');
      const issued=await raw(p,'/auth/presence-token');assert.equal(issued.status,200);
      const credential=issued.data.access_token, expiry=claims(credential).exp*1000;
      assert.equal(expiry,claims(user.tokens.refresh).exp*1000);
      const socket=await idleSocket(ctx,credential);assert(socket.connected);
      const start=Date.now();assert(expiry-start>60000,'Use actual test session lifetime, not a synthetic shortened token');
      console.log('WAIT actual two-minute absolute session/presence expiry; no synthetic clock or tokens');
      while(Date.now()<expiry+300)await sleep(Math.min(500,expiry+300-Date.now()));
      await socket.page.waitForFunction(()=>window.__auditClosedAt!==null,{},{timeout:5000});
      const observed=await socket.page.evaluate(()=>({at:window.__auditClosedAt,reason:window.__auditReason}));
      assert.equal(observed.reason,'io server disconnect');assert(observed.at>=expiry-250 && observed.at<expiry+3000);
      assert.equal((await raw(p,'/auth/me','GET',undefined,user.tokens.access)).status,401);
      assert.equal((await raw(p,'/auth/refresh','POST',{refresh_token:user.tokens.refresh})).status,401);
      assert.equal((await raw(p,'/auth/presence/validate','POST',{},credential)).status,401);
      // Reload invokes the real React auth provider/Axios interceptor. No tokens
      // are edited by this test; expiry must clear both and route to login.
      await p.reload();await p.waitForURL(u=>u.hash.includes('/login'));
      const saved=await p.evaluate(()=>({access:localStorage.getItem('vee_access_token'),refresh:localStorage.getItem('vee_refresh_token')}));
      assert.deepEqual(saved,{access:null,refresh:null});
      const rejected=await idleSocket(ctx,credential);assert.equal(rejected.connected,false);
      return {wait_ms:Date.now()-start,server_disconnect_offset_from_expiry_ms:observed.at-expiry,reason:observed.reason,expired_http:401,frontend_login:true,token_storage_cleared:true,expired_reconnect:false};
    });
  } finally {
    await browser.close();fs.writeFileSync(evidence,JSON.stringify({run:state.run,completed_at:new Date().toISOString(),kind:'real_browser_fullstack',results,http_responses:requests,blocked_external_hosts:[...blocked],page_errors:pageErrors,authentication:'Real UI login, actual password verifier, PostgreSQL sessions; no auth/clock mocks'},null,2));
    process.exitCode=results.length===2 && results.every(r=>r.status==='PASS')?0:1;
  }
})().catch(e=>{console.error(redact(e.message));process.exitCode=1;});
