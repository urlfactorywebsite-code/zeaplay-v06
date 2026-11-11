import test from 'node:test';
import assert from 'node:assert/strict';
import { notificationDelivery, knownNotificationIds, rememberNotifications } from '../utils/notificationAlerts';
import { activityWarning } from '../utils/taskActivity';
import type { ActivitySnapshot } from '../types/taskActivity';

test('blocked and unsupported browsers preserve independent sound preference', () => {
  for (const permission of ['denied', 'default', 'unsupported'] as const) {
    assert.deepEqual(notificationDelivery({ pushEnabled: true, soundEnabled: false, quiet: false }, permission, true), { browser: false, sound: false });
  }
  assert.deepEqual(notificationDelivery({ pushEnabled: false, soundEnabled: true, quiet: false }, 'denied', true), { browser: false, sound: true });
});
test('quiet hours suppress sound and browser while granted permission alone is insufficient', () => {
  assert.deepEqual(notificationDelivery({ pushEnabled: true, soundEnabled: true, quiet: true }, 'granted', true), { browser: false, sound: false });
  assert.deepEqual(notificationDelivery({ pushEnabled: false, soundEnabled: false, quiet: false }, 'granted', true), { browser: false, sound: false });
  assert.deepEqual(notificationDelivery({ pushEnabled: true, soundEnabled: true, quiet: false }, 'granted', false), { browser: true, sound: false });
});
test('header warning follows configured overtime threshold and remaining capacity', () => {
  const frame = { active_count: 1, limit: 5, workload: { near_deadline: [], overdue_tasks: [], overdue_subtasks: [],
    overtime_seconds: 600, overtime_threshold_seconds: 900, overlap_seconds: 0,
    estimated_remaining_seconds: 1000, remaining_capacity_seconds: 2000 } } as ActivitySnapshot;
  assert.equal(activityWarning(frame), false);
  frame.workload.estimated_remaining_seconds = 2001;
  assert.equal(activityWarning(frame), true);
  frame.workload.remaining_capacity_seconds = null;
  assert.equal(activityWarning(frame), false);
  frame.workload.overtime_seconds = 901;
  assert.equal(activityWarning(frame), true);
});

test('blocked or corrupt optional storage does not replay seen alerts in the same page', () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  try {
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } } });
    rememberNotifications('blocked-user', ['one']);
    assert.deepEqual([...knownNotificationIds('blocked-user')], ['one']);
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => '{broken', setItem() {} } });
    rememberNotifications('corrupt-user', ['two']);
    assert.deepEqual([...knownNotificationIds('corrupt-user')], ['two']);
  } finally { if (original) Object.defineProperty(globalThis, 'localStorage', original); else delete (globalThis as any).localStorage; }
});
