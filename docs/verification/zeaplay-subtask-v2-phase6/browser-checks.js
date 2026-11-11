async (page) => {
  page.setDefaultTimeout(7000);
  page.setDefaultNavigationTimeout(15000);
  await page.addInitScript(() => localStorage.removeItem('zea:notification-seen:phase6-user'));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.hostname === '127.0.0.1' && url.port === '6325') return url.pathname.startsWith('/api/') ? route.fulfill({ json: [] }) : route.continue();
    if (url.hostname === 'cdn.tailwindcss.com') return route.continue();
    return route.fulfill({ status: 200, body: '' });
  });
  const checks = [];
  const check = (name, value) => { if (!value) throw new Error(name); checks.push({ name, result: 'PASS' }); };
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('http://127.0.0.1:6325/checks/phase6.html');
  await page.waitForTimeout(1300);
  const state = () => page.evaluate(() => {
    const s = window.__phase6.state;
    return { calls: s.calls, shown: s.shown.length, sounds: s.sounds, prompts: s.prompts,
      sockets: s.sockets.filter(s => s.readyState === 1).length, opened: s.opened, saved: s.saved };
  });
  const add = async (id, patch = {}) => {
    await page.evaluate(({ id, patch }) => {
      const f = window.__phase6;
      Object.assign(f.state, patch);
      f.state.items.unshift({ id, userId: f.user.id, type: 'TASK_UPDATED', alertKind: 'task_updated',
        title: id, message: `Notification ${id}`, isRead: false, relatedTaskId: 'task-1', relatedRewardId: null,
        deepLink: '/tasks/task-1', createdAt: new Date().toISOString() });
      f.state.unread++; f.emit();
    }, { id, patch });
    await page.waitForTimeout(450);
  };
  const bell = () => page.getByRole('button', { name: /Notifications, \d+ unread/ });
  const hasUnread = async count => (await bell().getAttribute('aria-label'))?.startsWith(`Notifications, ${count} unread`);
  check('Authoritative unread count includes notifications beyond visible page', await hasUnread(151));
  check('StrictMode leaves one shared task socket', (await state()).sockets === 1);
  check('StrictMode and initial socket connection coalesce to one inbox read', (await state()).calls === 1);
  check('No automatic permission request or historical browser replay', (await state()).prompts === 0 && (await state()).shown === 0);
  await add('denied');
  check('Denied browser retains in-app unread alert', await hasUnread(152));
  check('Denied browser produces no browser notification or default sound', (await state()).shown === 0 && (await state()).sounds === 0);
  await page.evaluate(() => window.__phase6.permission('granted'));
  await add('granted');
  check('Granted permission uses browser delivery', (await state()).shown === 1);
  check('Sound defaults off', (await state()).sounds === 0);
  await page.evaluate(() => { for (let i = 0; i < 100; i++) window.__phase6.emit(); });
  const before = (await state()).calls;
  await page.waitForTimeout(450);
  check('One hundred realtime events coalesce to one inbox read', (await state()).calls - before === 1);
  check('Repeated state produces no duplicate browser alert', (await state()).shown === 1);
  await add('audible', { sound: true });
  check('Enabled sound produces one short audio presentation', (await state()).sounds === 1);
  await add('quiet', { quiet: true });
  check('Quiet hours suppress browser and sound while keeping unread state', (await state()).sounds === 1 && (await state()).shown === 2 && await hasUnread(155));
  await add('push-off', { quiet: false, push: false, sound: false });
  check('Disabled task push suppresses browser without losing inbox', (await state()).shown === 2 && await hasUnread(156));
  await page.evaluate(() => { window.__phase6.state.fail = true; window.__phase6.notify(); });
  await page.waitForTimeout(350);
  check('Failed inbox refetch preserves last readable state', await hasUnread(156));
  await page.evaluate(() => { window.__phase6.state.fail = false; window.__phase6.state.unread = 157; window.dispatchEvent(new Event('online')); });
  await page.waitForTimeout(450);
  check('Online recovery refetches authoritative unread count', await hasUnread(157));
  await bell().focus(); await page.keyboard.press('Enter');
  check('Keyboard opens existing notification center', await page.getByRole('button', { name: /Notification push-off/ }).isVisible());
  await page.keyboard.press('Escape');
  check('Escape closes notification center and restores focus', await bell().evaluate(el => document.activeElement === el));
  await bell().click();
  await page.getByRole('button', { name: /Notification push-off/ }).click();
  await page.waitForTimeout(400);
  check('Notification opens the relevant task through the existing callback', (await state()).opened.at(-1) === 'task-1');
  check('Read action updates authoritative badge', await hasUnread(156));
  await page.evaluate(() => {
    const f = window.__phase6;
    f.state.items.unshift({id:'owned-balance',userId:f.user.id,type:'TASK_UPDATED',alertKind:'points_reversed',
      title:'Owned balance adjustment',message:'Own private balance adjustment',body:'Own private balance adjustment',
      isRead:false,relatedTaskId:null,relatedRewardId:null,createdAt:new Date().toISOString()});
    f.state.unread++;f.notify();
  });
  await page.waitForTimeout(400);await bell().click();
  await page.getByRole('button',{name:/Own private balance adjustment/}).click();
  await page.getByText('Own private balance adjustment',{exact:true}).waitFor();
  await page.evaluate(() => window.__phase6.rotateSession());await page.waitForTimeout(400);
  check('Session change clears private notification preview', await page.getByText('Own private balance adjustment',{exact:true}).count() === 0);
  await bell().click();await page.getByRole('button',{name:/Own private balance adjustment/}).click();
  await page.evaluate(() => window.__phase6.changeRole());await page.waitForTimeout(400);
  check('Role change clears private notification preview', await page.getByText('Own private balance adjustment',{exact:true}).count() === 0);
  await page.getByLabel('Approaching deadline (hours)').fill('6');
  await page.getByLabel('Productive capacity override (hours per day)').fill('4');
  await page.getByLabel('Overtime alert after (minutes)').fill('15');
  await page.getByLabel('Notification sound', { exact: true }).check();
  await page.getByLabel('Quiet hours start').fill('22:00');
  await page.getByRole('button', { name: 'Save workload alerts' }).click();
  check('Incomplete quiet-hour range gives useful error', await page.getByRole('alert').innerText() === 'Enter both quiet-hour times, or clear both.');
  await page.getByLabel('Quiet hours end').fill('06:00');
  await page.getByRole('button', { name: 'Save workload alerts' }).click();
  check('Workload preference save preserves explicit capacity and sound', (await state()).saved.at(-1)?.productiveCapacityHours === 4 && (await state()).saved.at(-1)?.soundEnabled === true);
  await page.getByRole('button', { name: /Task activity/ }).click();
  check('Activity popup uses configurable approaching-deadline window', await page.getByText('Next 6 hours:', { exact: false }).isVisible());
  check('Header activity explains estimated overload', await page.getByText('Estimated workload exceeds remaining available hours.').isVisible());
  await page.keyboard.press('Escape');
  await page.addScriptTag({ url: 'http://127.0.0.1:6325/checks/axe.min.js' });
  const formAxe = await page.evaluate(async () => {
    const result = await window.axe.run(document.querySelector('form[aria-label="Workload alert preferences"]'), { rules: { 'color-contrast': { enabled: false } } });
    return { violations: result.violations.map(v => ({ id: v.id, nodes: v.nodes.length })), incomplete: result.incomplete.map(v => v.id) };
  });
  check('Workload form has no automated accessibility violations excluding contrast', formAxe.violations.length === 0);
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(500);
  check('Mobile navigation exposes unread count before expanding', await page.getByRole('button', { name: /Open menu, \d+ unread notifications/ }).isVisible());
  await page.getByRole('button', { name: /Open menu,/ }).click();
  check('Mobile unread badge remains accessible', await bell().isVisible());
  check('Mobile preferences fit viewport', await page.locator('form[aria-label="Workload alert preferences"]').evaluate(el => el.getBoundingClientRect().right <= innerWidth + 1));
  await bell().click();
  check('Mobile notification center stays within the viewport', await page.getByRole('region', {name:'Notifications', exact:true}).evaluate(el => el.getBoundingClientRect().left >= 0 && el.getBoundingClientRect().right <= innerWidth + 1));
  check('Mobile notifications remain selectable', await page.getByRole('button', { name: /Notification granted/ }).isVisible());
  await page.keyboard.press('Escape');
  const prior = (await state()).calls;
  await page.evaluate(() => window.__phase6.state.toggle(false)); await page.waitForTimeout(100);
  await page.evaluate(() => { window.__phase6.notify(); window.dispatchEvent(new Event('focus')); });
  await page.waitForTimeout(400);
  check('Unmount removes inbox event listeners and shared socket', (await state()).calls === prior && (await state()).sockets === 0);
  check('No browser permission prompt during all scenarios', (await state()).prompts === 0);
  return { checks, accessibility: formAxe, fixture: 'Actual Header, hooks, activity dialog and workload preferences under StrictMode; synthetic API and transports' };
}
