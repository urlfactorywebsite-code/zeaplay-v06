import test from 'node:test';
import assert from 'node:assert/strict';
import { activityWarning, elapsedSeconds, fiveSlots, validateActivitySubject, workDuration } from '../utils/taskActivity';
import type { ActivityContext, ActivitySnapshot } from '../types/taskActivity';
import { createActivityClock } from '../utils/activityClock';
import { coalesceActivityRefresh } from '../utils/activityRefresh';
import { taskReconnectDelay } from '../utils/taskSocket';

const row = (values: Partial<ActivityContext> = {}): ActivityContext => ({
  id: 'context', task_id: 'task', subtask_id: 'sub', task_title: 'Task', subtask_title: 'Sub', priority: 'HIGH',
  status: 'RUNNING', task_status: 'IN_PROGRESS', subtask_status: 'IN_PROGRESS', slot: 1, version: 1,
  elapsed_seconds: 90, elapsed_ms: 90000, resumed_at: '2026-11-02T10:00:00Z', productive_seconds: 0,
  subtask_elapsed_seconds: 30, subtask_productive_seconds: 0, actual_start_at: null, actual_end_at: null,
  deadline: null, can_start: true, ...values,
});
const frame = (contexts: ActivityContext[]): ActivitySnapshot => ({ user_id: 'owner', user_name: 'Owner', read_only: false,
  server_now: '2026-11-02T10:00:00Z', timezone: 'UTC', active_count: contexts.filter(x => x.status === 'RUNNING').length,
  limit: 5, contexts, workload: { period_start: '', period_end: '', manual_seconds: 0, overlap_seconds: 0,
    estimated_remaining_seconds: 0, unestimated_tasks: 0, capacity_seconds: null, overtime_seconds: null,
    capacity_note: null, near_deadline: [], overdue_tasks: [], overdue_subtasks: [], near_deadline_window_hours: 24 } });

test('one monotonic clock advances parent and selected-subtask elapsed without productive time', () => {
  assert.equal(elapsedSeconds(row(), 1000, 6000), 95);
  assert.equal(elapsedSeconds(row(), 1000, 6000, true), 35);
  assert.equal(row().productive_seconds, 0);
  assert.equal(elapsedSeconds(row(), 6000, 1000), 90);
});
test('pause and completion freeze elapsed through refresh and clock changes', () => {
  for (const status of ['PAUSED', 'COMPLETED', 'STOPPED'] as const) assert.equal(elapsedSeconds(row({ status }), 0, 999999), 90);
});
test('popup always renders five possible slots; paused work has no slot', () => {
  const slots = fiveSlots(frame([row({ slot: 3 }), row({ id: 'paused', task_id: 'other', slot: null, status: 'PAUSED' })]));
  assert.equal(slots.length, 5);
  assert.equal(slots.filter(x => x.context).length, 1);
  assert.equal(slots[2].context?.id, 'context');
});
test('server full-capacity, deadline and overlap warnings remain separate from manual work', () => {
  assert.equal(activityWarning(frame([])), false);
  const full = frame(Array.from({ length: 5 }, (_, i) => row({ id: String(i), slot: i + 1 })));
  assert.equal(activityWarning(full), true);
  const overlap = frame([]); overlap.workload.overlap_seconds = 1;
  assert.equal(activityWarning(overlap), true);
});
test('long parallel elapsed totals are displayed without a new daily cap', () => {
  assert.equal(workDuration(100 * 3600 + 61), '100:01:01');
  assert.equal(workDuration(-1), '0:00:00');
});

