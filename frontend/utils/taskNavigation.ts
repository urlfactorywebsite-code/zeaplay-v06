export const TASK_TABS = [
  { key: 'list', pageId: 'tasks.list', path: '/tasks', label: 'All Tasks' },
  { key: 'kanban', pageId: 'kanban', path: '/tasks/kanban', label: 'Kanban Board' },
  { key: 'gantt', pageId: 'gantt', path: '/tasks/gantt', label: 'Gantt Chart' },
  { key: 'calendar', pageId: 'calendar', path: '/tasks/calendar', label: 'Calendar' },
] as const;
export type TaskTabKey = typeof TASK_TABS[number]['key'];
export function taskDetailIdFromPath(path: string) {
  return /^\/tasks\/([a-f\d]{8}-(?:[a-f\d]{4}-){3}[a-f\d]{12})\/?$/i.exec(path)?.[1];
}
export const LEGACY_TASK_ROUTES: Record<string, string> = {
  '/kanban': '/tasks/kanban', '/gantt': '/tasks/gantt', '/calendar': '/tasks/calendar',
};
export function taskTabForPath(path: string) {
  try { path = decodeURIComponent(path); } catch { return undefined; }
  return TASK_TABS.find(tab => tab.path === path.replace(/\/+$/, '').toLowerCase());
}
export function updateTaskFilter(search: string, key: string, value: string) {
  const params = new URLSearchParams(search);
  if (!value || value === 'ALL') params.delete(key); else params.set(key, value);
  return params.toString();
}
