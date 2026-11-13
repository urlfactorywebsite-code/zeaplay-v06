// Run with Playwright's browser_run_code_unsafe filename tool against the local
// Vite server at 127.0.0.1:6319. Every API and support request is intercepted.
async function verifySettingsNavigation(page) {
  const origin = 'http://127.0.0.1:6319/';
  const results = [];
  const requests = [];
  const pageErrors = [];
  let acceptDialogs = true;
  const dialogs = [];
  const onDialog = async (dialog) => {
    dialogs.push(dialog.type());
    if (acceptDialogs) await dialog.accept(); else await dialog.dismiss();
  };
  page.removeAllListeners('dialog');
  page.removeAllListeners('pageerror');
  page.on('dialog', onDialog);
  let role = 'owner';
  // Safe metadata fixture generated from backend.app.navigation_registry.PAGES.
  const registry = [
  {
    "id": "dashboard",
    "defaultLabel": "Dashboard",
    "route": "/dashboard",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": null,
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": true,
    "mobile": true,
    "icon": "dashboard"
  },
  {
    "id": "tasks",
    "defaultLabel": "All Tasks",
    "route": "/tasks",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": null,
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": true,
    "mobile": true,
    "icon": "tasks"
  },
  {
    "id": "tasks.list",
    "defaultLabel": "All Tasks",
    "route": "/tasks",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": "tasks",
    "isSystemProtected": true,
    "navigationLocation": "task-tab",
    "desktop": true,
    "mobile": true,
    "icon": "tasks"
  },
  {
    "id": "kanban",
    "defaultLabel": "Kanban Board",
    "route": "/tasks/kanban",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": "tasks",
    "isSystemProtected": false,
    "navigationLocation": "task-tab",
    "desktop": true,
    "mobile": true,
    "icon": "kanban"
  },
  {
    "id": "gantt",
    "defaultLabel": "Gantt Chart",
    "route": "/tasks/gantt",
    "permittedRoles": [
      "manager",
      "admin",
      "owner"
    ],
    "parentId": "tasks",
    "isSystemProtected": false,
    "navigationLocation": "task-tab",
    "desktop": true,
    "mobile": true,
    "icon": "gantt"
  },
  {
    "id": "calendar",
    "defaultLabel": "Calendar",
    "route": "/tasks/calendar",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": "tasks",
    "isSystemProtected": false,
    "navigationLocation": "task-tab",
    "desktop": true,
    "mobile": true,
    "icon": "calendar"
  },
  {
    "id": "tickets",
    "defaultLabel": "Ticket",
    "route": "/tickets",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": null,
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": true,
    "mobile": true,
    "icon": "tickets"
  },
  {
    "id": "tool-library",
    "defaultLabel": "Tool Library",
    "route": "/tool-library",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": null,
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": true,
    "mobile": true,
    "icon": "tool-library"
  },
  {
    "id": "users",
    "defaultLabel": "Users",
    "route": "/admin/users",
    "permittedRoles": [
      "manager",
      "admin",
      "owner"
    ],
    "parentId": null,
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": true,
    "mobile": true,
    "icon": "users"
  },
  {
    "id": "reports",
    "defaultLabel": "Reports",
    "route": "/reports",
    "permittedRoles": [
      "manager",
      "admin",
      "owner"
    ],
    "parentId": null,
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": true,
    "mobile": true,
    "icon": "reports"
  },
  {
    "id": "achievements",
    "defaultLabel": "Achievements",
    "route": "/achievements",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": null,
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": true,
    "mobile": true,
    "icon": "achievements"
  },
  {
    "id": "settings",
    "defaultLabel": "Settings",
    "route": "/settings",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": null,
    "isSystemProtected": true,
    "navigationLocation": "sidebar",
    "desktop": true,
    "mobile": true,
    "icon": "settings"
  },
  {
    "id": "points",
    "defaultLabel": "Points",
    "route": "/admin/points-table",
    "permittedRoles": [
      "owner"
    ],
    "parentId": "achievements",
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": false,
    "mobile": true,
    "icon": "points"
  },
  {
    "id": "templates",
    "defaultLabel": "Templates",
    "route": "/template-editor",
    "permittedRoles": [
      "owner"
    ],
    "parentId": "achievements",
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": false,
    "mobile": true,
    "icon": "templates"
  },
  {
    "id": "levels",
    "defaultLabel": "Levels",
    "route": "/levels",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": "achievements",
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": false,
    "mobile": true,
    "icon": "levels"
  },
  {
    "id": "chat",
    "defaultLabel": "Chat",
    "route": "/chat",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": null,
    "isSystemProtected": false,
    "navigationLocation": "sidebar",
    "desktop": false,
    "mobile": false,
    "icon": "chat"
  },
  {
    "id": "settings.profile",
    "defaultLabel": "General / Profile",
    "route": "/settings/profile",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": "settings",
    "isSystemProtected": true,
    "navigationLocation": "settings-tab",
    "desktop": true,
    "mobile": true,
    "icon": "settings.profile"
  },
  {
    "id": "settings.support",
    "defaultLabel": "Support",
    "route": "/settings/support",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": "settings",
    "isSystemProtected": false,
    "navigationLocation": "settings-tab",
    "desktop": true,
    "mobile": true,
    "icon": "settings.support"
  },
  {
    "id": "settings.master-control",
    "defaultLabel": "Master Control",
    "route": "/settings/master-control",
    "permittedRoles": [
      "owner"
    ],
    "parentId": "settings",
    "isSystemProtected": false,
    "navigationLocation": "settings-tab",
    "desktop": true,
    "mobile": true,
    "icon": "settings.master-control"
  },
  {
    "id": "settings.api",
    "defaultLabel": "API",
    "route": "/settings/api",
    "permittedRoles": [
      "owner",
      "admin"
    ],
    "parentId": "settings",
    "isSystemProtected": false,
    "navigationLocation": "settings-tab",
    "desktop": true,
    "mobile": true,
    "icon": "settings.api"
  },
  {
    "id": "settings.logs",
    "defaultLabel": "Logs",
    "route": "/settings/logs",
    "permittedRoles": [
      "manager",
      "admin",
      "owner"
    ],
    "parentId": "settings",
    "isSystemProtected": false,
    "navigationLocation": "settings-tab",
    "desktop": true,
    "mobile": true,
    "icon": "settings.logs"
  },
  {
    "id": "settings.media-library",
    "defaultLabel": "Media Library",
    "route": "/settings/media-library",
    "permittedRoles": [
      "user",
      "admin",
      "manager",
      "owner"
    ],
    "parentId": "settings",
    "isSystemProtected": false,
    "navigationLocation": "settings-tab",
    "desktop": true,
    "mobile": true,
    "icon": "settings.media-library"
  },
  {
    "id": "settings.sidebar-management",
    "defaultLabel": "Sidebar Management",
    "route": "/settings/sidebar-management",
    "permittedRoles": [
      "owner",
      "admin"
    ],
    "parentId": "settings",
    "isSystemProtected": true,
    "navigationLocation": "settings-tab",
    "desktop": true,
    "mobile": true,
    "icon": "settings.sidebar-management"
  }
];
  registry.splice(registry.findIndex(page => page.id === 'settings.api') + 1, 0, {
    id: 'settings.mcp-management', defaultLabel: 'MCP Management', route: '/settings/mcp-management',
    permittedRoles: ['owner', 'admin'], parentId: 'settings', isSystemProtected: false,
    navigationLocation: 'settings-tab', desktop: true, mobile: true, icon: 'settings.mcp-management',
  });
  let policyVersion = 0;
  let policyUnavailable = false;
  let policyRules = Object.fromEntries(registry.map(p => [p.id, { enabled: true, hidden: false, allowedRoles: p.permittedRoles }]));
  const policyResponse = () => {
    const access = id => {
      const p = registry.find(p => p.id === id), rule = policyRules[id];
      if (!p.permittedRoles.includes(role) || !rule.allowedRoles.includes(role)) return 'forbidden';
      if (!rule.enabled) return 'disabled';
      return p.parentId ? access(p.parentId) : 'allowed';
    };
    return { tenantId: 'tenant-fixture', version: policyVersion, updatedBy: policyVersion ? 'settings-fixture' : null,
      updatedAt: policyVersion ? '2026-10-29T00:00:00Z' : null, roles: ['user', 'admin', 'manager', 'owner'],
      canManage: ['admin', 'owner'].includes(role), canChangeAccess: role === 'owner',
      pages: registry.map(p => ({ ...p, ...policyRules[p.id], access: access(p.id), visible: access(p.id) === 'allowed' && !policyRules[p.id].hidden && !(p.parentId && policyRules[p.parentId].hidden) })) };
  };
  let nonce = 100;
  let mediaError = false;
  let signedOut = false;
  const user = () => ({ id: 'settings-fixture', name: 'Navigation Tester', email: 'nav@example.test', role, status: 'active', points: 0 });
  const flags = [{ key: 'tasks.labels', label: 'Task Labels', group: 'Pages', description: 'Fixture task flag', enabled: true }];
  let smtpConfigs = [];
  let oauthConfigs = [];
  const image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZfQAAAAASUVORK5CYII=';
  const file = { id: 'fixture-media', original_filename: 'fixture.png', content_type: 'image/png', size_bytes: 32, created_at: '2026-10-29T00:00:00Z', read_url: image };
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const check = async (name, fn) => {
    try { await fn(); results.push({ name, status: 'PASS' }); }
    catch (error) { results.push({ name, status: 'FAIL', error: String(error).slice(0, 600), url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1600) }); }
  };
  const onError = (error) => pageErrors.push(String(error));
  page.on('pageerror', onError);
  page.setDefaultTimeout(7000);
  page.setDefaultNavigationTimeout(25000);
  await page.unrouteAll({ behavior: 'wait' });
  await page.addInitScript(() => {
    // Clear only this isolated browser origin's response cache between cases.
    // Otherwise an earlier fixture can hide the requests being tested.
    Object.keys(localStorage).filter((key) => key.startsWith('zea-play-cache:')).forEach((key) => localStorage.removeItem(key));
    localStorage.setItem('vee_access_token', 'settings-navigation-fixture');
    localStorage.setItem('zenith-task-theme', 'dark');
    history.replaceState({ ...history.state, usr: { settingsTest: 'preserved' } }, '');
  });
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.includes('/api/')) {
      const path = url.pathname.slice(url.pathname.indexOf('/api/') + 4);
      requests.push({ path, method: request.method(), query: url.search, body: request.postData(), authenticated: Boolean(request.headers().authorization) });
      let body = [];
      if (path === '/auth/me') {
        if (signedOut) return route.fulfill({ status: 401, json: { detail: 'Not authenticated' } });
        body = user();
      }
      else if (path === '/navigation') {
        if (policyUnavailable) return route.fulfill({ status: 503, json: { detail: 'Fixture navigation unavailable' } });
        if (request.method() === 'PUT') {
          const update = request.postDataJSON();
          if (update.version !== policyVersion) return route.fulfill({ status: 409, json: { detail: 'Navigation changed in another session. Discard and reload before saving.' } });
          policyRules = update.pages; policyVersion++;
        }
        body = policyResponse();
      }
      else if (path === '/users/me' && request.method() === 'PATCH') body = { ...user(), ...request.postDataJSON() };
      else if (path === '/users/me/avatar') body = { ...user(), avatar_asset_id: 'fixture-avatar', avatar_url: image };
      else if (path === '/avatars/policy') body = { maxBytes: 5 * 1024 * 1024, contentTypes: ['image/jpeg', 'image/png', 'image/webp'] };
      else if (path === '/users') body = [user()];
      else if (path === '/updates/latest') body = { id: 'notes', version_label: 'Fixture version', content_mode: 'text', details_text: 'Fixture release notes' };
      else if (path === '/feature-flags') {
        if (request.method() === 'PUT') Object.assign(flags[0], request.postDataJSON().flags[0]);
        body = flags;
      }
      else if (path === '/config/smtp/multiple') {
        if (request.method() === 'POST') smtpConfigs.push({ ...request.postDataJSON(), id: 'smtp-fixture', password: 'fixture-smtp-secret' });
        body = request.method() === 'GET' ? smtpConfigs : smtpConfigs[smtpConfigs.length - 1];
      }
      else if (path.startsWith('/config/smtp/multiple/')) {
        if (path.endsWith('/test')) body = { status: 'sent' };
        else if (request.method() === 'PATCH') { Object.assign(smtpConfigs[0], request.postDataJSON()); body = smtpConfigs[0]; }
        else if (request.method() === 'DELETE') { smtpConfigs = []; body = {}; }
      }
      else if (path === '/config/oauth') {
        if (request.method() === 'POST') oauthConfigs.push({ ...request.postDataJSON(), id: 'oauth-fixture', client_id: 'fixture-client-id', client_secret: 'fixture-oauth-secret', api_key: 'fixture-oauth-key' });
        body = request.method() === 'GET' ? oauthConfigs : oauthConfigs[oauthConfigs.length - 1];
      }
      else if (path.startsWith('/config/oauth/')) {
        if (path.endsWith('/rotate')) { oauthConfigs[0].client_secret = 'fixture-rotated-secret'; body = oauthConfigs[0]; }
        else if (request.method() === 'PATCH') { Object.assign(oauthConfigs[0], request.postDataJSON()); body = oauthConfigs[0]; }
        else if (request.method() === 'DELETE') { oauthConfigs = []; body = {}; }
      }
      else if (path === '/logs/retention') body = { id: 'retention', retention_days: 90 };
      else if (path === '/logs/audit') body = { items: [], total: 0, page: 1, page_size: 50, total_pages: 1 };
      else if (path === '/media/list') {
        if (mediaError) return route.fulfill({ status: 503, json: { detail: 'Fixture media unavailable' } });
        body = { items: url.searchParams.get('search') ? [] : [file], total: url.searchParams.get('search') ? 0 : 1, page: 1, page_size: 24 };
      }
      else if (path === '/media/external/connect') body = { provider: request.postDataJSON().provider, status: 'connected' };
      else if (path === '/media/presign') body = { upload_url: origin + 'settings-fixture-upload', bucket: 'fixture', object_key: 'fixture.png', file_id: file.id, expires_in: 300 };
      else if (path === '/media/confirm') body = { file_id: file.id, status: 'ready' };
      else if (path === '/media/avatar/finalize') body = { profile_image_key: file.id, profile_image_url: image };
      else if (path === '/auth/generate-token') body = { access_token: 'fixture-generated-token', token: 'fixture-generated-token', label: 'Fixture key', subject: 'settings-fixture', scopes: ['tasks.read'] };
      else if (path === '/ai/message') body = { reply: 'Fixture AI reply' };
      else if (path === '/ai/generate') body = { text: 'Fixture AI generation' };
      else if (path === '/support') body = { status: 'submitted' };
      else if (path === '/config/api') body = { provider: 'Google Gemini', api_key: 'fixture-server-ai-key' };
      else if (path === '/auth/presence-token') body = {};
      return route.fulfill({ json: body });
    }
    if (url.pathname === '/webhook/task-support') {
      requests.push({ path: '/webhook/task-support', method: request.method(), body: request.postData() });
      return route.fulfill({ json: { ok: true } });
    }
    if (url.pathname === '/settings-fixture-upload') {
      requests.push({ path: '/settings-fixture-upload', method: request.method() });
      return route.fulfill({ status: 200, body: '' });
    }
    // Permit the local app and its existing styles. Images use harmless fixtures.
    if (url.origin === new URL(origin).origin || url.hostname === 'cdn.tailwindcss.com' || url.hostname === 'cdn.jsdelivr.net') return route.continue();
    if (request.resourceType() === 'image') return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" />' });
    return route.fulfill({ json: {} });
  });
  const visit = async (path) => page.goto(`${origin}?settings-check=${++nonce}#${path}`, { waitUntil: 'domcontentloaded' });
  const selected = async (key) => page.waitForFunction((id) => document.getElementById(`settings-tab-${id}`)?.getAttribute('aria-selected') === 'true', key);
  const markers = { profile: 'Profile information', support: 'Submit Support Request', 'master-control': 'Feature Gatekeeper', api: 'API & OAuth Management', logs: 'Audit Logs', 'media-library': 'Media Library', 'sidebar-management': 'Sidebar Management' };
  const labels = { profile: 'General / Profile', support: 'Support', 'master-control': 'Master Control', api: 'API', logs: 'Logs', 'media-library': 'Media Library', 'sidebar-management': 'Sidebar Management' };
  const ready = async (key) => {
    await selected(key);
    await page.getByRole('tabpanel').getByRole('heading', { name: markers[key], exact: true }).waitFor();
  };
  await page.setViewportSize({ width: 1440, height: 1000 });
  await check('Settings default opens existing Profile', async () => {
    await visit('/settings?from=bookmark#profile-anchor');
    await ready('profile');
    assert(page.url().endsWith('#/settings/profile?from=bookmark#profile-anchor'), 'default URL lost query or anchor');
  });
  await check('One sidebar Settings entry, no former entries or dropdown', async () => {
    assert(await page.locator('.sidebar-shell a[href="#/settings"]').count() === 1, 'Settings missing or duplicated');
    assert(await page.locator('.sidebar-shell a').filter({ hasText: /^(Support|Master Control|API|Logs|Media Library|Profile)$/ }).count() === 0, 'old sidebar entries remain');
    assert(await page.getByRole('button', { name: 'Open sidebar menu', exact: true }).count() === 0, 'dropup remains');
  });
  await check('Unvisited Settings modules do not fetch data', async () => {
    assert(!requests.some((r) => ['/feature-flags', '/logs/audit', '/media/list', '/media/external/connect', '/webhooks'].includes(r.path)), 'unvisited tab fetched data');
  });
  await page.locator('.sidebar-shell').evaluate((el) => { el.dataset.settingsTest = 'same-layout'; });
  for (const key of Object.keys(markers)) {
    await check(`${labels[key]} tab navigation and sidebar highlight`, async () => {
      await page.getByRole('tab', { name: labels[key], exact: true }).click();
      await ready(key);
      assert(page.url().endsWith(`/settings/${key}`), 'incorrect tab route');
      assert(await page.locator('.sidebar-shell a[href="#/settings"]').getAttribute('aria-current') === 'page', 'Settings sidebar inactive');
    });
  }
  await check('Back and forward preserve selected tab', async () => {
    await page.goBack(); await ready('media-library');
    await page.goForward(); await ready('sidebar-management');
  });
  await check('Changing Settings tabs preserves the surrounding application layout', async () => {
    assert(await page.locator('.sidebar-shell').getAttribute('data-settings-test') === 'same-layout', 'layout remounted');
  });
  for (const key of Object.keys(markers)) {
    await check(`${labels[key]} direct deep link and refresh`, async () => {
      await visit(`/settings/${key}`); await ready(key);
      await page.reload(); await ready(key);
    });
  }
  for (const [from, target] of Object.entries({ '/profile': 'profile', '/support': 'support', '/master-control': 'master-control', '/api/overview': 'api', '/logs': 'logs', '/media': 'media-library' })) {
    await check(`Legacy ${from} preserves query, anchor and state`, async () => {
      await visit(`${from}?range=week#detail`); await ready(target);
      assert(page.url().endsWith(`/settings/${target}?range=week#detail`), 'redirect lost location');
      assert(await page.evaluate(() => history.state.usr?.settingsTest) === 'preserved', 'redirect lost state');
    });
  }
  await check('Keyboard arrow, Home, End, Space and Enter navigation', async () => {
    await visit('/settings/profile'); await ready('profile');
    const profile = page.getByRole('tab', { name: labels.profile, exact: true });
    await profile.focus(); await page.keyboard.press('ArrowRight');
    assert(await page.getByRole('tab', { name: labels.support, exact: true }).evaluate((el) => el === document.activeElement), 'ArrowRight did not move focus');
    assert(page.url().endsWith('/settings/profile'), 'focus movement loaded another page');
    await page.keyboard.press('Space'); await ready('support');
    await page.keyboard.press('End'); await page.keyboard.press('Enter'); await ready('sidebar-management');
    await page.keyboard.press('Home'); await page.keyboard.press('Enter'); await ready('profile');
    await page.keyboard.press('ArrowLeft');
    assert(await page.getByRole('tab', { name: labels['sidebar-management'], exact: true }).evaluate((el) => el === document.activeElement), 'ArrowLeft did not wrap');
  });
  await check('Unsaved profile edits survive cancelled tab navigation', async () => {
    await visit('/settings/profile'); await ready('profile');
    await page.getByRole('tabpanel').locator('input').first().fill('Unsaved profile draft');
    acceptDialogs = false;
    await page.getByRole('tab', { name: 'Support', exact: true }).click();
    await page.waitForTimeout(100);
    assert(page.url().endsWith('/settings/profile'), 'dirty profile was discarded');
    assert(await page.getByRole('tabpanel').locator('input').first().inputValue() === 'Unsaved profile draft', 'draft was reset');
    assert(await page.evaluate(() => { const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented; }), 'reload/close warning missing');
    acceptDialogs = true;
    await page.getByRole('tab', { name: 'Support', exact: true }).click(); await ready('support');
  });
  await check('Unsaved Support drafts survive cancelled browser Back and sidebar navigation', async () => {
    await page.locator('#subject').fill('Keep this draft');
    await page.waitForFunction(() => { const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented; });
    acceptDialogs = false;
    await page.evaluate(() => history.back()); await page.waitForTimeout(200);
    assert(page.url().endsWith('/settings/support'), 'Back discarded draft');
    await page.locator('.sidebar-shell').getByRole('link', { name: 'All Tasks', exact: true }).click();
    await page.waitForTimeout(100);
    assert(await page.locator('#subject').inputValue() === 'Keep this draft', 'sidebar discarded draft');
    acceptDialogs = true;
    await page.getByRole('button', { name: 'Reset form', exact: true }).click();
    await page.getByRole('tab', { name: 'General / Profile', exact: true }).click(); await ready('profile');
  });
  await check('Collapsed sidebar Settings has an accessible name and active state', async () => {
    await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click();
    const link = page.locator('.sidebar-shell').getByRole('link', { name: 'Settings', exact: true });
    assert(await link.getAttribute('title') === 'Settings', 'missing collapsed tooltip');
    await link.click(); await ready('profile');
    assert(await link.getAttribute('aria-current') === 'page', 'collapsed Settings inactive');
    await page.getByRole('button', { name: 'Expand sidebar', exact: true }).click();
  });
  await check('Existing profile save keeps its API contract', async () => {
    await page.getByRole('tabpanel').locator('input').first().fill('Updated Fixture Name');
    await page.getByRole('button', { name: 'Save profile', exact: true }).click();
    await page.getByText('Profile information updated successfully.', { exact: true }).waitFor();
    assert(requests.some((r) => r.path === '/users/me' && r.method === 'PATCH' && JSON.parse(r.body).name === 'Updated Fixture Name'), 'profile PATCH missing');
  });
  await check('Existing password mismatch validation blocks API calls', async () => {
    const inputs = page.getByRole('tabpanel').locator('input[type=password]');
    await inputs.nth(0).fill('fixture-current'); await inputs.nth(1).fill('fixture-new'); await inputs.nth(2).fill('fixture-mismatch');
    await inputs.nth(0).locator('xpath=ancestor::form').locator('button[type=submit]').click();
    await page.getByText('New password and confirmation do not match.', { exact: true }).waitFor();
    assert(!requests.some((r) => r.path.includes('change-password')), 'invalid password was submitted');
  });
  await check('AI assistant uses the authenticated backend without provider keys in the browser payload', async () => {
    await page.getByRole('button', { name: 'Toggle AI Assistant', exact: true }).press('Enter');
    const widget = page.locator('div').filter({ has: page.getByRole('heading', { name: 'AI Assistant', exact: true }) }).filter({ has: page.getByPlaceholder('Type a message...') }).last();
    await widget.getByPlaceholder('Type a message...').fill('Fixture assistant request');
    await widget.getByPlaceholder('Type a message...').press('Enter');
    await page.getByText('Fixture AI reply', { exact: true }).waitFor();
    const request = requests.findLast((r) => r.path === '/ai/message');
    assert(request && !('apiKey' in JSON.parse(request.body)) && !('geminiApiKey' in JSON.parse(request.body)), 'provider key sent by browser');
    await page.getByRole('button', { name: 'Close AI Assistant', exact: true }).click();
  });
  await check('Support submits through existing form with intercepted webhook', async () => {
    await page.getByRole('tab', { name: 'Support', exact: true }).click(); await ready('support');
    await page.locator('#subject').fill('Navigation fixture only');
    await page.locator('#category').selectOption('Bug'); await page.locator('#priority').selectOption('Low');
    await page.locator('#description').fill('Intercepted browser validation.');
    await page.getByRole('button', { name: 'Submit Request', exact: true }).click();
    await page.getByText('Your support request has been sent successfully.', { exact: true }).waitFor();
    assert(requests.some((r) => r.path === '/support' && r.authenticated && JSON.parse(r.body).user_id === 'settings-fixture'), 'support payload or authentication changed');
  });
  await check('Master Control saves through existing feature flag API', async () => {
    await page.getByRole('tab', { name: 'Master Control', exact: true }).click(); await ready('master-control');
    await page.getByText('Fixture task flag', { exact: true }).waitFor();
    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/feature-flags') && r.request().method() === 'PUT'),
      page.locator('button[aria-pressed]').first().click(),
    ]);
    assert(requests.some((r) => r.path === '/feature-flags' && r.method === 'PUT'), 'flag save missing');
  });
  await check('API documentation and webhooks reuse existing views', async () => {
    await page.getByRole('tab', { name: 'API', exact: true }).click(); await ready('api');
    await page.getByRole('button', { name: 'Documentation', exact: true }).click();
    await page.getByRole('button', { name: 'Webhooks', exact: true }).click();
    await page.getByRole('heading', { name: 'Webhook endpoints', exact: true }).waitFor();
  });
  await check('SMTP configuration create, edit, test and delete preserve contracts without displaying saved passwords', async () => {
    await page.getByRole('button', { name: 'SMTP', exact: true }).click();
    await page.getByRole('heading', { name: 'SMTP configuration', exact: true }).waitFor();
    await page.getByLabel('Configuration name', { exact: true }).fill('Fixture mailbox');
    await page.getByLabel('SMTP host', { exact: true }).fill('smtp.example.test');
    await page.getByLabel('Username', { exact: true }).fill('mail@example.test');
    await page.getByLabel('Password', { exact: true }).fill('new-fixture-secret');
    await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
    await page.getByText('Configuration saved.', { exact: true }).waitFor();
    assert(!(await page.locator('body').innerText()).includes('fixture-smtp-secret'), 'SMTP secret is visible');
    await page.getByRole('button', { name: 'Edit Fixture mailbox', exact: true }).click();
    assert(await page.locator('input[type=password]').inputValue() === '', 'saved SMTP secret populated form');
    await page.getByLabel('Configuration name', { exact: true }).fill('Updated mailbox');
    await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
    await page.getByText('Configuration saved.', { exact: true }).waitFor();
    const update = requests.findLast((r) => r.path.includes('/config/smtp/multiple/') && r.method === 'PATCH');
    assert(update && !('password' in JSON.parse(update.body)), 'blank password overwrote existing credential');
    await page.getByLabel('Test recipient', { exact: true }).fill('test@example.test');
    await page.getByRole('button', { name: 'Send test email', exact: true }).click();
    await page.getByText('Test email requested.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Delete Updated mailbox', exact: true }).click();
    await page.getByText('Configuration deleted.', { exact: true }).waitFor();
    assert(!await page.evaluate(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('zea-play-cache:') && value.includes('fixture-smtp-secret'))), 'SMTP credential persisted in cache');
  });
  await check('Integration drafts block inner-tab changes until discarded', async () => {
    await page.getByLabel('Configuration name', { exact: true }).fill('Unsaved mailbox');
    acceptDialogs = false;
    await page.getByRole('button', { name: 'OAuth', exact: true }).click(); await page.waitForTimeout(100);
    assert(await page.getByLabel('Configuration name', { exact: true }).inputValue() === 'Unsaved mailbox', 'SMTP draft lost');
    acceptDialogs = true;
    await page.getByRole('button', { name: 'OAuth', exact: true }).click();
    await page.getByRole('heading', { name: 'OAuth configuration', exact: true }).waitFor();
  });
  await check('OAuth configuration create, rotate, delete and explicit credential reveal work', async () => {
    await page.getByLabel('Configuration name', { exact: true }).fill('Fixture OAuth');
    await page.getByLabel('Redirect URL', { exact: true }).fill('https://example.test/callback');
    await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
    await page.getByText('Configuration saved.', { exact: true }).waitFor();
    assert(!(await page.locator('body').innerText()).includes('fixture-oauth-secret'), 'OAuth secret exposed by default');
    await page.getByRole('button', { name: 'Reveal credentials', exact: true }).click();
    await page.getByText('fixture-oauth-secret', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Hide credentials', exact: true }).click();
    await page.getByRole('button', { name: 'Rotate credentials', exact: true }).click();
    await page.getByText('Credentials rotated.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Delete Fixture OAuth', exact: true }).click();
    await page.getByText('Configuration deleted.', { exact: true }).waitFor();
    assert(!await page.evaluate(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('zea-play-cache:') && value.includes('fixture-oauth-secret'))), 'OAuth secret persisted in cache');
  });
  await check('Bearer history survives reload within its account session without localStorage secrets', async () => {
    await page.getByRole('button', { name: 'Bearer Key Builder', exact: true }).click();
    await page.getByLabel('Key label', { exact: true }).fill('Fixture key');
    await page.getByRole('button', { name: 'Generate Key', exact: true }).click();
    await page.waitForFunction(() => sessionStorage.getItem('zea-play::bearer-key-history:settings-fixture')?.includes('fixture-generated-token'));
    assert(!await page.evaluate(() => Object.values(localStorage).some((value) => value.includes('fixture-generated-token'))), 'token persisted in localStorage');
    await page.reload(); await ready('api');
    await page.getByRole('button', { name: 'Bearer Key Builder', exact: true }).click();
    assert(await page.evaluate(() => Array.from(document.querySelectorAll('input')).some((input) => input.value === 'fixture-generated-token')), 'session history was lost');
  });
  await check('Owner can update the server AI provider key without prefilled or cached credentials', async () => {
    await page.getByRole('button', { name: 'AI provider', exact: true }).click();
    await page.getByRole('heading', { name: 'AI provider configuration', exact: true }).waitFor();
    assert(await page.getByLabel('New provider key', { exact: true }).inputValue() === '', 'provider credential prefilled');
    assert(!(await page.locator('body').innerText()).includes('fixture-server-ai-key'), 'stored provider credential exposed');
    await page.getByLabel('New provider key', { exact: true }).fill('replacement-fixture-provider');
    await page.getByRole('button', { name: 'Save provider configuration', exact: true }).click();
    await page.getByText('Provider configuration saved.', { exact: true }).waitFor();
    assert(requests.some((r) => r.path === '/config/api' && r.method === 'PATCH' && JSON.parse(r.body).api_key === 'replacement-fixture-provider'), 'provider update contract changed');
    assert(!await page.evaluate(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('zea-play-cache:') && value.includes('fixture-server-ai-key'))), 'provider key cached');
  });
  await check('Avatar crop callback, dialog focus and finalize API work without overwriting profile edits', async () => {
    await visit('/settings/profile'); await ready('profile');
    await page.getByRole('tabpanel').locator('input').first().fill('Keep profile draft');
    await page.locator('input[type=file]').first().evaluate((input) => {
      const transfer = new DataTransfer();
      const canvas = document.createElement('canvas'); canvas.width = 64; canvas.height = 64;
      const bytes = Uint8Array.from(atob(canvas.toDataURL('image/png').split(',')[1]), char => char.charCodeAt(0));
      transfer.items.add(new File([bytes], 'avatar.png', { type: 'image/png' }));
      input.files = transfer.files; input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const cropper = page.getByRole('dialog', { name: 'Adjust avatar', exact: true });
    await cropper.waitFor();
    await page.waitForFunction(() => { const image = document.querySelector('[role=dialog] img'); return image?.naturalWidth > 0; });
    await page.waitForTimeout(150);
    await cropper.getByRole('button', { name: 'Save avatar', exact: true }).click();
    await page.getByText('Profile picture updated successfully.', { exact: true }).waitFor();
    assert(requests.some((r) => r.path === '/users/me/avatar' && r.body.includes('name="crop"')), 'crop metadata was not finalized');
    assert(await page.getByRole('tabpanel').locator('input').first().inputValue() === 'Keep profile draft', 'avatar update reset dirty profile');
    await page.getByRole('tab', { name: 'Support', exact: true }).click(); await ready('support');
  });
  await check('Logs filters retain existing API calls', async () => {
    await visit('/settings/logs'); await ready('logs');
    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/logs/audit?') && r.url().includes('category=security')),
      page.getByRole('button', { name: 'Security Logs', exact: true }).click(),
    ]);
    assert(requests.some((r) => r.path === '/logs/audit' && r.query.includes('category=security')), 'log filter missing');
  });
  await check('Media preview, search and upload keep existing APIs', async () => {
    await page.getByRole('tab', { name: 'Media Library', exact: true }).click(); await ready('media-library');
    await page.getByRole('img', { name: 'fixture.png', exact: true }).click();
    await page.getByRole('heading', { name: 'fixture.png', exact: true }).waitFor();
    await page.keyboard.press('Tab');
    assert(await page.getByRole('dialog').evaluate((el) => el.contains(document.activeElement)), 'media dialog does not trap keyboard focus');
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    await page.getByPlaceholder('Search filename...').fill('no-match');
    await page.getByText('No media yet', { exact: true }).waitFor();
    assert(requests.some((r) => r.path === '/media/list' && r.query.includes('search=no-match')), 'media search missing');
    await page.getByPlaceholder('Search filename...').fill('');
    await page.locator('input[type=file]').evaluate((input) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([new Uint8Array([137, 80, 78, 71])], 'fixture.png', { type: 'image/png' }));
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.getByText('Completed', { exact: true }).waitFor();
    assert(requests.some((r) => r.path === '/media/presign') && requests.some((r) => r.path === '/settings-fixture-upload' && r.method === 'PUT') && requests.some((r) => r.path === '/media/confirm'), 'media upload pipeline missing');
  });
  for (const width of [390, 768]) {
    await check(`${width}px mobile/tablet Settings navigation and no page overflow`, async () => {
      await page.setViewportSize({ width, height: 900 });
      await visit('/settings/support'); await ready('support');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'horizontal page overflow');
      await page.locator('.mobile-nav-shell').getByRole('button', { name: 'Open pages menu', exact: true }).click();
      const menu = page.locator('.mobile-menu-card');
      assert(await menu.getByRole('link', { name: 'Settings', exact: true }).count() === 1, 'Settings missing from mobile menu');
      assert(await menu.locator('a[href="#/media"],a[href="#/logs"],a[href="#/api/overview"]').count() === 0, 'mobile standalone entries remain');
      await page.keyboard.press('Tab');
      assert(await page.getByRole('dialog', { name: 'Pages', exact: true }).evaluate((el) => el.contains(document.activeElement)), 'mobile menu focus escaped');
      await menu.getByRole('link', { name: 'Settings', exact: true }).click(); await ready('profile');
      await page.getByRole('tab', { name: 'Media Library', exact: true }).click(); await ready('media-library');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'media page overflow');
      await page.locator('.mobile-nav-shell').getByRole('button', { name: 'Open pages menu', exact: true }).click();
      await page.keyboard.press('Escape');
      await page.getByRole('dialog', { name: 'Pages', exact: true }).waitFor({ state: 'hidden' });
    });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const currentRole of ['user', 'manager', 'admin']) {
    role = currentRole;
    await check(`${role} sees only authorized Settings tabs`, async () => {
      await visit('/settings/profile'); await ready('profile');
      const expected = role === 'user' ? ['General / Profile', 'Support', 'Media Library'] : role === 'admin' ? ['General / Profile', 'Support', 'API', 'Logs', 'Media Library', 'Sidebar Management'] : ['General / Profile', 'Support', 'Logs', 'Media Library'];
      assert(JSON.stringify(await page.getByRole('tab').allTextContents()) === JSON.stringify(expected), 'incorrect authorized tabs');
      assert(await page.getByRole('heading', { name: 'Data backup & maintenance', exact: true }).count() === 0, 'owner data maintenance exposed');
    });
    await check(`${role} retains Media access without delete controls and its existing Logs access`, async () => {
      await visit('/settings/media-library'); await ready('media-library');
      await page.getByRole('img', { name: 'fixture.png', exact: true }).waitFor();
      assert(await page.getByRole('button', { name: 'Delete', exact: true }).count() === 0, 'media delete exposed');
      if (role !== 'user') { await visit('/settings/logs'); await ready('logs'); }
    });
    for (const key of (role === 'user' ? ['master-control', 'api', 'logs'] : role === 'admin' ? ['master-control'] : ['master-control', 'api'])) {
      await check(`${role} blocked from direct ${key} route before privileged requests`, async () => {
        const start = requests.length;
        await visit(`/settings/${key}`);
        await page.waitForURL((url) => url.hash === '#/settings/profile');
        assert(!requests.slice(start).some((r) => ['/feature-flags', '/logs/audit', '/config/api', '/webhooks'].includes(r.path)), 'restricted page requested sensitive data');
        const legacy = { 'master-control': '/master-control', api: '/api/overview', logs: '/logs' }[key];
        await visit(legacy); await page.waitForURL((url) => url.hash === '#/settings/profile');
      });
    }
  }
  role = 'owner';
  const row = id => page.locator(`[data-page-id="${id}"]`);
  const management = async () => { await visit('/settings/sidebar-management'); await ready('sidebar-management'); };
  await check('Existing tenant/account preferences migrate without overwriting their source', async () => {
    await page.evaluate(() => {
      localStorage.removeItem('zea.sidebar.v2:tenant-fixture:settings-fixture');
      localStorage.setItem('zea.sidebar.v1:tenant-fixture:settings-fixture', JSON.stringify({ order: ['/tasks', '/dashboard'], labels: { '/tasks': 'My Work' } }));
    });
    await management();
    assert(await row('tasks').getByLabel('Name for All Tasks', { exact: true }).inputValue() === 'My Work', 'migrated label missing');
    assert(await page.locator('.sidebar-shell a').first().getAttribute('href') === '#/tasks', 'migrated order missing');
    assert(await page.evaluate(() => localStorage.getItem('zea.sidebar.v1:tenant-fixture:settings-fixture')?.includes('My Work')), 'legacy source overwritten');
  });
  await check('Personal rename and keyboard reorder save without changing organization policy', async () => {
    const writes = requests.filter(r => r.path === '/navigation' && r.method === 'PUT').length;
    await row('tasks').getByLabel('Name for All Tasks', { exact: true }).fill('Team Work');
    await row('tasks').getByRole('button', { name: 'Move All Tasks down', exact: true }).click();
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await page.getByText('Your personal names and ordering were saved in this browser.', { exact: true }).waitFor();
    assert(requests.filter(r => r.path === '/navigation' && r.method === 'PUT').length === writes, 'personal layout changed global policy');
    await page.reload(); await ready('sidebar-management');
    assert(await row('tasks').getByLabel('Name for All Tasks', { exact: true }).inputValue() === 'Team Work', 'personal rename not persistent');
    assert(await page.locator('.sidebar-shell a').first().getAttribute('href') === '#/dashboard', 'arrow reorder not persistent');
  });
  await check('Sidebar editor dirty drafts block tab changes and browser Back', async () => {
    await row('tasks').getByLabel('Name for All Tasks', { exact: true }).fill('Unsaved Work');
    acceptDialogs = false;
    await page.getByRole('tab', { name: 'Support', exact: true }).click(); await page.waitForTimeout(150);
    assert(page.url().endsWith('/settings/sidebar-management'), 'dirty editor was left');
    assert(await row('tasks').getByLabel('Name for All Tasks', { exact: true }).inputValue() === 'Unsaved Work', 'draft lost');
    acceptDialogs = true;
    await page.getByRole('button', { name: 'Discard Changes / Reload', exact: true }).click();
    await page.waitForTimeout(150);
    assert(await row('tasks').getByLabel('Name for All Tasks', { exact: true }).inputValue() === 'Team Work', 'discard did not restore saved layout');
  });
  await check('Drag handle reorders pages and persists after save', async () => {
    await page.setViewportSize({ width: 1440, height: 1800 });
    await row('dashboard').scrollIntoViewIfNeeded();
    const before = await page.locator('[data-page-id]').first().getAttribute('data-page-id');
    const handle = row('tasks').locator('[title="Drag All Tasks"]');
    const source = await handle.boundingBox(), target = await row('dashboard').boundingBox();
    assert(source && target, 'drag targets missing');
    await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
    await page.mouse.down();
    await page.mouse.move(source.x + source.width / 2, target.y + 20, { steps: 24 });
    await page.mouse.up(); await page.waitForTimeout(350);
    assert(await page.locator('[data-page-id]').first().getAttribute('data-page-id') !== before, 'drag did not reorder');
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await page.getByText('Your personal names and ordering were saved in this browser.', { exact: true }).waitFor();
    await page.reload(); await ready('sidebar-management');
    assert(await page.locator('.sidebar-shell a').first().getAttribute('href') === '#/tasks', 'drag order not persisted');
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check('Nested Settings labels and order use personal preferences', async () => {
    await page.getByRole('button', { name: 'Settings Tabs', exact: true }).click();
    await row('settings.support').getByLabel('Name for Support', { exact: true }).fill('Help Desk');
    await row('settings.support').getByRole('button', { name: 'Move Support up', exact: true }).click();
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await page.getByRole('tab', { name: 'Help Desk', exact: true }).waitFor();
    assert((await page.getByRole('tab').allTextContents())[0] === 'Help Desk', 'nested order ignored');
    await row('settings.support').getByLabel('Name for Support', { exact: true }).fill('Support');
    await row('settings.support').getByRole('button', { name: 'Move Support down', exact: true }).click();
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await page.getByRole('tab', { name: 'Support', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Main Sidebar Pages', exact: true }).click();
  });
  await check('Empty names prevent save and search disables reordering', async () => {
    await row('tasks').getByLabel('Name for All Tasks', { exact: true }).fill(' ');
    assert(await page.getByRole('button', { name: 'Save Changes', exact: true }).isDisabled(), 'empty name allowed');
    await row('tasks').getByLabel('Name for All Tasks', { exact: true }).fill('Team Work');
    await page.getByRole('searchbox', { name: 'Search pages', exact: true }).fill('All Tasks');
    assert(await row('tasks').getByRole('button', { name: 'Move All Tasks down', exact: true }).isDisabled(), 'filtered reorder enabled');
    await page.getByRole('searchbox', { name: 'Search pages', exact: true }).fill('');
  });
  await check('Protected pages and forbidden role options cannot be changed in the editor', async () => {
    assert(await row('settings').getByRole('switch', { name: 'Enable Settings', exact: true }).isDisabled(), 'Settings parent not protected');
    await page.getByRole('button', { name: 'Settings Tabs', exact: true }).click();
    assert(await row('settings.profile').getByRole('switch').isDisabled(), 'Profile not protected');
    assert(await row('settings.sidebar-management').getByRole('switch').isDisabled(), 'management not protected');
    await row('settings.api').locator('summary').click();
    assert(await row('settings.api').getByLabel('API: user', { exact: true }).isDisabled(), 'API user escalation allowed');
    assert(await row('settings.api').getByLabel('API: manager', { exact: true }).isDisabled(), 'API Manager ceiling widened');
  });
  await check('Main and nested modules save only after high-impact confirmation', async () => {
    const writes = requests.filter(r => r.path === '/navigation' && r.method === 'PUT').length;
    await row('settings.support').getByRole('switch').uncheck();
    await page.getByRole('button', { name: 'Main Sidebar Pages', exact: true }).click();
    await row('tickets').getByRole('switch').uncheck();
    assert(requests.filter(r => r.path === '/navigation' && r.method === 'PUT').length === writes, 'checkbox auto-saved');
    acceptDialogs = false;
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    assert(requests.filter(r => r.path === '/navigation' && r.method === 'PUT').length === writes, 'cancelled policy was saved');
    acceptDialogs = true;
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await page.getByText(/Organization policy and personal layout saved/).waitFor();
    assert(await page.locator('.sidebar-shell a[href="#/tickets"]').count() === 0, 'disabled main link visible');
    assert(await page.getByRole('tab', { name: 'Support', exact: true }).count() === 0, 'disabled nested link visible');
    await visit('/tickets'); await ready('profile');
    await page.getByRole('alert').filter({ hasText: 'disabled by your organization' }).waitFor();
    await visit('/support'); await ready('profile');
    await page.getByRole('alert').filter({ hasText: 'Support is disabled' }).waitFor();
    for (const alternate of ['/SETTINGS/SUPPORT/', '/settings/%73upport']) {
      await visit(alternate); await ready('profile');
      await page.getByRole('alert').filter({ hasText: 'Support is disabled' }).waitFor();
    }
  });
  await check('Reset Defaults restores availability and personal layout without expanding permissions', async () => {
    await management();
    await page.getByRole('button', { name: 'Reset Defaults', exact: true }).click();
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await page.getByText(/Organization policy and personal layout saved/).waitFor();
    assert(await page.locator('.sidebar-shell a[href="#/tickets"]').count() === 1, 'reset did not restore main page');
    assert(await page.getByRole('tab', { name: 'API', exact: true }).count() === 1, 'owner API lost');
  });
  await check('Hidden navigation preserves independently authorized direct access', async () => {
    await page.getByRole('button', { name: 'Settings Tabs', exact: true }).click();
    await row('settings.support').getByLabel('Hide Support navigation only', { exact: true }).check();
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await page.getByText(/Organization policy and personal layout saved/).waitFor();
    assert(await page.getByRole('tab', { name: 'Support', exact: true }).count() === 0, 'hidden tab visible');
    await visit('/settings/support');
    await page.getByRole('heading', { name: 'Submit Support Request', exact: true }).waitFor();
    assert(page.url().endsWith('/settings/support'), 'hidden page was forbidden');
    policyRules['settings.support'].hidden = false; policyVersion++;
  });
  await check('A concurrent save reports conflict and preserves the local draft', async () => {
    await management();
    await row('tickets').getByLabel('Hide Ticket navigation only', { exact: true }).check();
    await row('tasks').getByLabel('Name for All Tasks', { exact: true }).fill('Retain conflict draft');
    policyVersion++;
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Navigation changed in another session' }).waitFor();
    assert(await row('tasks').getByLabel('Name for All Tasks', { exact: true }).inputValue() === 'Retain conflict draft', 'conflict destroyed draft');
    await page.getByRole('button', { name: 'Discard Changes / Reload', exact: true }).click();
  });
  await check('Active sessions revalidate on focus and leave newly disabled pages', async () => {
    await visit('/settings/media-library'); await ready('media-library');
    await page.locator('.sidebar-shell').evaluate(el => { el.dataset.policyTest = 'preserved'; });
    policyRules['settings.media-library'].enabled = false; policyVersion++;
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await ready('profile');
    assert(await page.locator('.sidebar-shell').getAttribute('data-policy-test') === 'preserved', 'surrounding layout was reset');
    await page.getByRole('alert').filter({ hasText: 'Media Library is disabled' }).waitFor();
    policyRules['settings.media-library'].enabled = true; policyVersion++;
  });
  await check('Unavailable global policy fails closed with a working Retry action', async () => {
    policyUnavailable = true;
    await visit('/settings/api');
    await page.getByRole('alert').filter({ hasText: 'Fixture navigation unavailable' }).waitFor();
    assert(await page.getByRole('heading', { name: 'API & OAuth Management', exact: true }).count() === 0, 'privileged page loaded without policy');
    policyUnavailable = false;
    await page.getByRole('button', { name: 'Retry navigation configuration', exact: true }).click(); await ready('api');
  });
  await check('Admin editor preserves Owner-only policy controls', async () => {
    role = 'admin'; await management();
    assert(await row('tickets').getByRole('switch').isDisabled(), 'Admin can disable modules');
    assert(await row('tickets').getByLabel('Hide Ticket navigation only', { exact: true }).isEnabled(), 'Admin layout control missing');
    assert(await page.getByRole('tab', { name: 'API', exact: true }).count() === 1, 'Authorized Admin API access missing');
    role = 'owner';
  });
  for (const width of [390, 1440]) {
    await check(`Sidebar Management remains usable at ${width}px`, async () => {
      await page.setViewportSize({ width, height: 1000 }); await management();
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'horizontal page overflow');
      await row('tasks').getByLabel('Name for All Tasks', { exact: true }).fill('Responsive draft');
      await row('tasks').getByRole('button', { name: 'Move All Tasks up', exact: true }).click();
      await page.getByRole('button', { name: 'Discard Changes / Reload', exact: true }).click();
    });
  }
  await check('Media error state remains inside Settings shell', async () => {
    mediaError = true;
    await visit('/settings/media-library'); await selected('media-library');
    await page.getByText('Fixture media unavailable', { exact: true }).waitFor();
    assert(await page.getByRole('tab').count() === 8, 'error removed Settings navigation');
    mediaError = false;
  });
  await check('Logout remains accessible through the existing header account menu', async () => {
    await visit('/settings/profile'); await ready('profile');
    await page.getByRole('button', { name: 'Navigation Tester owner', exact: true }).click();
    await page.getByRole('button', { name: 'Logout', exact: true }).click();
    await page.waitForURL((url) => url.hash === '#/login');
    assert(!await page.evaluate(() => Object.keys(sessionStorage).some((key) => key.startsWith('zea-play::bearer-key-history:'))), 'logout retained credential history');
  });
  await check('Signed-out deep links and legacy administrative URLs require login', async () => {
    signedOut = true;
    for (const path of ['/settings/api', '/api/overview', '/master-control']) {
      await visit(path); await page.waitForURL((url) => url.hash === '#/login');
      assert(await page.getByRole('tab').count() === 0, 'Settings rendered without authentication');
    }
  });
  await check('No uncaught browser errors', async () => assert(pageErrors.length === 0, pageErrors.join('\n')));
  page.off('pageerror', onError);
  page.off('dialog', onDialog);
  const summary = { passed: results.filter((r) => r.status === 'PASS').length, failed: results.filter((r) => r.status === 'FAIL').length, results, pageErrors };
  await page.evaluate((value) => { window.__settingsNavigationResults = value; }, summary);
  return summary;
}
