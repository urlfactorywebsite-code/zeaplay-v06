import assert from 'node:assert/strict';
import test from 'node:test';
import { getAvatarColor, getAvatarInitials, getUserAvatarUrl } from '../utils/userAvatar';
import { getFrameClassName } from '../constants/avatarFrames';
import { Role } from '../types';

test('canonical avatar wins over legacy aliases and empty profiles remain supported', () => {
  assert.equal(getUserAvatarUrl({ avatarAsset: { url: '/avatars/canonical/image' }, profileImageUrl: '/old' }), '/avatars/canonical/image');
  assert.equal(getUserAvatarUrl(null), null);
  assert.equal(getUserAvatarUrl({}), null);
  assert.equal(getUserAvatarUrl({ profileImageUrl: '/legacy' }), '/legacy');
});

test('initials and color are deterministic for empty, single and multiple names', () => {
  assert.equal(getAvatarInitials(' Alice   Johnson '), 'AJ');
  assert.equal(getAvatarInitials('Alice'), 'A');
  assert.equal(getAvatarInitials('  '), '?');
  assert.equal(getAvatarColor('employee-1'), getAvatarColor('employee-1'));
  assert.notEqual(getAvatarColor('employee-1'), getAvatarColor('employee-2'));
});

test('all existing named frames and role frames remain independently available', () => {
  for (const frame of ['classic', 'aurora', 'solar', 'emerald', 'role-ring', 'achievement-glow', 'minimal']) {
    assert.ok(getFrameClassName(frame, Role.USER).length > 0);
  }
  assert.notEqual(getFrameClassName('aurora', Role.USER), getFrameClassName('solar', Role.USER));
});

test('empty aliases fall through and executable avatar URLs are ignored', () => {
  assert.equal(getUserAvatarUrl({ avatarAsset: { url: ' ' }, avatarUrl: '/avatars/new/image' }), '/avatars/new/image');
  for (const value of ['javascript:alert(1)', 'data:image/svg+xml,<svg/>', '//evil.test/x']) {
    assert.equal(getUserAvatarUrl({ avatarUrl: value }), null);
  }
  assert.equal(getUserAvatarUrl({ avatarUrl: 'data:image/png;base64,AA==' }), 'data:image/png;base64,AA==');
});