test('one shared render clock serves 100 subscribers and cleans up while hidden', () => {
  let time = 1000, hidden = false, nextId = 0, visibility: (() => void) | undefined;
  const timers = new Map<number, () => void>();
  const clock = createActivityClock({ now: () => time, hidden: () => hidden,
    every: fn => { timers.set(++nextId, fn); return nextId; },
    clear: id => { timers.delete(id as number); },
    onVisibility: fn => { visibility = fn; return () => { visibility = undefined; }; },
  });
  let updates = 0;
  const off = Array.from({ length: 100 }, () => clock.subscribe(() => { updates++; }));
  assert.equal(timers.size, 1);
  updates = 0; time = 2000;
  timers.values().next().value!();
  assert.equal(updates, 100); assert.equal(clock.getSnapshot(), 2000);
  hidden = true; visibility!(); assert.equal(timers.size, 0);
  time = 7200000; hidden = false; visibility!();
  assert.equal(timers.size, 1); assert.equal(clock.getSnapshot(), time);
  for (const unsubscribe of off) unsubscribe();
  assert.equal(timers.size, 0); assert.equal(visibility, undefined);
});

test('activity event bursts coalesce and canceled refreshes cannot fire after unmount', () => {
  let run = 0, nextId = 0;
  const timers = new Map<number, () => void>();
  const refresh = coalesceActivityRefresh(() => { run++; }, {
    later: fn => { timers.set(++nextId, fn); return nextId; }, clear: id => { timers.delete(id); },
  });
  for (let i = 0; i < 100; i++) refresh.request();
  assert.equal(timers.size, 1);
  const fn = timers.values().next().value!; timers.clear(); fn();
  assert.equal(run, 1);
  refresh.request(); refresh.cancel(); assert.equal(timers.size, 0);
});

test('reconnect backoff is jittered and bounded without retry-count overflow', () => {
  assert.equal(taskReconnectDelay(0, 0), 750);
  assert.equal(taskReconnectDelay(0, 1), 1250);
  assert.equal(taskReconnectDelay(1, .5), 2000);
  assert.equal(taskReconnectDelay(100000, .5), 15000);
  assert.notEqual(taskReconnectDelay(3, .1), taskReconnectDelay(3, .9));
});

test('browser wall-clock drift cannot change server elapsed or productive work', () => {
  const original = Date.now;
  try {
    Date.now = () => original() + 24 * 60 * 60 * 1000;
    assert.equal(elapsedSeconds(row(), 1000, 6000), 95);
    Date.now = () => 0;
    assert.equal(elapsedSeconds(row(), 1000, 6000), 95);
    assert.equal(row().productive_seconds, 0);
  } finally { Date.now = original; }
});

test('capacity alert uses the authoritative personal count, including capacity overflow', () => {
  const value = frame([row({ status: 'PAUSED', slot: null })]);
  assert.equal(activityWarning(value), false);
  value.active_count = 6;
  assert.equal(activityWarning(value), true);
});

test('another tab switching accounts cannot install a different subject snapshot', () => {
  const value = frame([]);
  assert.equal(validateActivitySubject(value, 'owner'), value);
  assert.throws(() => validateActivitySubject(value, 'other-account'), /Account changed/);
});


test('slow activity reads keep one pending refresh instead of abort/refetch storms', async () => {
  const jobs = new Map<number,()=>void>(); let id=0,runs=0,release!:()=>void;
  const q=coalesceActivityRefresh(()=>{runs++;return new Promise<void>(resolve=>{release=resolve;});},{later:fn=>{jobs.set(++id,fn);return id;},clear:key=>{jobs.delete(key);}});
  const fire=()=>{const [key,fn]=jobs.entries().next().value!;jobs.delete(key);fn();};
  for(let i=0;i<100;i++)q.request();fire();
  for(let i=0;i<1000;i++)q.request();
  assert.equal(runs,1);assert.equal(jobs.size,0);
  release();await Promise.resolve();assert.equal(jobs.size,1);
  fire();assert.equal(runs,2);q.cancel();release();await Promise.resolve();assert.equal(jobs.size,0);
});

test('cleanup during an asynchronous refresh prevents a late follow-up', async () => {
  let scheduled:(()=>void)|undefined,release!:()=>void;
  const q=coalesceActivityRefresh(()=>new Promise<void>(resolve=>{release=resolve;}),{later:fn=>{scheduled=fn;return 1;},clear:()=>{scheduled=undefined;}});
  q.request();const first=scheduled!;scheduled=undefined;first();q.request();q.cancel();
  release();await Promise.resolve();assert.equal(scheduled,undefined);
});
