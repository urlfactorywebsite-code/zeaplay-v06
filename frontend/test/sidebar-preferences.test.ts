import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { applySidebarPreferences, legacySidebarStorageKey, migrateSidebarPreferences, parseSidebarPreferences, readSidebarPreferences, sidebarStorageKey } from '../utils/sidebarPreferences';
import type { NavigationPage } from '../types/navigation';
import { SETTINGS_TABS } from '../utils/settingsNavigation';

const pages = JSON.parse(readFileSync(new URL('../checks/navigation-registry.fixture.json', import.meta.url), 'utf8')) as NavigationPage[];

test('every Settings route has one authoritative server definition', () => {
  const settings = pages.filter(page => page.navigationLocation === 'settings-tab');
  assert.equal(settings.length, SETTINGS_TABS.length);
  for (const tab of SETTINGS_TABS) {
    const server = settings.find(page => page.route === tab.path)!;
    assert.ok(server);
    assert.ok(server.permittedRoles.length > 0);
  }
});

test('migration preserves labels, order and unknown IDs without mutating legacy storage', () => {
  const legacy = JSON.stringify({ order: ['/reports', '/tasks', '/logs', 'future-page'], labels: { '/reports': 'My Reports', '/tasks': 'Work', '/logs': 'History', 'future-page': 'Future' } });
  const result = migrateSidebarPreferences(legacy, pages);
  assert.deepEqual(result.order, ['reports', 'tasks', 'settings.logs', 'future-page']);
  assert.equal(result.labels['settings.logs'], 'History');
  const data = new Map([[legacySidebarStorageKey('tenant-a', 'owner-a'), legacy]]);
  const storage = { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value); } };
  assert.deepEqual(readSidebarPreferences(storage, 'tenant-a', 'owner-a', pages), result);
  assert.equal(data.get(legacySidebarStorageKey('tenant-a', 'owner-a')), legacy);
  assert.equal(readSidebarPreferences(storage, 'tenant-b', 'owner-a', pages).order.length, 0);
  assert.equal(readSidebarPreferences(storage, 'tenant-a', 'owner-b', pages).order.length, 0);
  storage.setItem(sidebarStorageKey('tenant-a', 'owner-a'), JSON.stringify({ order: ['tickets'], labels: { tickets: 'Service' } }));
  assert.equal(readSidebarPreferences(storage, 'tenant-a', 'owner-a', pages).labels.tickets, 'Service');
});

test('malformed preferences are ignored and invalid names cannot enter navigation', () => {
  assert.deepEqual(parseSidebarPreferences('{bad'), { order: [], labels: {} });
  const parsed = parseSidebarPreferences(JSON.stringify({ order: ['tasks', 'tasks', 3], labels: { tasks: ' Work ', tickets: ' ', calendar: 'x'.repeat(49), reports: 4 } }));
  assert.deepEqual(parsed.order, ['tasks']);
  assert.deepEqual(Object.entries(parsed.labels), [['tasks', 'Work']]);
});

test('applying preferences never introduces absent or forbidden pages and never duplicates entries', () => {
  const allowed = pages.filter(page => ['tasks', 'tickets'].includes(page.id));
  const preferences = { order: ['reports', 'tickets', 'tickets'], labels: { tickets: 'Help Desk', reports: 'Private' } };
  assert.deepEqual(applySidebarPreferences(allowed, preferences).map(page => [page.id, page.label]), [['tickets', 'Help Desk'], ['tasks', 'All Tasks']]);
});

test('read-only storage preserves readable legacy names and ordering', () => {
  const legacy = JSON.stringify({ order: ['/tasks'], labels: { '/tasks': 'Keep My Work' } });
  const storage = { getItem: (key: string) => key.includes('v1:') ? legacy : null, setItem: () => { throw new Error('quota'); } };
  const migrated = readSidebarPreferences(storage, 'tenant', 'owner', pages);
  assert.equal(migrated.labels.tasks, 'Keep My Work');
  assert.deepEqual(migrated.order, ['tasks']);
});
