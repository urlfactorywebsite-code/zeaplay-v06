import assert from 'node:assert/strict';
import test from 'node:test';
import { QueryClient } from '@tanstack/react-query';
import api from '../services/mockApi';
import { TaskStatus } from '../types';
import { taskListQueryOptions } from '../hooks/useTaskCache';

test('task query identity separates accounts/roles and filters while sharing display layouts', () => {
  const params = { page: 2, pageSize: 10, viewMode: 'list' as const };
  assert.deepEqual(taskListQueryOptions(params, 'owner').queryKey, taskListQueryOptions({ ...params, viewMode: 'grid' }, 'owner').queryKey);
  assert.notDeepEqual(taskListQueryOptions(params, 'owner').queryKey, taskListQueryOptions(params, 'user').queryKey);
  assert.notDeepEqual(taskListQueryOptions(params, 'owner').queryKey, taskListQueryOptions({ ...params, status: TaskStatus.IN_PROGRESS }, 'owner').queryKey);
  assert.equal(params.viewMode, 'list');
});

test('adjacent-page prefetch and live consumption share one request and invalidation fetches fresh data', async () => {
  const original = api.getTasksPage;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let requests = 0;
  let release: () => void;
  const response = { items: [], page: 2, pageSize: 10, total: 0, totalPages: 1,
    statusCounts: Object.fromEntries(Object.values(TaskStatus).map(status => [status, 0])) as Record<TaskStatus, number> };
  api.getTasksPage = async () => { requests++; await new Promise<void>(resolve => { release = resolve; }); return response; };
  try {
    const options = taskListQueryOptions({ page: 2, pageSize: 10 }, 'fixture');
    const prefetch = client.prefetchQuery(options);
    const live = client.fetchQuery(options);
    assert.equal(requests, 1);
    release!();
    await Promise.all([prefetch, live]);
    assert.deepEqual(await client.fetchQuery(options), response);
    assert.equal(requests, 1);
    await client.invalidateQueries({ queryKey: ['tasks'], refetchType: 'none' });
    const fresh = client.fetchQuery(options);
    assert.equal(requests, 2);
    release!(); await fresh;
  } finally { api.getTasksPage = original; client.clear(); }
});
