import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from './useAuth';
import { taskListQueryOptions, type TaskListCacheParams } from './useTaskCache';

export function useTaskPrefetch({ baseParams, pages, enabled = true }: {
  baseParams: Omit<TaskListCacheParams, 'page'>; pages: number[]; enabled?: boolean;
}) {
  const { user } = useAuth();
  const client = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    for (const page of pages) {
      if (page > 0) void client.prefetchQuery(taskListQueryOptions({ ...baseParams, page }, `${user?.id}:${user?.role}`));
    }
  }, [baseParams, pages, enabled, client, user?.id, user?.role]);
}
