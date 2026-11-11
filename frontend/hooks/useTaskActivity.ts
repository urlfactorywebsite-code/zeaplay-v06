import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/mockApi';
import { getAccessToken } from '../services/tokenStorage';
import { useAuth } from './useAuth';
import { APP_REFRESH_EVENT } from '../utils/appEvents';
import { TASKS_CHANGED_EVENT } from '../utils/taskEvents';
import { TASK_ACTIVITY_CHANGED, validateActivitySubject } from '../utils/taskActivity';
import { coalesceActivityRefresh } from '../utils/activityRefresh';
import type { ActivitySnapshot } from '../types/taskActivity';

export interface ActivitySample { frame: ActivitySnapshot; receivedAt: number }
export function useTaskActivity(enabled: boolean, userId?: string, connected = false) {
  const { user } = useAuth();
  const client = useQueryClient();
  const identity = `${getAccessToken()}:${user?.id}:${user?.role}`;
  const subject = userId || user?.id;
  const key = useMemo(() => ['task-activity', identity, subject], [identity, subject]);
  const [recoveryInterval] = useState(() => 30_000 + Math.floor(Math.random() * 5000));
  const query = useQuery({ queryKey: key, enabled: enabled && !!user,
    queryFn: async ({ signal }): Promise<ActivitySample> => ({ frame: validateActivitySubject(await api.getTaskActivity(userId, signal), subject), receivedAt: performance.now() }),
    staleTime: 0, refetchOnWindowFocus: false, refetchOnReconnect: false,
    // Healthy sessions use the shared stream. One aggregate recovery request
    // remains available when that stream is disconnected.
    refetchInterval: connected ? false : recoveryInterval, refetchIntervalInBackground: false, retry: 1,
  });
  const queued = useMemo(() => coalesceActivityRefresh(() =>
    client.invalidateQueries({ queryKey: key, exact: true }, { cancelRefetch: false })
  ), [client, key]);
  const refresh = useCallback(() => queued.request(), [queued]);
  useEffect(() => {
    if (!enabled || !query.data) return;
    // The local work day may end without a task event. Refetch once at that
    // boundary, using server time plus monotonic elapsed time, not clock polling.
    const frame = query.data.frame;
    const remaining = Date.parse(frame.workload.period_end) - Date.parse(frame.server_now)
      - Math.max(0, performance.now() - query.data.receivedAt);
    if (!Number.isFinite(remaining)) return;
    const timer = window.setTimeout(refresh, Math.max(0, remaining) + 25);
    return () => window.clearTimeout(timer);
  }, [enabled, query.data, refresh]);
  useEffect(() => {
    if (!enabled) return;
    const changed = (event: Event) => {
      const affected = (event as CustomEvent<{ userId?: string }>).detail?.userId;
      if (!document.hidden && (!affected || affected === subject)) refresh();
    };
    const visible = () => { if (!document.hidden) refresh(); };
    const names = [TASKS_CHANGED_EVENT, APP_REFRESH_EVENT, 'online', 'focus'];
    window.addEventListener(TASK_ACTIVITY_CHANGED, changed);
    for (const name of names) window.addEventListener(name, visible);
    document.addEventListener('visibilitychange', visible);
    return () => {
      queued.cancel();
      window.removeEventListener(TASK_ACTIVITY_CHANGED, changed);
      for (const name of names) window.removeEventListener(name, visible);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [enabled, refresh, queued, subject]);
  const accept = (frame: ActivitySnapshot) => {
    validateActivitySubject(frame, subject);
    queued.cancel();
    // Abort stale in-flight GETs before installing the committed mutation frame.
    void client.cancelQueries({ queryKey: key, exact: true });
    client.setQueryData<ActivitySample>(key, { frame, receivedAt: performance.now() });
  };
  return { frame: query.isError ? undefined : query.data?.frame, receivedAt: query.data?.receivedAt ?? performance.now(),
    isError: query.isError, error: query.error, refresh, accept };
}
