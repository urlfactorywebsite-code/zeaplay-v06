export const TASKS_CHANGED_EVENT = 'zea:tasks-changed';
export function notifyTasksChanged() {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(TASKS_CHANGED_EVENT));
}
