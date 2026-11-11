// Run via Playwright browser_run_code_unsafe against the isolated Vite fixture.
async function verifyAvatarProfile(page) {
  const origin = 'http://127.0.0.1:6321';
  const results = [], errors = [], writes = [], images = [];
  let version = 0, failUpload = false;
  let user = { id: 'avatar-fixture', name: 'Alice Johnson', email: 'alice@example.test', role: 'user', status: 'ACTIVE',
    employer_id: 'EMP-001', title: 'Project Manager', points: 0, tasks_created: 0, tasks_completed: 0,
    skills: [], projects: ['Release planning'], claimed_reward_ids: [], unlocked_achievement_ids: [], clarity_scores: [],
    updated_at: '2026-10-29T08:00:00', created_at: '2026-10-01T08:00:00' };
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZfQAAAAASUVORK5CYII=', 'base64');
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const check = async (name, action) => {
    try { await action(); results.push({ name, status: 'PASS' }); }
    catch (error) { results.push({ name, status: 'FAIL', error: String(error).slice(0, 500) }); }
  };
  page.setDefaultTimeout(8000);
  page.on('pageerror', error => errors.push(String(error)));
  page.on('dialog', dialog => dialog.accept());
  await page.unrouteAll({ behavior: 'wait' });
  await page.addInitScript(() => {
    Object.keys(localStorage).filter(key => key.startsWith('zea-play-cache:')).forEach(key => localStorage.removeItem(key));
    localStorage.setItem('vee_access_token', 'fixture-token');
    localStorage.setItem('zenith-task-theme', 'dark');
    localStorage.setItem('org-user-profiles-v1', JSON.stringify({bob: {phone: 'retired-secret-phone', notes: 'retired-secret-note'}}));
  });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) {
      const path = url.pathname.slice(4);
      if (path === '/auth/me') return route.fulfill({ json: user });
      if (/^\/avatars\/[^/]+\/image/.test(path)) {
        images.push(url.pathname + url.search);
        assert(request.headers().authorization === 'Bearer fixture-token', 'Photo request has no bearer authentication');
        if (path.includes('avatar-default-01')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="32" fill="cyan"/></svg>' });
        return route.fulfill({ contentType: 'image/png', body: png });
      }
      if (path === '/users/me/avatar') {
        assert(request.headers()['content-type'].startsWith('multipart/form-data; boundary='), 'Avatar request is not multipart');
        assert(request.postData().includes('name="crop"'), 'Crop metadata missing from multipart');
        writes.push({ path, method: request.method() });
        if (failUpload) { failUpload = false; return route.fulfill({ status: 400, json: { detail: 'Fixture image rejected' } }); }
        version++;
        user = { ...user, avatar_asset_id: `photo-${version}`, avatar_url: `/avatars/photo-${version}/image?v=${version}`,
          updated_at: `2026-10-29T08:00:${String(version).padStart(2, '0')}` };
        return route.fulfill({ json: user });
      }
      if ((path === '/users/me' || path === '/users/avatar-fixture') && request.method() === 'PATCH') {
        const body = request.postDataJSON(); writes.push({ path, body });
        user = { ...user, ...body };
        if ('avatar_asset_id' in body && body.avatar_asset_id === null) user.avatar_url = null;
        return route.fulfill({ json: user });
      }
      if (path === '/users') return route.fulfill({ json: [user,
        { ...user, id: 'bob', name: 'Bob Miller', email: 'bob@example.test', employer_id: 'EMP-002', role: 'user', department_id: 'design', department: { id: 'design', name: 'Design' }, phone: null, notes: null },
        ...Array.from({length: 12}, (_, index) => ({ ...user, id: `peer-${index}`, name: `Colleague ${index}`, employer_id: `EMP-${100 + index}`, role: index % 2 ? 'user' : 'admin', department_id: 'engineering', department: { id: 'engineering', name: 'Engineering' } }))] });
      if (path === '/avatars') return route.fulfill({ json: [{ id: 'avatar-default-01', name: 'Workspace artwork', storage_type: 'file', url: '/avatars/avatar-default-01/image?v=1', is_default: true, created_at: user.created_at, updated_at: user.updated_at }] });
      if (path === '/avatars/policy') return route.fulfill({ json: { maxBytes: 5 * 1024 * 1024, contentTypes: ['image/jpeg', 'image/png', 'image/webp'] } });
      if (path === '/departments') return route.fulfill({ json: [{ id: 'engineering', name: 'Engineering' }, { id: 'design', name: 'Design' }] });
      if (path.includes('preferences')) return route.fulfill({ json: [] });
      return route.fulfill({ json: [] });
    }
    if (url.origin === origin || url.hostname === 'cdn.tailwindcss.com' || url.hostname === 'cdn.jsdelivr.net') return route.continue();
    return route.fulfill({ json: {} });
  });
  const visit = (query = '') => page.goto(`${origin}/checks/avatar-profile.fixture.html${query}`, { waitUntil: 'networkidle' });
  const photoInput = () => page.locator('input[type=file][accept="image/jpeg,image/png,image/webp"]').first();
  // A valid local raster is created in the browser so the cropper sees natural dimensions.
  const choosePhoto = async () => {
    const encoded = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = 100; canvas.height = 80;
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#00ccd8'; ctx.fillRect(0, 0, 100, 80);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await photoInput().setInputFiles({ name: 'portrait.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') });
    await page.getByRole('dialog').waitFor();
  };
  await visit();
  await check('Existing user initials, employee fields and self-service permissions', async () => {
    await page.getByRole('heading', { name: 'Profile information' }).waitFor();
    assert((await page.getByTestId('identity-menu').innerText()).includes('AJ'), 'Initials missing');
    assert(await page.getByLabel('Employer ID', { exact: true }).isDisabled(), 'Employee ID editable by regular user');
    assert(await page.getByLabel('Department', { exact: true }).isDisabled(), 'Department editable by regular user');
    assert(await page.getByText('Project Manager', { exact: true }).isVisible(), 'Designation missing');
  });
  await check('Bio and skills persist, duplicates prevented and chips removable', async () => {
    await page.getByLabel('Professional bio', { exact: false }).fill('Managing projects.\n<script>safe text</script>');
    await page.getByPlaceholder('Search or add a skill').fill('React');
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await page.getByPlaceholder('Search or add a skill').fill('react');
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    assert(await page.getByRole('button', { name: 'Remove React' }).count() === 1, 'Duplicate skill allowed');
    await page.getByRole('button', { name: 'Save profile', exact: true }).click();
    await page.getByText('Profile information updated successfully.').waitFor();
    assert(user.skills.length === 1 && user.profile_bio.includes('\n'), 'Profile payload incorrect');
    assert(!('role' in writes.at(-1).body) && !('department_id' in writes.at(-1).body), 'Self-service sent protected fields');
    await visit();
    assert((await page.getByLabel('Professional bio', { exact: false }).inputValue()).includes('<script>'), 'Bio lost after refresh');
    assert(await page.locator('script').filter({ hasText: 'safe text' }).count() === 0, 'Bio interpreted as markup');
    await page.getByRole('button', { name: 'Remove React' }).click();
    await page.getByRole('button', { name: 'Save profile', exact: true }).click();
    await page.getByText('Profile information updated successfully.').waitFor();
  });
  await check('Circular crop preview, zoom, reposition and cancel', async () => {
    await choosePhoto();
    const crop = page.locator('.reactEasyCrop_CropArea');
    assert(await crop.evaluate(element => getComputedStyle(element).borderRadius) === '50%', 'Crop preview is not circular');
    await page.getByRole('slider', { name: 'Avatar zoom' }).fill('2');
    const box = await crop.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down(); await page.mouse.move(box.x + box.width / 2 + 20, box.y + box.height / 2 + 10); await page.mouse.up();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert(version === 0, 'Cancel uploaded a photo');
  });
  await check('Avatar upload updates menu, card and settings without reload', async () => {
    await page.getByLabel('Professional bio', { exact: false }).fill('Keep this unsaved bio');
    await choosePhoto();
    await page.getByRole('button', { name: 'Save avatar', exact: true }).click();
    await page.getByText('Profile picture updated successfully.').waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('[aria-label="Alice Johnson profile picture"] img')].filter(img => img.complete && img.naturalWidth > 0).length === 3);
    assert(images.filter(path => path.includes('photo-1')).length === 2, 'Duplicate authenticated image downloads');
    assert(await page.getByLabel('Professional bio', { exact: false }).inputValue() === 'Keep this unsaved bio', 'Upload reset the bio draft');
    await page.getByLabel('Professional bio', { exact: false }).fill(user.profile_bio);
  });
  await check('Frame selection persists independently and survives refresh', async () => {
    await page.getByRole('button', { name: /Aurora Neon/ }).click();
    await page.getByText('Profile frame saved.').waitFor();
    await visit();
    assert(user.avatar_frame === 'aurora', 'Frame was not persisted');
    assert(await page.getByTestId('identity-menu').locator('[role=img]').evaluate(el => el.className.includes('ring-purple')), 'Menu did not get selected frame');
  });
  await check('Replacement uses a new image reference', async () => {
    const previous = user.avatar_url;
    await choosePhoto(); await page.getByRole('button', { name: 'Save avatar', exact: true }).click();
    await page.getByText('Profile picture updated successfully.').waitFor();
    assert(user.avatar_url !== previous, 'Photo cache reference did not change');
  });
  await check('Upload errors keep the crop open for retry', async () => {
    failUpload = true;
    await choosePhoto(); await page.getByRole('button', { name: 'Save avatar', exact: true }).click();
    await page.getByRole('dialog').getByText('Fixture image rejected').waitFor();
    await page.getByRole('button', { name: 'Save avatar', exact: true }).click();
    await page.getByText('Profile picture updated successfully.').waitFor();
  });
  await check('Deletion restores initials and preserves the selected frame', async () => {
    await page.getByRole('button', { name: 'Remove picture', exact: true }).click();
    await page.getByText('Picture removed. Your initials are restored.').waitFor();
    assert((await page.getByTestId('identity-menu').innerText()).includes('AJ'), 'Initials not restored');
    assert(user.avatar_frame === 'aurora' && !user.avatar_url, 'Delete changed frame or retained photo');
  });
  await check('SVG and oversize files are rejected before upload', async () => {
    await photoInput().setInputFiles({ name: 'bad.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg/>') });
    await page.getByText('Unsupported image type. Please upload JPEG, PNG, or WebP.').waitFor();
    await photoInput().setInputFiles({ name: 'big.png', mimeType: 'image/png', buffer: Buffer.alloc(5 * 1024 * 1024 + 1) });
    await page.getByText('Please choose an image that is 5 MB or smaller.').waitFor();
    assert(await page.getByRole('dialog').count() === 0, 'Invalid file opened cropper');
  });
  await check('Mobile identity layout and crop controls do not overflow', async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('region', { name: 'Employee digital ID card' }).scrollIntoViewIfNeeded();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile page overflows');
    await choosePhoto();
    assert(await page.getByRole('button', { name: 'Save avatar', exact: true }).isVisible(), 'Mobile crop save missing');
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile crop overflows');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.setViewportSize({ width: 1365, height: 900 });
  });
  await check('User directory search and employee card with expandable details', async () => {
    await visit('?directory=1');
    await page.getByPlaceholder('Search by name...').fill('Alice');
    await page.getByRole('button', { name: 'Alice Johnson', exact: true }).click();
    await page.getByRole('region', { name: 'Employee digital ID card' }).waitFor();
    await page.getByText('Additional Details', { exact: true }).click();
    assert(await page.getByText('Manager email', { exact: true }).isVisible(), 'Details did not expand');
    assert(await page.getByText('Assigned Projects', { exact: true }).isVisible(), 'Projects section missing');
    await page.setViewportSize({width:390,height:844});
    assert(await page.getByRole('dialog').evaluate(el => el.scrollWidth <= el.clientWidth), 'Mobile user details overflow');
    await page.setViewportSize({width:1365,height:900});
  });
  await check('Admin edits bio and structured skills without splitting commas', async () => {
    user = { ...user, role: 'admin' };
    await visit('?directory=1');
    await page.getByRole('button', { name: 'Alice Johnson', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Edit', exact: true }).click();
    await page.getByRole('dialog').getByRole('textbox', { name: /professional bio/i }).fill('Updated employee responsibilities');
    await page.getByPlaceholder('Search or add a skill').fill('Research, Strategy');
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await page.getByRole('button', { name: 'Save changes', exact: true }).click();
    await page.getByRole('region', { name: 'Employee digital ID card' }).getByText('Updated employee responsibilities').waitFor();
    assert(user.skills.length === 1 && user.skills[0] === 'Research, Strategy', 'Structured skill was split');
  });
  await check('Directory employee ID, role and department filters and pagination', async () => {
    await visit('?directory=1');
    assert(await page.getByText('Showing 1 to 10 of 14 users').isVisible(), 'First page count incorrect');
    await page.getByRole('button', {name:'Next', exact:true}).click();
    await page.getByText('Showing 11 to 14 of 14 users').waitFor();
    await page.getByRole('button', {name:'Previous', exact:true}).click();
    await page.getByPlaceholder('Search by Employer ID...').fill('EMP-002');
    await page.getByText('Showing 1 to 1 of 1 users').waitFor();
    assert(await page.getByRole('button', {name:'Bob Miller',exact:true}).isVisible(), 'Employee ID filter wrong');
    await page.getByRole('button', {name:'Clear filters',exact:true}).click();
    const role = page.locator('select').filter({has:page.locator('option', {hasText:'All Roles'})});
    await role.selectOption('user');
    await page.getByText('Showing 1 to 7 of 7 users').waitFor();
    await page.getByRole('button', {name:'Clear filters',exact:true}).click();
    const department = page.locator('select').filter({has:page.locator('option', {hasText:'All Departments'})});
    await department.selectOption('Design');
    await page.getByText('Showing 1 to 1 of 1 users').waitFor();
    await page.getByRole('button', {name:'Clear filters',exact:true}).click();
    await page.locator('select').filter({has:page.locator('option[value="100"]')}).selectOption('20');
    await page.getByText('Showing 1 to 14 of 14 users').waitFor();
  });
  await check('Retired profile shadows cannot restore private peer contacts', async () => {
    await page.getByRole('button', {name:'Bob Miller',exact:true}).click();
    await page.getByText('Additional Details',{exact:true}).click();
    const dialog = page.getByRole('dialog');
    assert(!(await dialog.innerText()).includes('retired-secret'), 'Retired local profile exposed private data');
    assert(await page.evaluate(() => !Object.keys(localStorage).some(key => key.startsWith('zea-play-cache:') && /:(users|avatar-assets)$/.test(key))), 'Private user data persisted in response cache');
    await dialog.getByRole('button',{name:'Close',exact:true}).click();
  });
  await check('Real workspace library IDs are selectable in the existing editor', async () => {
    const row = page.locator('tr').filter({has:page.getByRole('button',{name:'Alice Johnson',exact:true})});
    await row.getByRole('button').last().click();
    await page.getByRole('menuitem',{name:'Edit',exact:true}).click();
    await page.getByRole('button',{name:'Workspace artwork'}).waitFor();
    await page.waitForFunction(() => document.querySelector('[aria-label="Workspace artwork profile picture"] img')?.naturalWidth > 0);
    await page.getByRole('button',{name:'Workspace artwork'}).click();
    await page.getByRole('button',{name:'Save Changes',exact:true}).click();
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'));
    assert(user.avatar_asset_id === 'avatar-default-01', 'Picker sent a synthetic avatar ID');
  });
  await check('Manager actions retain status management and hide restricted editors', async () => {
    user = {...user,role:'manager'};
    await visit('?directory=1');
    const row = page.locator('tr').filter({has:page.getByRole('button',{name:'Bob Miller',exact:true})});
    await row.getByRole('button').last().click();
    await page.getByRole('menuitem',{name:'Deactivate',exact:true}).waitFor();
    assert(await page.getByRole('menuitem',{name:'Change Role',exact:true}).count() === 0, 'Manager sees restricted role editor');
    assert(await page.getByRole('menuitem',{name:'Reset Password',exact:true}).count() === 0, 'Manager sees credential reset');
  });
  await check('Empty fields and long content fit tablet and mobile identity cards', async () => {
    user = {...user,title:null,profile_bio:null,skills:[],employer_id:null};
    await visit();
    let card = page.getByRole('region',{name:'Employee digital ID card'});
    await card.getByText('No professional bio added yet.').waitFor();
    assert(await card.getByText('Not assigned',{exact:true}).isVisible(), 'Missing employee ID not clean');
    assert(!/undefined|null/.test(await card.innerText()), 'Missing data rendered literally');
    user = {...user,name:'A'.repeat(200),title:'T'.repeat(200),email:'e'.repeat(150)+'@example.test',profile_bio:'B'.repeat(500),skills:['S'.repeat(60)]};
    for (const width of [768,390]) {
      await page.setViewportSize({width,height:900}); await visit();
      card = page.getByRole('region',{name:'Employee digital ID card'});
      assert(await card.evaluate(el => el.scrollWidth <= el.clientWidth), `Long profile overflows at ${width}px`);
    }
    await page.setViewportSize({width:1365,height:900});
  });
  await check('No uncaught component errors', async () => assert(errors.length === 0, errors.join('\n')));
  return { passed: results.filter(r => r.status === 'PASS').length, failed: results.filter(r => r.status === 'FAIL').length, results, errors };
}
