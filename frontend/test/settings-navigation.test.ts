import assert from 'node:assert/strict';
import test from 'node:test';
import { LEGACY_SETTINGS_ROUTES, SETTINGS_TABS } from '../utils/settingsNavigation';

test('every Settings tab has one unique, shareable nested route', () => {
  assert.equal(SETTINGS_TABS.length, 7);
  assert.equal(new Set(SETTINGS_TABS.map((tab) => tab.path)).size, 7);
  for (const tab of SETTINGS_TABS) {
    assert.equal(tab.path, `/settings/${tab.key}`);
  }
});

test('legacy bookmarks point to canonical Settings routes without loops', () => {
  assert.deepEqual(LEGACY_SETTINGS_ROUTES, {
    '/profile': '/settings/profile',
    '/support': '/settings/support',
    '/master-control': '/settings/master-control',
    '/api/overview': '/settings/api',
    '/logs': '/settings/logs',
    '/media': '/settings/media-library',
  });
  for (const target of Object.values(LEGACY_SETTINGS_ROUTES)) {
    assert.ok(SETTINGS_TABS.some((tab) => tab.path === target));
    assert.ok(!(target in LEGACY_SETTINGS_ROUTES));
  }
});
