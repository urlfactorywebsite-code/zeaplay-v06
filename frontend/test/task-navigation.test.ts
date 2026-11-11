import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { TASK_TABS, LEGACY_TASK_ROUTES, taskTabForPath, taskDetailIdFromPath, updateTaskFilter } from '../utils/taskNavigation';
import { navigationPage, validateNavigationPolicy } from '../utils/navigationAccess';
import { calendarDateKey, taskDeadlineDateKey, parseTaskDate, resolveTaskTimezone, taskWallTimeToUtc, calendarToday, taskTimelineRange } from '../utils/taskCalendarDates';
import type { NavigationPolicy } from '../types/navigation';

const registry = JSON.parse(readFileSync(new URL('../checks/navigation-registry.fixture.json', import.meta.url), 'utf8'));
const policy = (): NavigationPolicy => ({tenantId:'fixture',version:0,updatedAt:null,updatedBy:null,roles:['owner','user'],canManage:true,canChangeAccess:true,
  pages:registry.map(page=>({...page,enabled:true,hidden:false,allowedRoles:page.permittedRoles,access:'allowed',visible:true}))});

test('four task routes keep /tasks canonical and map every legacy bookmark',()=>{
  assert.deepEqual(TASK_TABS.map(tab=>tab.path),['/tasks','/tasks/kanban','/tasks/gantt','/tasks/calendar']);
  for(const [old,path] of Object.entries(LEGACY_TASK_ROUTES)) {
    assert.ok(taskTabForPath(path));
    assert.equal(navigationPage(policy(),old,'?priority=HIGH')?.route,path);
  }
  assert.equal(taskTabForPath('/TASKS/%6banban/')?.key,'kanban');
  assert.equal(taskTabForPath('/tasks/unknown'),undefined);
});

test('the protected default task tab owns /tasks route authorization',()=>{
  const value=policy();
  assert.equal(validateNavigationPolicy(value),value);
  assert.equal(navigationPage(value,'/tasks','')?.id,'tasks.list');
  assert.equal(value.pages.find(page=>page.id==='tasks.list')?.isSystemProtected,true);
  assert.equal(value.pages.filter(page=>['tasks','kanban','gantt','calendar'].includes(page.id)&&page.navigationLocation==='sidebar').length,1);
  value.pages.find(page=>page.id==='gantt')!.access='forbidden';
  assert.equal(navigationPage(value,'/tasks/gantt','')?.access,'forbidden');
});

test('only the parent/default task pair may share a registry route',()=>{
  const value=policy();
  value.pages.find(page=>page.id==='calendar')!.route='/tasks';
  assert.throws(()=>validateNavigationPolicy(value));
  const incomplete=policy(); incomplete.pages=incomplete.pages.filter(page=>page.id!=='tasks.list');
  assert.throws(()=>validateNavigationPolicy(incomplete));
});

test('shared filters preserve unrelated query values and clearing removes only its filter',()=>{
  const next=updateTaskFilter('?taskId=bookmark&priority=HIGH&search=design','status','IN_PROGRESS');
  const query=new URLSearchParams(next);
  assert.equal(query.get('taskId'),'bookmark');assert.equal(query.get('priority'),'HIGH');assert.equal(query.get('search'),'design');
  const cleared=new URLSearchParams(updateTaskFilter(next,'status','ALL'));
  assert.equal(cleared.get('status'),null);assert.equal(cleared.get('taskId'),'bookmark');
});

test('calendar civil days never shift when local midnight differs from UTC',()=>{
  const previous=process.env.TZ;
  try {
    for(const zone of ['Asia/Kolkata','Pacific/Auckland','America/Los_Angeles']) {
      process.env.TZ=zone;
      assert.equal(calendarDateKey(new Date(2026,9,29,0,0)),'2026-10-29');
      assert.equal(taskDeadlineDateKey('2026-10-29T23:59:59'),'2026-10-29');
      assert.equal(taskDeadlineDateKey('2026-10-29T00:30:00+05:30'),'2026-10-28');
    }
  } finally { if(previous===undefined)delete process.env.TZ;else process.env.TZ=previous; }
});

test('profile timezone overrides browser grouping and naive deadlines are UTC', () => {
  assert.equal(resolveTaskTimezone('Asia/Kolkata'), 'Asia/Kolkata');
  assert.equal(taskDeadlineDateKey('2026-10-29T18:30:00', 'Asia/Kolkata'), '2026-10-30');
  assert.equal(taskDeadlineDateKey('2026-10-29T06:30:00Z', 'America/Los_Angeles'), '2026-10-28');
  assert.equal(parseTaskDate('2026-10-29 18:30:00').toISOString(), '2026-10-29T18:30:00.000Z');
  assert.equal(calendarDateKey(calendarToday('Asia/Kolkata', new Date('2026-10-29T18:30:00Z'))), '2026-10-30');
  assert.doesNotThrow(() => resolveTaskTimezone('Invalid/Zone'));
});

test('calendar scheduling converts wall times and rejects a nonexistent DST time', () => {
  assert.equal(taskWallTimeToUtc('2026-10-30T00:00', 'Asia/Kolkata'), '2026-10-29T18:30:00.000Z');
  assert.equal(taskWallTimeToUtc('2026-03-08T00:00', 'America/New_York'), '2026-03-08T05:00:00.000Z');
  assert.throws(() => taskWallTimeToUtc('2026-03-08T02:30', 'America/New_York'));
  assert.equal(taskWallTimeToUtc('2026-11-01T23:59', 'America/New_York'), '2026-11-02T04:59:00.000Z');
});

test('notification task deep links recognize UUIDs without accepting unknown tab names', () => {
  const id = '12345678-1234-1234-1234-123456789012';
  assert.equal(taskDetailIdFromPath(`/tasks/${id}`), id);
  assert.equal(taskDetailIdFromPath('/tasks/unknown'), undefined);
  assert.equal(taskDetailIdFromPath('/tasks/../users'), undefined);
});

test('Gantt uses civil-day intervals across midnight/DST and retains reversed recorded dates', () => {
  const midnight = taskTimelineRange('2026-10-29T18:29:00Z', '2026-10-29T18:31:00Z', 'Asia/Kolkata');
  assert.equal(midnight.end - midnight.start, 1);
  const dst = taskTimelineRange('2026-03-08T05:00:00Z', '2026-03-09T03:59:00Z', 'America/New_York');
  assert.equal(dst.end - dst.start, 0);
  const reversed = taskTimelineRange('2026-10-30T12:00:00Z', '2026-10-29T10:00:00Z', 'UTC');
  assert.equal(reversed.dueBeforeCreation, true);
  assert.equal(reversed.end - reversed.start, 1);
});
