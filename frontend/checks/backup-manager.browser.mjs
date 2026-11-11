// Run against the isolated Vite fixture with ZEA_PLAYWRIGHT_MODULE pointing to
// an installed Playwright package. All API traffic is intercepted; no live data.
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';

const { chromium } = createRequire(import.meta.url)(
  process.env.ZEA_PLAYWRIGHT_MODULE || 'playwright',
);
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const page = await browser.newPage({
  viewport: { width: 1440, height: 1100 },
  acceptDownloads: true,
});
const origin = 'http://127.0.0.1:6331';
const output = path.dirname(
  new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1'),
);
const results = [],
  errors = [];
const datasets = [
  {
    id: 'users',
    name: 'Users',
    count: 24,
    description: 'Profiles only; credentials excluded',
    dependencies: ['departments'],
  },
  {
    id: 'tasks',
    name: 'Tasks',
    count: 13020,
    description: 'Tasks and scheduling',
    dependencies: ['users', 'kanban-columns'],
  },
  {
    id: 'departments',
    name: 'Departments',
    count: 8,
    description: 'Teams and departments',
    dependencies: [],
  },
  {
    id: 'kanban-columns',
    name: 'Kanban Columns',
    count: 9,
    description: 'Task workflow',
    dependencies: [],
  },
  {
    id: 'notifications',
    name: 'Notifications',
    count: 480,
    description: 'Workspace notifications',
    dependencies: ['users'],
  },
];
let presets = [],
  jobs = [],
  downloads = 0,
  restores = 0,
  unexpected = [],
  provisionApproved = false;
