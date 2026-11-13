import React from 'react';
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import McpManagementPanel, { MCP_SECTIONS } from '../components/McpManagementPanel';
import type { McpManagementSnapshot } from '../types/mcpManagement';
import type { NavigationPolicy } from '../types/navigation';
import { navigationPage, validateNavigationPolicy } from '../utils/navigationAccess';

const snapshot: McpManagementSnapshot = JSON.parse(readFileSync(new URL('./fixtures/mcp-management.json', import.meta.url), 'utf8'));
const registry = JSON.parse(readFileSync(new URL('../checks/navigation-registry.fixture.json', import.meta.url), 'utf8'));
const render = (section: typeof MCP_SECTIONS[number]) => renderToStaticMarkup(<McpManagementPanel data={snapshot} initialSection={section} onReload={() => {}} />);

for (const section of MCP_SECTIONS) {
  test(`renders ${section} and all six section controls`, () => {
    const html = render(section);
    assert.match(html, new RegExp(`id="mcp-section-title"[^>]*>${section}</h3>`));
    assert.equal((html.match(/aria-pressed="/g) || []).length, 6);
    assert.match(html, /Remote MCP access is blocked/);
    assert.doesNotMatch(html, /type="password"|access_token|client_secret/);
  });
}

test('overview reports unavailable inventory and unmonitored health', () => {
  const html = render('Overview');
  assert.match(html, /Active connections<\/dt><dd[^>]*>Unavailable/);
  assert.match(html, /Enabled tools<\/dt><dd[^>]*>0/);
  assert.match(html, /No live health check has been performed/);
});

test('catalog shows exactly five approved read-only tools with disabled controls', () => {
  const html = render('Tools');
  for (const tool of snapshot.tools) assert.ok(html.includes(tool.id));
  assert.equal((html.match(/type="checkbox"/g) || []).length, 5);
  assert.equal((html.match(/disabled=""/g) || []).length, 5);
  assert.equal((html.match(/>Read-only</g) || []).length, 5);
});

test('connections are pending and cannot be created', () => {
  const html = render('Connections');
  for (const client of ['ChatGPT', 'Claude', 'Cursor', 'VS Code', 'Other MCP-compatible clients']) assert.ok(html.includes(client));
  assert.equal((html.match(/Connect unavailable/g) || []).length, 5);
  assert.equal((html.match(/disabled=""/g) || []).length, 5);
});

test('tenant, role, read-only and emergency controls explain storage blocker', () => {
  const html = render('Permissions');
  assert.match(html, /fieldset disabled=""/);
  assert.match(html, /safe disabled defaults, not saved tenant preferences/);
  assert.match(html, /no emergency stop has been recorded/);
});

test('activity view has no fabricated rows', () => {
  const html = render('Activity Logs');
  assert.match(html, /MCP activity unavailable/);
  assert.doesNotMatch(html, /<table|<tr|Connected successfully/);
});

test('untrusted metadata is escaped', () => {
  const copy = structuredClone(snapshot);
  copy.tools[0].description = '<script>alert(1)</script>';
  const html = renderToStaticMarkup(<McpManagementPanel data={copy} initialSection="Tools" onReload={() => {}} />);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test('MCP deep link uses the server registry and rejects missing registry identity', () => {
  const policy: NavigationPolicy = { tenantId: snapshot.tenant_context, version: 0, updatedAt: null, updatedBy: null,
    roles: ['user', 'manager', 'admin', 'owner'], canManage: true, canChangeAccess: true,
    pages: registry.map(page => ({ ...page, enabled: true, hidden: false, allowedRoles: page.permittedRoles, access: 'allowed', visible: true })) };
  assert.equal(navigationPage(validateNavigationPolicy(policy), '/settings/mcp-management', '')?.id, 'settings.mcp-management');
  policy.pages = policy.pages.filter(page => page.id !== 'settings.mcp-management');
  assert.throws(() => validateNavigationPolicy(policy));
});
