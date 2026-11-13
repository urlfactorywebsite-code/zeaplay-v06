import assert from 'node:assert/strict';
import test, { afterEach } from 'node:test';
import { readFileSync } from 'node:fs';
import { http } from '../services/mockApi';
import { getMcpManagement } from '../services/mcpManagement';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/mcp-management.json', import.meta.url), 'utf8'));
const original = http.defaults.adapter;
afterEach(() => { http.defaults.adapter = original; });
function reply(data: unknown, inspect = (_config: any) => {}) {
  http.defaults.adapter = async config => {
    inspect(config);
    return { config, data, status: 200, statusText: 'OK', headers: {} };
  };
}
const read = () => getMcpManagement(new AbortController().signal, fixture.tenant_context);

test('MCP reads use bounded existing authenticated transport without a tenant selector', async () => {
  reply(fixture, config => {
    assert.equal(config.url, '/mcp-management');
    assert.equal(config.method, 'get');
    assert.equal(config.timeout, 10000);
    assert.equal(config.params, undefined);
  });
  assert.deepEqual(await read(), fixture);
});

for (const [name, change] of [
  ['sixth tool', value => { value.tools.push({ ...value.tools[0], id: 'zeaplay_delete_task', read_only: false }); }],
  ['duplicate tool', value => { value.tools[4] = value.tools[0]; }],
  ['write-capable tool', value => { value.tools[0].read_only = false; }],
  ['unapproved scope', value => { value.tools[0].scope = 'tasks:write'; }],
  ['enabled remote access', value => { value.overview.remote_access_enabled = true; }],
  ['fictional live health', value => { value.overview.health_status = 'healthy'; }],
  ['wrong tool count', value => { value.overview.total_tools = 6; }],
  ['inconsistent enabled tool count', value => { value.overview.enabled_tools = 1; }],
  ['missing configuration', value => { delete value.configuration; }],
  ['unexpected credential field', value => { value.client_secret = 'REVIEW_SYNTHETIC_SECRET'; }],
] as const satisfies ReadonlyArray<readonly [string, (value: any) => void]>) {
  test(`unexpected ${name} response fails closed`, async () => {
    const value = structuredClone(fixture); change(value); reply(value);
    await assert.rejects(read, /MCP configuration response is unavailable or invalid/);
  });
}

test('wrong-tenant response is rejected', async () => {
  reply({ ...fixture, tenant_context: 'b2222222-2222-4222-8222-222222222222' });
  await assert.rejects(read, /tenant context changed/);
});

test('cancelled reads never issue an HTTP request', async () => {
  let calls = 0; reply(fixture, () => calls++);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(() => getMcpManagement(controller.signal, fixture.tenant_context));
  assert.equal(calls, 0);
});
