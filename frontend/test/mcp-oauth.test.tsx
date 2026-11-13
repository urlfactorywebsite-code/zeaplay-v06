import React from 'react';
import assert from 'node:assert/strict';
import test, { afterEach } from 'node:test';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import McpManagementPanel from '../components/McpManagementPanel';
import { validateMcpManagementResponse } from '../utils/mcpManagementResponse';
import { previewMcpConsent, decideMcpConsent } from '../services/mcpConsent';
import { saveMcpPolicy, emergencyDisableMcp, revokeMcpGrant } from '../services/mcpManagement';
import { http } from '../services/mockApi';

const base = JSON.parse(readFileSync(new URL('./fixtures/mcp-management.json', import.meta.url), 'utf8'));
const original = http.defaults.adapter;
afterEach(() => { http.defaults.adapter = original; });
const id = 'a1111111-1111-4111-8111-111111111111';
const stamp = '2026-11-13T00:00:00+00:00';
const preview = { request_id: id, client_name: 'Isolated test client', tenant_context: base.tenant_context,
  scopes: ['tasks:read'], tools: ['zeaplay_list_tasks'], csrf: 'a'.repeat(43), expires_at: stamp };
function isolated() {
  const value = structuredClone(base);
  value.configuration = { available:true, persisted:true, blocker:'', enabled:true, read_only:true,
    allowed_tool_ids:value.tools.map(t => t.id), allowed_roles:['user'], emergency_disabled:false, revision:1, isolated:true };
  value.tools.forEach(t => { t.enabled=true; t.available=true; });
  Object.assign(value.overview, { service_status:'isolated_configured', enabled_tools:5, active_connections:1,
    security_mode:'Read-only / isolated OAuth', endpoint:'http://127.0.0.1:8791/mcp' });
  value.connections = { available:true, total:1, reason:'Isolated fixture only', items:[{ id, client_id:'local-test', user_id:'fixture-user',
    scopes:['tasks:read'], status:'active', created_at:stamp, expires_at:stamp, revoked_at:null }] };
  value.activity = { available:true, reason:'Audit fixture only', items:[{ id, event:'consent_approved', outcome:'success',
    tool_id:null, grant_id:id, correlation_id:id, occurred_at:stamp }] };
  return value;
}
function reply(data: unknown, inspect = (_config: any) => {}) {
  http.defaults.adapter = async config => { inspect(config); return { config, data, status:200, statusText:'OK', headers:{} }; };
}

