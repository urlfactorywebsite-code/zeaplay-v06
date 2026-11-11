import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import type { NavigationPolicy } from '../types/navigation';
import { navigationPage, validateNavigationPolicy } from '../utils/navigationAccess';

const registry = JSON.parse(readFileSync(new URL('../checks/navigation-registry.fixture.json', import.meta.url), 'utf8'));
const fixture = (): NavigationPolicy => ({ tenantId: 'fixture', version: 1, updatedAt: null, updatedBy: null, roles: ['owner', 'admin', 'manager', 'user'], canManage: true, canChangeAccess: true,
  pages: registry.map(page => ({ ...page, enabled: true, hidden: false, allowedRoles: page.permittedRoles, access: 'allowed', visible: true })) });

for (const path of ['/settings/api', '/SETTINGS/API/', '/settings/%61pi', '/api/overview']) {
  test(`canonical and alternate ${path} share the same access decision`, () => {
    const value = fixture();
    value.pages.find(page => page.id === 'settings.api')!.access = 'forbidden';
    assert.equal(navigationPage(value, path, '')?.access, 'forbidden');
  });
}
test('achievement shortcuts and conversation links retain their registry identities', () => {
  assert.equal(navigationPage(fixture(), '/achievements', '?tab=points')?.id, 'points');
  assert.equal(navigationPage(fixture(), '/chat/conversation', '')?.id, 'chat');
});
test('malformed, incomplete and permission-expanding responses fail closed', () => {
  assert.equal(validateNavigationPolicy(fixture()).version, 1);
  for (const mutate of [
    (value: NavigationPolicy) => { value.pages = value.pages.filter(page => page.id !== 'settings.api'); },
    (value: NavigationPolicy) => { value.pages.push(value.pages[0]); },
    (value: NavigationPolicy) => { value.version = -1; },
    (value: NavigationPolicy) => { value.pages.find(page => page.id === 'settings.api')!.allowedRoles = ['user']; },
    (value: NavigationPolicy) => { value.pages[0].access = 'anything' as never; },
  ]) { const value = fixture(); mutate(value); assert.throws(() => validateNavigationPolicy(value)); }
});
