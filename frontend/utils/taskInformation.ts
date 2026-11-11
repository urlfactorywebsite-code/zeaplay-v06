import { DateTime } from 'luxon';
import api from '../services/mockApi';
import { getAccessToken } from '../services/tokenStorage';
import type { InformationOptions, TaskInformation } from '../types/taskInformation';

export const informationScope = (taskId: string, user?: { id: string; role: string; departmentId?: string | null; status?: string } | null) =>
  ['task-information', user?.id, user?.role, user?.departmentId, user?.status, getAccessToken(), taskId] as const;

export function taskInformationQueryOptions(scope: readonly unknown[], taskId: string, options: InformationOptions, viewerId?: string) {
  const token = getAccessToken();
  return {
    queryKey: [...scope, options],
    queryFn: async ({ signal }: { signal: AbortSignal }): Promise<TaskInformation> => {
      if (getAccessToken() !== token) throw new Error('Account changed while loading task information');
      const data = await api.getTaskInformation(taskId, options, signal);
      if (getAccessToken() !== token || data.viewer_id !== viewerId || data.task_id !== taskId || data.section !== options.section)
        throw new Error('Task information identity changed. Refresh your sign-in.');
      return data;
    },
    enabled: !!viewerId, staleTime: 15_000, gcTime: 60_000, retry: false,
    // One coalesced modal-level recovery path owns all active section/history reads.
    refetchOnWindowFocus: false, refetchOnReconnect: false,
  };
}

export function informationZone(zone?: string) {
  return zone && DateTime.now().setZone(zone).isValid ? zone : 'UTC';
}

export function formatInformationTime(value: string | null, zone: string) {
  if (!value) return 'Not recorded';
  const parsed = DateTime.fromISO(value, { zone: 'utc' }).setZone(zone);
  const fraction = value.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})?$/)?.[1];
  return parsed.isValid ? `${parsed.toFormat('yyyy-LL-dd HH:mm:ss')}${fraction ? `.${fraction}` : ''} ${parsed.toFormat('ZZZZ')}` : value;
}

export const isInformationTimestamp = (key: string, value: unknown): value is string =>
  typeof value === 'string' && /^(?:.*_at|start|end)$/.test(key) && value.includes('T') && DateTime.fromISO(value, { zone: 'utc' }).isValid;

export function informationLastPage(total: number, size: number) { return Math.max(1, Math.ceil(total / size)); }