test('explicit isolated state validates and renders real grant/audit shapes', () => {
  const data = validateMcpManagementResponse(isolated(), base.tenant_context);
  for (const section of ['Connections','Activity Logs','Permissions','Tools'] as const) {
    const html = renderToStaticMarkup(<McpManagementPanel data={data} initialSection={section} onReload={() => {}}
      onSave={async () => {}} onEmergency={async () => {}} onRevoke={async () => {}} />);
    assert.match(html, /Remote MCP access is blocked/);
    assert.doesNotMatch(html, /mcp_at\.|mcp_rt\.|mcp_dt\.|client_secret/);
    if (section === 'Connections') { assert.match(html, /Revoke grant/); assert.equal((html.match(/Connect unavailable/g)||[]).length,5); }
    if (section === 'Activity Logs') assert.match(html, /consent_approved/);
    if (section === 'Permissions') assert.match(html, /Save isolated policy/);
    if (section === 'Tools') assert.equal((html.match(/disabled=""/g)||[]).length,0);
  }
});
for (const [name, change] of [
  ['production endpoint', v => { v.overview.endpoint='https://production.invalid/mcp'; }],
  ['missing isolated gate', v => { delete v.configuration.isolated; }],
  ['readonly disabled', v => { v.configuration.read_only=false; }],
  ['sixth policy tool', v => { v.configuration.allowed_tool_ids.push('zeaplay_write_task'); }],
  ['active production remote', v => { v.overview.remote_access_enabled=true; }],
  ['wrong enabled count', v => { v.overview.enabled_tools=4; }],
  ['inconsistent tool availability', v => { v.tools[0].available=false; }],
  ['credential in grant', v => { v.connections.items[0].access_token='synthetic-secret'; }],
  ['credential in audit', v => { v.activity.items[0].token='synthetic-secret'; }],
  ['unknown grant status', v => { v.connections.items[0].status='connected_to_production'; }],
] as const satisfies ReadonlyArray<readonly [string, (v:any) => void]>) {
  test('isolated response rejects '+name, () => { const value=isolated(); change(value);
    assert.throws(() => validateMcpManagementResponse(value, base.tenant_context), /unavailable or invalid/); });
}
test('emergency lock renders disabled policy while preserving revoke', () => {
  const value=isolated(); value.configuration.emergency_disabled=true; value.configuration.enabled=false;
  value.overview.enabled_tools=0; value.overview.active_connections=0; value.tools.forEach(t => { t.available=false; });
  const data=validateMcpManagementResponse(value, base.tenant_context);
  const html=renderToStaticMarkup(<McpManagementPanel data={data} initialSection="Permissions" onReload={() => {}} onSave={async()=>{}} />);
  assert.match(html, /fieldset disabled=""/); assert.match(html, /Emergency lock is active/);
});
test('consent preview uses authenticated transport and browser cookie without identity selectors', async () => {
  reply(preview, config => { assert.equal(config.url,`/mcp-oauth/requests/${id}/preview`);
    assert.equal(config.withCredentials,true); assert.equal(config.timeout,10000); assert.equal(config.data,'{}'); });
  assert.deepEqual(await previewMcpConsent(id,new AbortController().signal),preview);
});
test('consent rejects invalid identifiers before transport', async () => {
  let calls=0; reply(preview,()=>calls++);
  await assert.rejects(() => previewMcpConsent('../arbitrary',new AbortController().signal)); assert.equal(calls,0);
});
test('consent rejects mismatched request and secret fields', async () => {
  for (const value of [{...preview,request_id:'b2222222-2222-4222-8222-222222222222'}, {...preview,access_token:'synthetic'}]) {
    reply(value); await assert.rejects(() => previewMcpConsent(id,new AbortController().signal),/unavailable/);
  }
});
test('consent decision sends only explicit consent and ephemeral CSRF', async () => {
  reply({redirect_uri:'http://127.0.0.1:8999/callback?code=synthetic&state=synthetic'}, config => {
    assert.deepEqual(JSON.parse(config.data),{approve:false,csrf:preview.csrf}); assert.equal(config.withCredentials,true);
  });
  assert.match(await decideMcpConsent(id,preview.csrf,false),/^http:\/\/127\.0\.0\.1:8999\/callback/);
});
for (const redirect of ['https://external.invalid/cb','javascript:alert(1)','http://user:pass@127.0.0.1:8999/cb','http://127.0.0.1:8999/cb#fragment']) {
  test('consent rejects non-isolated callback '+redirect.split(':')[0],async () => {
    reply({redirect_uri:redirect}); await assert.rejects(() => decideMcpConsent(id,preview.csrf,true));
  });
}
test('management writes use existing transport and no tenant or credential fields', async () => {
  const calls:any[]=[]; reply({},config=>calls.push(config));
  await saveMcpPolicy({enabled:true,read_only:true,allowed_tool_ids:['zeaplay_list_tasks'],allowed_roles:['user'],reason:'Isolated',expected_revision:1});
  await emergencyDisableMcp('Isolated stop'); await revokeMcpGrant(id);
  assert.deepEqual(calls.map(c=>c.method),['patch','post','post']);
  for (const config of calls) { assert.equal(config.timeout,10000); assert.doesNotMatch(config.data,/tenant_id|access_token|refresh_token/); }
});
