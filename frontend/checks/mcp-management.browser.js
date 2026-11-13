// Browser-only UI fixture checks. Backend authority is tested separately.
// Invoke verifyMcpManagement(page, {registry, snapshot}) with the checked-in
// navigation registry and test/fixtures/mcp-management.json. No real credentials.
async function verifyMcpManagement(page, { registry, snapshot }) {
  const origin = 'http://127.0.0.1:6329';
  let role = 'owner', failed = false, disabled = false, wrongTenant = false, malformed = false, stalled = false;
  const requests = [], errors = [], results = [];
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const check = async (name, work) => {
    try { await work(); results.push({ name, status: 'PASS' }); }
    catch (error) { results.push({ name, status: 'FAIL', error: String(error), url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1500) }); }
  };
  page.on('pageerror', error => errors.push(String(error)));
  page.setDefaultTimeout(20000);
  await page.unrouteAll({ behavior: 'wait' });
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem('vee_access_token', 'phase3-ui-fixture-only');
    localStorage.setItem('zenith-task-theme', 'dark');
  });
  const policy = () => ({ tenantId: snapshot.tenant_context, version: 0, updatedBy: null, updatedAt: null,
    roles: ['user', 'manager', 'admin', 'owner'], canManage: ['owner', 'admin'].includes(role), canChangeAccess: role === 'owner',
    pages: registry.map(entry => {
      const allowed = entry.permittedRoles.includes(role);
      const denied = disabled && entry.id === 'settings.mcp-management';
      return { ...entry, enabled: !denied, hidden: false, allowedRoles: entry.permittedRoles,
        access: !allowed ? 'forbidden' : denied ? 'disabled' : 'allowed', visible: allowed && !denied };
    }) });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) {
      const path = url.pathname.slice(4);
      requests.push({ path, method: request.method() });
      let json = [];
      if (path === '/auth/me') json = { id: 'phase3-fixture-user', name: 'Phase 3 Tester', email: 'phase3@example.test', role, status: 'ACTIVE', points: 0 };
      else if (path === '/navigation') json = policy();
      else if (path === '/mcp-management') {
        if (stalled) {
          await new Promise(resolve => setTimeout(resolve, 11000));
          return route.abort().catch(() => {});
        }
        if (failed) return route.fulfill({ status: 503, json: { detail: 'Synthetic outage' } });
        json = { ...snapshot, tenant_context: wrongTenant ? 'b2222222-2222-4222-8222-222222222222' : snapshot.tenant_context };
        if (malformed) json = { ...json, tools: [...snapshot.tools, { ...snapshot.tools[0], id: 'zeaplay_delete_task', read_only: false }] };
      }
      else if (path === '/notifications/unread-count') json = { count: 0 };
      else if (path === '/auth/presence-token') return route.fulfill({ status: 403, json: { detail: 'Presence disabled in UI fixture' } });
      else if (path === '/updates/release-notes') json = { version_label: 'UI fixture', content_mode: 'text', details_text: '' };
      else if (path === '/admin/data/manager/catalog') json = { datasets: [], limitations: [], unregistered_tables: [] };
      return route.fulfill({ json });
    }
    if (url.origin === origin || ['cdn.tailwindcss.com', 'cdn.jsdelivr.net'].includes(url.hostname)) return route.continue();
    if (request.resourceType() === 'image' || /\.(png|svg|ico)$/.test(url.pathname)) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"/>' });
    return route.abort();
  });
  let visitNumber = 0;
  const visit = path => page.goto(origin + '/?phase3-check=' + (++visitNumber) + '#' + path, { waitUntil: 'domcontentloaded' });
  const ready = () => page.locator('#mcp-section-title').waitFor();
  const section = async name => {
    await page.getByRole('navigation', { name: 'MCP sections' }).getByRole('button', { name, exact: true }).click();
    await page.locator('#mcp-section-title').filter({ hasText: name }).waitFor();
  };
  await page.setViewportSize({ width: 1440, height: 1000 });
  await check('Owner deep link and eight Settings tabs', async () => {
    await visit('/settings/mcp-management'); await ready();
    assert(await page.getByRole('tab', { name: 'MCP Management', exact: true }).getAttribute('aria-selected') === 'true', 'MCP tab not selected');
    assert(await page.getByRole('tab').count() === 8, 'expected eight Settings tabs');
  });
  await check('Overview has unknown connection count and no live health claim', async () => {
    await page.getByText('No live health check has been performed.', { exact: false }).waitFor();
    assert(await page.locator('dt').filter({ hasText: 'Active connections' }).locator('..').innerText().then(text => text.includes('Unavailable')), 'connection count should be unavailable');
  });
  for (const name of ['Tools', 'Connections', 'Permissions', 'Security', 'Activity Logs']) {
    await check(name + ' section and disabled authority', async () => {
      await section(name);
      assert(await page.locator('#mcp-section input:enabled').count() === 0, 'unapproved controls enabled');
      if (name === 'Tools') assert(await page.locator('#mcp-section input[type=checkbox]').count() === 5, 'incorrect tool catalog');
      if (name === 'Connections') assert(await page.locator('#mcp-section button:disabled').count() === 5, 'client creation exposed');
      if (name === 'Activity Logs') assert(await page.locator('#mcp-section table').count() === 0, 'fabricated audit table');
    });
  }
  await check('DOM-edited tool control cannot submit policy', async () => {
    await section('Tools');
    const control = page.locator('#mcp-section input').first();
    await control.evaluate(input => { input.disabled = false; });
    await control.click();
    assert(!requests.some(r => r.path.startsWith('/mcp') && r.method !== 'GET'), 'client-side authority mutation submitted');
  });
  await check('Settings keyboard navigation reaches MCP without autoactivation', async () => {
    const api = page.getByRole('tab', { name: 'API', exact: true });
    await api.focus(); await page.keyboard.press('ArrowRight');
    assert(await page.getByRole('tab', { name: 'MCP Management', exact: true }).evaluate(el => el === document.activeElement), 'keyboard did not reach MCP');
    await page.keyboard.press('Enter'); await ready();
  });
  await check('Deep link survives reload', async () => { await page.reload(); await ready(); });
  for (const width of [320, 390, 768, 1440]) {
    await check('Responsive sections at ' + width, async () => {
      await page.setViewportSize({ width, height: 900 });
      for (const name of ['Overview', 'Tools', 'Connections', 'Permissions', 'Security', 'Activity Logs']) {
        await section(name);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'horizontal overflow in ' + name);
      }
    });
  }
  await check('API outage clears previous success and retry recovers', async () => {
    failed = true;
    await page.getByRole('button', { name: 'Reload status', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'MCP management is unavailable' }).waitFor();
    assert(await page.getByRole('navigation', { name: 'MCP sections' }).count() === 0, 'stale snapshot retained');
    failed = false; await page.getByRole('button', { name: 'Retry', exact: true }).click(); await ready();
  });
  await check('Wrong tenant response fails closed', async () => {
    wrongTenant = true; await page.getByRole('button', { name: 'Reload status', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'MCP management is unavailable' }).waitFor();
    wrongTenant = false; await page.getByRole('button', { name: 'Retry', exact: true }).click(); await ready();
  });
  await check('Unapproved write tool in malformed response fails closed', async () => {
    malformed = true; await page.getByRole('button', { name: 'Reload status', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'MCP management is unavailable' }).waitFor();
    assert(await page.getByRole('navigation', { name: 'MCP sections' }).count() === 0, 'malformed catalog was rendered');
    malformed = false; await page.getByRole('button', { name: 'Retry', exact: true }).click(); await ready();
  });
  await check('Stalled read times out and permits retry', async () => {
    stalled = true; await page.getByRole('button', { name: 'Reload status', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'MCP management is unavailable' }).waitFor();
    stalled = false; await page.getByRole('button', { name: 'Retry', exact: true }).click(); await ready();
  });
  await check('Admin can open MCP management', async () => { role = 'admin'; await visit('/settings/mcp-management'); await ready(); });
  for (const denied of ['user', 'manager']) {
    await check(denied + ' cannot navigate directly or see MCP tab', async () => {
      role = denied; await visit('/settings/mcp-management');
      await page.waitForURL(url => url.hash === '#/settings/profile', { waitUntil: 'domcontentloaded' });
      await page.getByRole('heading', { name: 'Profile information', exact: true }).waitFor();
      assert(await page.getByRole('tab', { name: 'MCP Management', exact: true }).count() === 0, 'MCP tab visible');
    });
  }
  await check('Tenant navigation disable blocks direct route', async () => {
    role = 'owner'; disabled = true; await visit('/settings/mcp-management');
    await page.waitForURL(url => url.hash === '#/settings/profile', { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: 'Profile information', exact: true }).waitFor();
    assert(await page.getByRole('tab', { name: 'MCP Management', exact: true }).count() === 0, 'disabled tab visible');
    disabled = false;
  });
  await check('No MCP mutations or console exceptions', async () => {
    assert(!requests.some(r => r.path.startsWith('/mcp') && r.method !== 'GET'), 'MCP mutation attempted');
    assert(errors.length === 0, errors.join('; '));
  });
  role = 'owner'; disabled = false;
  await check('Final Owner overview', async () => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await visit('/settings/mcp-management'); await ready();
  });
  return { results, errors, requests: requests.filter(r => r.path.startsWith('/mcp')), note: 'API-intercepted browser fixtures; not real-auth or production proof' };
}
