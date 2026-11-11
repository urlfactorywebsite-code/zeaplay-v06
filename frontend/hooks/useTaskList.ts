import { useCallback, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from './useAuth';
import { taskListQueryOptions, type TaskListCacheParams } from './useTaskCache';

export function useTaskList({ params, enabled = true }: { params: TaskListCacheParams; enabled?: boolean }) {
  const { user } = useAuth();
  const options = taskListQueryOptions(params, `${user?.id}:${user?.role}`);
  const query = useQuery({ ...options, enabled });
  const latest = useRef({ enabled, refetch: query.refetch });
  latest.current = { enabled, refetch: query.refetch };
  const refresh = useCallback(() => {
    // A mutation's shared invalidation may already have started this request.
    if (latest.current.enabled) void latest.current.refetch({ cancelRefetch: false });
  }, []);
  return {
    data: query.data ?? null,
    loading: enabled && query.isPending,
    error: query.error instanceof Error ? query.error.message : null,
    refresh,
  };
}
