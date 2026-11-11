// Run with the disposable backend/checks/serve_navigation_fixture.py at 6321
// and Vite at 6319. Auth, policy, and API administration use REAL local routes.
// Unrelated page data and all external services are isolated fixtures.
async function sidebarReadiness(page) {
  const origin = 'http://127.0.0.1:6319/';
  const backend = 'http://127.0.0.1:6321';
  const results = [], errors = [], requests = [];
  let nonce = Date.now();
  page.removeAllListeners('dialog'); page.removeAllListeners('pageerror');
  page.on('dialog', dialog => dialog.accept());
  page.on('pageerror', error => errors.push(String(error)));
  page.setDefaultTimeout(12000); page.setDefaultNavigationTimeout(25000);
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const check = async (name, fn) => {
    try { await fn(); results.push({name, status:'PASS'}); }
    catch(error) { results.push({name, status:'FAIL', error:String(error).slice(0,1000)}); }
  };
  const install = async target => {
    await target.unrouteAll({behavior:'wait'});
    await target.routeWebSocket('**/*', socket => socket.close());
    target.removeAllListeners('dialog');
    target.on('dialog', dialog => dialog.accept().catch(() => {}));
    await target.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.pathname.startsWith('/api/')) {
        const path = url.pathname.slice(4);
        if (/^\/(navigation|config|webhooks)(\/|$)/.test(path) || /^\/auth\/(login|logout|me|refresh)$/.test(path)) {
          const response = await route.fetch({url: backend + url.pathname + url.search});
          requests.push({path, method:request.method(), status:response.status()});
          return route.fulfill({response});
        }
        let json = [];
        if (path === '/updates/latest') json = {id:'fixture-notes',version_label:'Readiness fixture',content_mode:'text',details_text:'Isolated review'};
        if (path === '/auth/presence-token') json = {};
        return route.fulfill({json});
      }
      if (url.origin === new URL(origin).origin || ['cdn.tailwindcss.com','cdn.jsdelivr.net'].includes(url.hostname)) return route.continue();
      if (request.resourceType() === 'image') return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" />'});
      return route.fulfill({json:{}});
    });
  };
  const visit = (target,path) => target.goto(`${origin}?readiness=${++nonce}#${path}`, {waitUntil:'domcontentloaded'});
  const ready = target => target.getByRole('heading',{name:'Profile information',exact:true}).waitFor();
  const signIn = async (target,role,tenant='a') => {
    await visit(target,'/settings/profile');
    await target.getByRole('textbox',{name:'Email address',exact:true}).fill(`${role}-${tenant}@readiness.example.com`);
    await target.getByLabel('Password',{exact:true}).fill('readiness-fixture-password');
    await target.getByRole('button',{name:'Sign in',exact:true}).press('Enter');
    await ready(target);
  };
  const signOut = async target => {
    await target.getByRole('button',{name:/Readiness .* (owner|admin|manager|user)$/}).click();
    const response = target.waitForResponse(response => response.url().includes('/api/auth/logout'));
    await target.getByRole('button',{name:'Logout',exact:true}).click();
    await target.waitForURL(url=>url.hash==='#/login');
    assert((await response).status()===204,'logout request was not authenticated');
  };
  const adminPage = async () => {
    await visit(page,'/settings/sidebar-management');
    await page.getByRole('heading',{name:'Sidebar Management',exact:true}).waitFor();
    await page.getByRole('button',{name:'Settings Tabs',exact:true}).click();
  };
  const apiRow = () => page.locator('[data-page-id="settings.api"]');
  const save = async () => {
    await page.getByRole('button',{name:'Save Changes',exact:true}).click();
    await page.getByText(/Organization policy and personal layout saved/).waitFor();
  };
  const requestApi = (target,path) => target.evaluate(async path => {
    const response = await fetch('/api'+path,{headers:{Authorization:`Bearer ${localStorage.getItem('vee_access_token')}`}});
    const body = await response.text();
    return {status:response.status, hasSecret:body.includes('tenant-a-fixture-key') || body.includes('tenant-b-fixture-key')};
  },path);
  await install(page);
  // Clear only credentials/cache belonging to this isolated origin. Preferences
  // remain untouched across real logout/login, refresh and the new browser.
  await visit(page,'/login');
  await page.evaluate(()=>{localStorage.removeItem('vee_access_token');localStorage.removeItem('vee_refresh_token');Object.keys(localStorage).filter(key=>key.startsWith('zea-play-cache:')).forEach(key=>localStorage.removeItem(key));});
  await page.reload();
  await check('Owner enables protected Settings and saves API with exactly Owner/Admin visibility',async()=>{
    await signIn(page,'owner'); await adminPage();
    assert(await page.locator('[data-page-id="settings.profile"]').getByRole('switch').isDisabled(),'Profile not protected');
    await apiRow().locator('summary').click();
    assert(await apiRow().getByLabel('API: user',{exact:true}).isDisabled(),'User escalation enabled');
    assert(await apiRow().getByLabel('API: manager',{exact:true}).isDisabled(),'Manager escalation enabled');
    await apiRow().getByRole('switch').uncheck(); await save();
    await apiRow().getByRole('switch').check();
    await apiRow().getByLabel('API: owner',{exact:true}).check();
    await apiRow().getByLabel('API: admin',{exact:true}).check();
    await save();
    const policy = await page.evaluate(async()=> (await fetch('/api/navigation',{headers:{Authorization:`Bearer ${localStorage.getItem('vee_access_token')}`}})).json());
    assert(policy.pages.find(page=>page.id==='settings').enabled,'Settings disabled');
    assert(JSON.stringify(policy.pages.find(page=>page.id==='settings.api').allowedRoles.sort())===JSON.stringify(['admin','owner']),'wrong saved role policy');
    await signOut(page);
  });
  for (const role of ['owner','admin','manager','user']) {
    await check(`${role} real login observes API policy and independent endpoint authorization`,async()=>{
      await signIn(page,role);
      const allowed=['owner','admin'].includes(role);
      assert(await page.getByRole('tab',{name:'API',exact:true}).count()===(allowed?1:0),'incorrect API visibility');
      await visit(page,'/settings/api');
      if(allowed) await page.getByRole('heading',{name:'API & OAuth Management',exact:true}).waitFor();
      else {await ready(page);await page.getByRole('alert').filter({hasText:'does not have access'}).waitFor();}
      for(const path of ['/config/api','/config/smtp/multiple','/config/oauth']) {
        const response=await requestApi(page,path);
        assert(response.status===(allowed?200:403),'endpoint did not enforce role: '+path);
        if(!allowed)assert(!response.hasSecret,'member received a credential');
      }
      await signOut(page);
    });
  }
  await check('A fresh browser reads persisted global policy without inheriting personal storage',async()=>{
    const context=await page.context().browser().newContext();
    try {
      const fresh=await context.newPage();await install(fresh);await signIn(fresh,'admin');
      assert(await fresh.getByRole('tab',{name:'API',exact:true}).count()===1,'policy missing in new browser');
      assert(await fresh.evaluate(()=>Object.keys(localStorage).filter(key=>key.startsWith('zea.sidebar.v2:')).length)===0,'personal layout was copied between browsers');
    } finally {await context.close();}
  });
  await check('Owner disables API; every role loses navigation and direct configuration access',async()=>{
    await signIn(page,'owner');await adminPage();await apiRow().getByRole('switch').uncheck();await save();await signOut(page);
    for(const role of ['owner','admin','manager','user']) {
      await signIn(page,role);assert(await page.getByRole('tab',{name:'API',exact:true}).count()===0,'disabled API visible to '+role);
      await visit(page,'/settings/api');await ready(page);
      assert((await requestApi(page,'/config/api')).status===403,'disabled endpoint still accessible');await signOut(page);
    }
  });
  await check('Re-enabling API restores only Owner/Admin after refresh and login',async()=>{
    await signIn(page,'owner');await adminPage();await apiRow().getByRole('switch').check();await save();await page.reload();
    await page.getByRole('tab',{name:'API',exact:true}).waitFor();await signOut(page);
    for(const role of ['admin','manager','user']) {
      await signIn(page,role);assert(await page.getByRole('tab',{name:'API',exact:true}).count()===(role==='admin'?1:0),'re-enable broadened roles');await signOut(page);
    }
  });
  await check('Tenant B remains unchanged when Tenant A changes policy',async()=>{
    await signIn(page,'owner');await adminPage();await apiRow().getByRole('switch').uncheck();await save();await signOut(page);
    await signIn(page,'admin','b');assert(await page.getByRole('tab',{name:'API',exact:true}).count()===1,'Tenant A affected Tenant B');
    assert((await requestApi(page,'/config/api')).status===200,'Tenant B endpoint blocked');await signOut(page);
    await signIn(page,'owner');await adminPage();await apiRow().getByRole('switch').check();await save();await signOut(page);
  });
  await check('No uncaught errors during authenticated end-to-end scenario',async()=>assert(errors.length===0,errors.join('\n')));
  const summary={passed:results.filter(result=>result.status==='PASS').length,failed:results.filter(result=>result.status==='FAIL').length,results,errors,requests};
  await page.evaluate(value=>{window.__sidebarReadiness= value;},summary);
  return summary;
}
