// UI fixtures only. The HTTP/PG OAuth proof is exercise_oauth.py.
async function verifyMcpOAuthUI(page, { registry, snapshot }) {
  const origin = 'http://127.0.0.1:6329';
  let current = structuredClone(snapshot), rejected = false, unavailable = false, role = 'owner';
  const results = [], requests = [], errors = [];
  const id = 'a1111111-1111-4111-8111-111111111111';
  const csrf = 'a'.repeat(43);
  const check = async (name, fn) => { try { await fn(); results.push({ name, status:'PASS' }); }
    catch (e) { results.push({name,status:'FAIL',error:String(e)}); } };
  const assert = (value, message) => { if (!value) throw new Error(message); };
  page.on('pageerror', e => errors.push(String(e)));
  page.setDefaultTimeout(10000);
  await page.addInitScript(() => { localStorage.clear(); localStorage.setItem('vee_access_token','phase4-ui-fixture'); localStorage.setItem('zenith-task-theme','dark'); });
  await page.route('**/*', async route => {
    const req=route.request(), url=new URL(req.url());
    if (url.pathname === '/__mcp_ui_frame') return route.fulfill({contentType:'text/html',body:`<iframe title="Embedded consent" src="${origin}/#/mcp/consent?request=${id}"></iframe>`});
    if (url.pathname === '/__mcp_ui_callback') return route.fulfill({contentType:'text/html',body:'<h1>Isolated UI callback fixture</h1>'});
    if (url.pathname.startsWith('/api/')) {
      const path=url.pathname.slice(4), method=req.method();
      if (path.startsWith('/mcp')) requests.push({path,method,body:method==='GET'?undefined:req.postDataJSON()});
      let json=[];
      if (path === '/auth/me') json={id:'phase4-fixture-user',name:'Phase 4 Tester',email:'phase4@example.test',role,status:'ACTIVE',points:0};
      else if (path === '/navigation') json={tenantId:current.tenant_context,version:0,updatedAt:null,updatedBy:null,roles:['user','manager','admin','owner'],canManage:role==='owner',canChangeAccess:role==='owner',pages:registry.map(p=>({...p,enabled:true,hidden:false,allowedRoles:p.permittedRoles,access:p.permittedRoles.includes(role)?'allowed':'forbidden',visible:p.permittedRoles.includes(role)}))};
      else if (path === '/mcp-management') json=current;
      else if (path === '/mcp-management/policy') {
        if (rejected) return route.fulfill({status:409,json:{detail:'Fixture revision conflict'}});
        const value=req.postDataJSON(); Object.assign(current.configuration,{enabled:value.enabled,allowed_tool_ids:value.allowed_tool_ids,allowed_roles:value.allowed_roles,revision:current.configuration.revision+1});
        current.tools.forEach(t=>{t.enabled=value.allowed_tool_ids.includes(t.id);t.available=value.enabled&&t.enabled;});
        current.overview.enabled_tools=current.tools.filter(t=>t.available).length;
        json={saved:true,revision:current.configuration.revision,remote_access_enabled:false};
      }
      else if (path === '/mcp-management/emergency-disable') {
        Object.assign(current.configuration,{enabled:false,emergency_disabled:true,revision:current.configuration.revision+1});
        Object.assign(current.overview,{enabled_tools:0,active_connections:0});current.tools.forEach(t=>{t.available=false;});json={emergency_disabled:true};
      }
      else if (/\/mcp-oauth\/grants\/.+\/revoke/.test(path)) {
        const grant=current.connections.items.find(x=>path.includes(x.id));if(grant){grant.status='revoked';grant.revoked_at=new Date().toISOString();}json={revoked:true};
      }
      else if (path.endsWith('/preview')) {
        if (unavailable) return route.fulfill({status:503,json:{detail:'Fixture unavailable'}});
        json={request_id:id,client_name:'Isolated fixture client',tenant_context:current.tenant_context,scopes:['tasks:read'],tools:current.tools.slice(0,4).map(t=>t.id),expires_at:'2026-11-13T23:59:59+00:00',csrf};
      }
      else if (path.endsWith('/decision')) json={redirect_uri:origin+'/__mcp_ui_callback?code=ui-fixture-only'};
      else if (path === '/notifications/unread-count') json={count:0};
      else if (path === '/auth/presence-token') return route.fulfill({status:403,json:{detail:'Fixture presence disabled'}});
      else if (path === '/updates/release-notes') json={version_label:'UI fixture',content_mode:'text',details_text:''};
      return route.fulfill({json});
    }
    if(url.origin===origin || ['cdn.tailwindcss.com','cdn.jsdelivr.net'].includes(url.hostname)) return route.continue();
    return route.abort();
  });
  let visit=0;
  const go=path=>page.goto(origin+'/?phase4-ui='+(++visit)+'#'+path,{waitUntil:'domcontentloaded'});
  const ready=()=>page.locator('#mcp-section-title').waitFor();
  const section=async name=>{await page.getByRole('navigation',{name:'MCP sections'}).getByRole('button',{name,exact:true}).click();};
  await check('isolated backend state and production warning',async()=>{await go('/settings/mcp-management');await ready();await page.getByText('Configured for isolated OAuth only',{exact:true}).waitFor();assert((await page.locator('body').innerText()).includes('External production integrations'),'missing warning');});
  for (const width of [320,390,768,1440]) await check('isolated six sections fit '+width,async()=>{
    await page.setViewportSize({width,height:900});
    for(const name of ['Overview','Tools','Connections','Permissions','Security','Activity Logs']) {await section(name);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'overflow '+name);}
  });
  await check('external client creation remains disabled beside genuine grants',async()=>{await section('Connections');assert(await page.getByRole('button',{name:/^Connect .*unavailable$/}).count()===5,'external creation exposed');assert(await page.getByRole('button',{name:'Revoke grant',exact:true}).count()>0,'no genuine grants');});
  await check('tool draft saves only approved policy after confirmation',async()=>{
    await section('Tools');await page.getByLabel('Enable List tasks',{exact:true}).uncheck();await section('Permissions');
    await page.getByLabel('Reason for policy change').fill('UI isolated verification');await page.getByRole('button',{name:'Save isolated policy',exact:true}).click();await ready();await section('Tools');
    assert(!await page.getByLabel('Enable List tasks',{exact:true}).isChecked(),'saved tool remained enabled');
    const request=requests.find(x=>x.path==='/mcp-management/policy');assert(request.body.read_only===true&&request.body.expected_revision>=1&&!('tenant_id'in request.body),'unsafe request');
  });
  await check('server rejection is visible and never claims save success',async()=>{
    rejected=true;await section('Permissions');await page.getByLabel('Reason for policy change').fill('Rejected fixture');await page.getByRole('button',{name:'Save isolated policy',exact:true}).click();await page.getByRole('alert').filter({hasText:'Change was not confirmed'}).waitFor();rejected=false;
    page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Reload status',exact:true}).click();await ready();
  });
  await check('revoke grant request and saved status',async()=>{await section('Connections');const button=page.getByRole('button',{name:'Revoke grant',exact:true}).filter({visible:true});
    const enabled=page.locator('#mcp-section button').filter({hasText:'Revoke grant'}).and(page.locator('button:enabled')).first();await enabled.click();await ready();assert(requests.some(x=>x.path.endsWith('/revoke')),'no revoke submitted');});
  await check('emergency locks policy controls after server confirmation',async()=>{await section('Permissions');await page.getByRole('button',{name:'Emergency disable tenant MCP',exact:true}).click();await ready();await section('Permissions');assert(await page.getByLabel('Enable tenant MCP',{exact:true}).isDisabled(),'policy editable after emergency');await page.getByText('Emergency lock is active',{exact:false}).waitFor();});
  role='user';
  await check('embedded consent cannot load or approve authorization',async()=>{
    const before=requests.filter(x=>x.path.endsWith('/preview')||x.path.endsWith('/decision')).length;
    await page.goto(origin+'/__mcp_ui_frame',{waitUntil:'domcontentloaded'});
    const frame=page.frameLocator('iframe');
    await frame.getByRole('heading',{name:'Authorize isolated MCP access'}).waitFor();
    await frame.getByRole('alert').filter({hasText:'Consent cannot be approved in an embedded page.'}).waitFor();
    assert(await frame.getByRole('button',{name:'Approve read-only access',exact:true}).count()===0,'consent can be clickjacked inside a frame');
    assert(requests.filter(x=>x.path.endsWith('/preview')||x.path.endsWith('/decision')).length===before,'embedded consent called authorization API');
  });
  for(const approve of [false,true]) await check('ordinary user explicit consent '+(approve?'approve':'deny'),async()=>{
    await go('/mcp/consent?request='+id);await page.getByText('Isolated fixture client',{exact:true}).waitFor();
    assert(await page.getByRole('heading',{name:'Authorize isolated MCP access'}).count()===1,'consent page missing');
    await page.getByRole('button',{name:approve?'Approve read-only access':'Deny',exact:true}).click();await page.getByRole('heading',{name:'Isolated UI callback fixture'}).waitFor();
    const sent=requests.filter(x=>x.path.endsWith('/decision')).at(-1).body;assert(sent.approve===approve&&sent.csrf===csrf&&Object.keys(sent).length===2,'unsafe consent body');
    assert(await page.evaluate(()=>!Object.values(localStorage).some(v=>/mcp_(at|rt|dt)\./.test(v))),'OAuth tokens stored');
  });
  await check('unavailable consent fails closed',async()=>{unavailable=true;await go('/mcp/consent?request='+id);await page.getByRole('alert').filter({hasText:'Consent request is unavailable'}).waitFor();assert(await page.getByRole('button',{name:'Approve read-only access'}).count()===0,'approval enabled after error');});
  await check('no uncaught browser exceptions',async()=>assert(errors.length===0,errors.join(';')));
  return {results,errors,note:'UI API fixtures only; actual OAuth proof is the separate PG/HTTP run'};
}