const assert = (value, message) => {
  if (!value) throw new Error(message);
};
const check = async (name, run) => {
  try {
    await run();
    results.push({ name, status: 'PASS' });
  } catch (error) {
    results.push({ name, status: 'FAIL', error: String(error).slice(0, 600) });
  }
};
page.setDefaultTimeout(10000);
page.on('pageerror', (error) => errors.push(String(error)));
page.on('download', () => downloads++);
await page.addInitScript(() => {
  localStorage.setItem('vee_access_token', 'fixture-token');
  localStorage.setItem('zenith-task-theme', 'dark');
});
await page.route('**/*', async (route) => {
  const request = route.request(),
    url = new URL(request.url()),
    endpoint = url.pathname.split('/admin/data/manager')[1];
  if (endpoint !== undefined) {
    const method = request.method();
    if (endpoint === '/catalog')
      return route.fulfill({
        json: {
          datasets,
          limitations: [
            'Credentials and opaque audit payloads are excluded.',
            'Storage files require a separate media backup.',
          ],
          unregistered_tables: [],
        },
      });
    if (endpoint === '/jobs') return route.fulfill({ json: jobs });
    if (endpoint === '/presets' && method === 'GET')
      return route.fulfill({ json: presets });
    if (endpoint === '/presets' && method === 'POST') {
      const p = { id: `preset-${presets.length}`, ...request.postDataJSON() };
      presets.push(p);
      return route.fulfill({ json: p });
    }
    if (endpoint.startsWith('/presets/') && method === 'PUT') {
      const p = presets.find((p) => endpoint.endsWith(p.id));
      Object.assign(p, request.postDataJSON());
      return route.fulfill({ json: p });
    }
    if (endpoint.startsWith('/presets/') && method === 'DELETE') {
      presets = presets.filter((p) => !endpoint.endsWith(p.id));
      return route.fulfill({ status: 204 });
    }
    if (endpoint === '/exports') {
      const job = {
        id: 'export-fixture',
        operation: 'Export',
        scope: request.postDataJSON().scope,
        requested_by: 'Workspace Owner',
        started_at: '2026-10-29T12:00:00',
        completed_at: '2026-10-29T12:00:02',
        status: 'Completed',
        record_count: 13541,
        file_size: 128000,
        download_available: true,
        report: {},
      };
      jobs = [job];
      return route.fulfill({ status: 202, json: { ...job, status: 'Queued' } });
    }
    if (endpoint.endsWith('/download-ticket'))
      return route.fulfill({ json: { ticket: 'one-use-fixture-ticket' } });
    if (endpoint.endsWith('/download'))
      return route.fulfill({
        contentType: 'application/zip',
        headers: {
          'Content-Disposition': 'attachment; filename="zea-play-fixture.zip"',
        },
        body: Buffer.from(
          '504b0506000000000000000000000000000000000000',
          'hex',
        ),
      });
    if (endpoint === '/imports/validate') {
      const job = {
        id: 'import-fixture',
        operation: 'Import',
        scope: 'custom',
        requested_by: 'Workspace Owner',
        started_at: '2026-10-29T12:00:00',
        status: 'Queued',
        record_count: 1,
        file_size: 30,
        report: {
          datasets: { departments: 1 },
          selected: ['departments'],
          mode: 'insert',
          impact: { insert: 1, update: 0, skip: 0 },
          errors: [],
          valid: true,
          preview_token: 'fixture-preview',
        },
      };
      jobs.push(job);
      return route.fulfill({ json: job });
    }
    if (endpoint.endsWith('/preview')) {
      const job = jobs.find((j) => j.id === 'import-fixture');
      job.report.mode = request.postDataJSON().mode;
      provisionApproved = request.postDataJSON().provision_users === true;
      return route.fulfill({ json: job });
    }
    if (endpoint.endsWith('/confirm')) {
      restores++;
      const job = jobs.find((j) => j.id === 'import-fixture');
      job.status = 'Completed';
      job.completed_at = '2026-10-29T12:00:03';
      return route.fulfill({ json: job });
    }
    unexpected.push(`${method} ${endpoint}`);
    return route.fulfill({
      status: 404,
      json: { detail: 'Unexpected fixture request' },
    });
  }
  if (url.hostname === '127.0.0.1' || url.hostname === 'cdn.tailwindcss.com')
    return route.continue();
  return route.abort();
});
try {
  await page.goto(origin + '/checks/backup-manager.fixture.html');
  await page.getByRole('button', { name: 'Generate Export' }).waitFor();
  await check(
    'Entire Workspace defaults to one ZIP and all dataset selections',
    async () => {
      await page.getByText('13,541', { exact: true }).waitFor();
      assert(
        (await page.getByRole('checkbox', { checked: true }).count()) === 6,
        'Default dataset/related-data selection incorrect',
      );
      assert(
        await page.getByRole('button', { name: 'Generate Export' }).isEnabled(),
        'Generate disabled',
      );
    },
  );
  await page.screenshot({
    path: path.join(output, 'backup-manager-desktop.png'),
    fullPage: true,
  });
  await check('Custom selection, search, clear and select all', async () => {
    await page
      .getByRole('button', { name: 'Custom Selection', exact: false })
      .click();
    await page
      .getByRole('button', { name: 'Clear Selection', exact: true })
      .click();
    assert(
      await page.getByRole('button', { name: 'Generate Export' }).isDisabled(),
      'Empty export enabled',
    );
    await page
      .getByRole('textbox', { name: 'Search datasets' })
      .fill('Departments');
    await page
      .locator('label')
      .filter({ hasText: 'Departments' })
      .filter({ has: page.locator('input[type=checkbox]') })
      .getByRole('checkbox')
      .check();
    assert(
      await page.getByRole('button', { name: 'Generate Export' }).isEnabled(),
      'Custom selection unavailable',
    );
    await page.getByRole('textbox', { name: 'Search datasets' }).fill('');
    await page.getByRole('button', { name: 'Select All', exact: true }).click();
  });
  await check(
    'Configurations create, rename, duplicate and delete',
    async () => {
      await page
        .getByRole('textbox', { name: 'Configuration name' })
        .fill('Weekly backup');
      await page
        .getByRole('button', { name: 'Save Configuration', exact: true })
        .click();
      await page
        .getByText('Export configuration saved.', { exact: true })
        .waitFor();
      await page
        .getByRole('textbox', { name: 'Configuration name' })
        .fill('Renamed backup');
      await page
        .getByRole('button', { name: 'Save Configuration', exact: true })
        .click();
      await page.waitForFunction(
        () =>
          document.querySelector('option') &&
          [...document.querySelectorAll('option')].some(
            (o) => o.textContent === 'Renamed backup',
          ),
      );
      await page
        .getByRole('button', { name: 'Duplicate', exact: true })
        .click();
      await page.waitForTimeout(250);
      assert(presets.length === 2, 'Duplicate was not saved');
      await page.getByRole('button', { name: 'Delete configuration' }).click();
      await page.waitForTimeout(250);
      assert(
        presets.length === 1 && presets[0].name === 'Renamed backup',
        'Delete/rename failed',
      );
    },
  );
  await check(
    'Exactly one native download; reload does not repeat it',
    async () => {
      const event = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Generate Export' }).click();
      await event;
      await page.waitForTimeout(3500);
      assert(downloads === 1, `Unexpected downloads: ${downloads}`);
      await page.reload();
      await page.getByRole('button', { name: 'Generate Export' }).waitFor();
      await page.waitForTimeout(3500);
      assert(downloads === 1, 'Reload triggered another download');
      await page.getByRole('button', { name: 'History', exact: true }).click();
      assert(
        (await page.getByRole('button', { name: 'Download ZIP' }).count()) ===
          1,
        'History download missing',
      );
    },
  );
  await check(
    'Import validates without writing and requires preview plus typed confirmation',
    async () => {
      await page
        .getByRole('button', { name: 'Import / Restore', exact: true })
        .click();
      await page.getByLabel('Backup file', { exact: true }).setInputFiles({
        name: 'departments.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('id,name\nnew,New department\n'),
      });
      await page
        .getByRole('combobox', {
          name: 'Dataset for an individual legacy file',
        })
        .selectOption('departments');
      await page.getByRole('button', { name: 'Validate backup' }).click();
      await page.getByRole('button', { name: 'Confirm and restore' }).waitFor();
      assert(restores === 0, 'Validation executed a restore');
      assert(
        await page
          .getByRole('button', { name: 'Confirm and restore' })
          .isDisabled(),
        'Missing typed confirmation accepted',
      );
      await page
        .getByRole('combobox', { name: 'Restore behavior' })
        .selectOption('update');
      await page
        .getByRole('checkbox', {
          name: /I authorize provisioning missing users/,
        })
        .check();
      assert(
        (await page
          .getByRole('button', { name: 'Confirm and restore' })
          .count()) === 0,
        'Changed restore behavior reused stale preview',
      );
      await page
        .getByRole('button', { name: 'Validate dependencies & preview impact' })
        .click();
      assert(
        provisionApproved,
        'Explicit provisioning approval did not reach the validated preview',
      );
      await page
        .getByRole('textbox', { name: 'Restore confirmation' })
        .fill('RESTORE');
      await page.getByRole('button', { name: 'Confirm and restore' }).click();
      await page
        .getByText('Restore completed in one transaction.', { exact: false })
        .waitFor();
      assert(restores === 1, 'Restore count incorrect');
    },
  );
  await check('Mobile layout fits the viewport', async () => {
    await page.getByRole('button', { name: 'New Export', exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: path.join(output, 'backup-manager-mobile.png'),
      fullPage: true,
    });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      'Mobile page overflows horizontally',
    );
  });
  await check(
    'Existing import entry points retain the selected file and dataset without automatic restore',
    async () => {
      await page.goto(
        origin + '/checks/backup-manager.fixture.html?entry=legacy',
      );
      await page
        .getByText('Selected file: users.csv', { exact: true })
        .waitFor();
      assert(
        (await page
          .getByRole('combobox', {
            name: 'Dataset for an individual legacy file',
          })
          .inputValue()) === 'users',
        'Legacy dataset was lost',
      );
      assert(
        await page.getByRole('button', { name: 'Validate backup' }).isEnabled(),
        'Selected file was lost',
      );
      assert(
        restores === 1,
        'Opening the existing import entry point triggered a restore',
      );
    },
  );
  await check('No component errors or unintended API mutations', async () => {
    assert(!errors.length, errors.join('\n'));
    assert(!unexpected.length, unexpected.join('\n'));
  });
} finally {
  const report = {
    passed: results.filter((r) => r.status === 'PASS').length,
    failed: results.filter((r) => r.status === 'FAIL').length,
    results,
    errors,
    downloads,
    restores,
  };
  await writeFile(
    path.join(output, 'backup-manager-results.json'),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
}
if (results.some((r) => r.status === 'FAIL')) process.exitCode = 1;
