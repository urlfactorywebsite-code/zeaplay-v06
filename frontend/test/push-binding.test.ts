import test from 'node:test';
import assert from 'node:assert/strict';
import { clearPageNotices, trackBrowserNotice } from '../utils/pushBinding';

test('account scope cleanup closes native notification cards without a service worker', () => {
  let closed = 0;
  trackBrowserNotice({ close() { closed++; } } as Notification);
  clearPageNotices(); clearPageNotices();
  assert.equal(closed, 1);
});

test('native notification tracking is bounded during long sessions', () => {
  let closed = 0;
  for (let i = 0; i < 120; i++) trackBrowserNotice({ close() { closed++; } } as Notification);
  assert.equal(closed, 20);
  clearPageNotices(); assert.equal(closed, 120);
});
