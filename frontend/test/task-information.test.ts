import test from 'node:test';
import assert from 'node:assert/strict';
import { QueryClient } from '@tanstack/react-query';
import api from '../services/mockApi';
import { formatInformationTime, informationLastPage, informationScope, informationZone, isInformationTimestamp, taskInformationQueryOptions } from '../utils/taskInformation';
import type { TaskInformation } from '../types/taskInformation';

const frame = (values: Partial<TaskInformation> = {}) => ({ viewer_id: 'owner', task_id: 'task', section: 'overview', items: [], ...values } as TaskInformation);

test('rapid section revisits and concurrent observers share the authorized cache; invalidation refreshes it', async () => {
  const original = api.getTaskInformation;
  const client = new QueryClient();
  let requests = 0;
  api.getTaskInformation = async () => { requests++; return frame(); };
  const scope = ['task-information', 'synthetic-owner', 'task'];
  const options = taskInformationQueryOptions(scope, 'task', { section: 'overview', page: 1 }, 'owner');
  try {
    await Promise.all([client.fetchQuery(options), client.fetchQuery(options)]);
    await client.fetchQuery(options);
    assert.equal(requests, 1);
    await client.invalidateQueries({ queryKey: scope, refetchType: 'none' });
    await client.fetchQuery(options);
    assert.equal(requests, 2);
    assert.equal(options.refetchOnReconnect, false);
    assert.equal(options.refetchOnWindowFocus, false);
  } finally { api.getTaskInformation = original; client.clear(); }
});

test('viewer, task and section mismatches fail closed instead of entering a successful query cache', async () => {
  const original = api.getTaskInformation;
  try {
    for (const bad of [{ viewer_id: 'other-account' }, { task_id: 'other-task' }, { section: 'points' as const }]) {
      const client = new QueryClient();
      api.getTaskInformation = async () => frame(bad);
      const options = taskInformationQueryOptions(['private-scope'], 'task', { section: 'overview', page: 1 }, 'owner');
      await assert.rejects(client.fetchQuery(options), /identity changed/);
      assert.equal(client.getQueryData(options.queryKey), undefined);
      client.clear();
    }
  } finally { api.getTaskInformation = original; }
});

test('cancelling a closing modal aborts a pending read and retains no result', async () => {
  const original = api.getTaskInformation;
  const client = new QueryClient();
  let aborted = false;
  api.getTaskInformation = (_task, _options, signal) => new Promise((_resolve, reject) => {
    signal!.addEventListener('abort', () => { aborted = true; reject(new Error('Aborted')); }, { once: true });
  });
  const options = taskInformationQueryOptions(['close-scope'], 'task', { section: 'overview', page: 1 }, 'owner');
  try {
    const pending = client.fetchQuery(options).catch(() => undefined);
    await client.cancelQueries({ queryKey: ['close-scope'] });
    client.removeQueries({ queryKey: ['close-scope'] });
    await pending;
    assert.equal(aborted, true);
    assert.equal(client.getQueryData(options.queryKey), undefined);
  } finally { api.getTaskInformation = original; client.clear(); }
});

test('timezone formatting preserves DST repeated instants, fractional seconds and explicit UTC fallback', () => {
  assert.equal(formatInformationTime('2026-11-01T05:30:00Z', 'America/New_York'), '2026-11-01 01:30:00 EDT');
  assert.equal(formatInformationTime('2026-11-01T06:30:00Z', 'America/New_York'), '2026-11-01 01:30:00 EST');
  assert.equal(formatInformationTime('2026-11-02T10:00:00.123456Z', 'Asia/Kolkata'), '2026-11-02 15:30:00.123456 GMT+5:30');
  assert.equal(informationZone('invalid/zone'), 'UTC');
  assert.equal(formatInformationTime(null, 'UTC'), 'Not recorded');
  assert.equal(isInformationTimestamp('actual_start_at', '2026-11-02T10:00:00Z'), true);
  assert.equal(isInformationTimestamp('planned_start_date', '2026-11-02'), false);
  assert.equal(isInformationTimestamp('note', '2026-11-02T10:00:00Z'), false);
  assert.equal(informationLastPage(0, 25), 1);
});

test('role, department and activation changes cannot reuse an earlier authorized snapshot', () => {
  const client = new QueryClient();
  const user = { id: 'owner', role: 'owner', departmentId: 'team', status: 'active' };
  const options = { section: 'overview' as const, page: 1 };
  client.setQueryData([...informationScope('task', user), options], frame());
  try {
    for (const change of [{ role: 'user' }, { departmentId: 'other-team' }, { status: 'deactivated' }]) {
      assert.equal(client.getQueryData([...informationScope('task', { ...user, ...change }), options]), undefined);
    }
  } finally { client.clear(); }
});
