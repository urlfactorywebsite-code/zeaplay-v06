import test from 'node:test';
import assert from 'node:assert/strict';
import { TaskPriority } from '../types';
import { actualTimeOptions, actualTimeToUtc, actualWallTime, mapApiSubtask, plannedDatesError, subtaskCreateRequest, subtaskPriority, subtaskRequest } from '../utils/subtaskWorkflow';

test('creation requires ordered real planned dates', () => {
  assert.ok(plannedDatesError('', '2026-11-02'));
  assert.ok(plannedDatesError('2026-11-03', '2026-11-02'));
  assert.ok(plannedDatesError('2026-02-30', '2026-03-01'));
  assert.equal(plannedDatesError('2026-11-02', '2026-11-02'), '');
});

test('actual times round trip in the configured timezone', () => {
  const utc = actualTimeToUtc('2026-11-02T10:30:00', 'Asia/Kolkata');
  assert.equal(utc, '2026-11-02T05:00:00.000Z');
  assert.equal(actualWallTime(utc, 'Asia/Kolkata'), '2026-11-02T10:30:00');
  assert.equal(actualWallTime(null, 'Asia/Kolkata'), '');
});

test('DST gaps are rejected and repeated hours require explicit offsets', () => {
  assert.throws(() => actualTimeToUtc('2026-03-08T02:30:00', 'America/New_York'), /does not exist/);
  const local = '2026-11-01T01:30:00';
  assert.equal(actualTimeOptions(local, 'America/New_York').length, 2);
  assert.throws(() => actualTimeToUtc(local, 'America/New_York'), /occurs twice/);
  assert.equal(actualTimeToUtc(local, 'America/New_York', '-240'), '2026-11-01T05:30:00.000Z');
  assert.equal(actualTimeToUtc(local, 'America/New_York', '-300'), '2026-11-01T06:30:00.000Z');
});

test('legacy API fields remain present and completion status is derived', () => {
  const old = mapApiSubtask({ id:'old', title:'Historic', completed:true });
  assert.equal(old.status, 'COMPLETED');
  assert.equal(old.managed, false);
  assert.equal(old.actualStartAt, null);
  assert.equal(old.pointPolicyVersion, 'legacy');
});

test('priority inheritance stays dynamic and clearing override restores it', () => {
  const row = { id:'a', title:'A', completed:false, priorityOverride:null };
  assert.equal(subtaskPriority(row, TaskPriority.HIGH), TaskPriority.HIGH);
  assert.equal(subtaskPriority(row, TaskPriority.URGENT), TaskPriority.URGENT);
  assert.equal(subtaskPriority({ ...row, priorityOverride:TaskPriority.LOW }, TaskPriority.URGENT), TaskPriority.LOW);
  assert.equal(subtaskCreateRequest(row).priority_override, null);
});

test('status actions send a concurrency token without manufacturing actual times', () => {
  assert.deepEqual(subtaskRequest({ action:'START', version:3 }), { action:'START', expected_version:3 });
  assert.deepEqual(subtaskRequest({ actualStartAt:null, confirmActualTimes:true, version:4 }), {
    actual_start_at:null, confirm_actual_times:true, expected_version:4,
  });
});
