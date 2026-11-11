import { getAccessToken } from '../services/tokenStorage';
import api from '../services/mockApi';
import type { TaskPriority, TaskStatus } from '../types';

export type TaskListCacheParams = {
  viewMode?: 'list' | 'grid';
  page: number;
  pageSize: number;
  search?: string;
  status?: TaskStatus;
  priority?: TaskPriority;
  assigneeId?: string;
  team?: string;
  tag?: string;
  dueDate?: string;
  createdDate?: string;
  quickFilter?: string;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
};

/** The live list and adjacent-page prefetch share one query and in-flight request. */
export function taskListQueryOptions(params: TaskListCacheParams, identity: string) {
  const request = { ...params };
  delete request.viewMode; // Layout does not change the server result.
  return {
    queryKey: ['tasks', 'list', `${getAccessToken()}:${identity}`, request] as const,
    queryFn: ({ signal }: { signal: AbortSignal }) => api.getTasksPage({ ...request, signal }),
    staleTime: 60_000,
  };
}
