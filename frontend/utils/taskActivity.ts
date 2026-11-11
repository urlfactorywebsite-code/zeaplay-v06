import type { ActivityContext, ActivitySnapshot } from '../types/taskActivity';

export const TASK_ACTIVITY_CHANGED = 'zea:task-activity-changed';
export const TASK_ACTIVITY_WATCH = 'zea:task-activity-watch';
export function notifyActivityChanged(userId?: string) { window.dispatchEvent(new CustomEvent(TASK_ACTIVITY_CHANGED, { detail: { userId } })); }
export function watchActivity(userId?: string) { window.dispatchEvent(new CustomEvent(TASK_ACTIVITY_WATCH, { detail: { userId } })); }
export function validateActivitySubject(frame: ActivitySnapshot, subject?: string) {
  if (frame.user_id !== subject) throw new Error('Account changed while loading activity; refresh your sign-in.');
  return frame;
}

/** One monotonic UI clock interpolates an authoritative server snapshot. */
export function elapsedSeconds(row: ActivityContext, receivedAt: number, now: number, selectedSubtask = false) {
  return (selectedSubtask ? row.subtask_elapsed_seconds ?? row.elapsed_seconds : row.elapsed_seconds)
    + (row.status === 'RUNNING' ? Math.max(0, now - receivedAt) / 1000 : 0);
}
export function workDuration(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 3600)}:${String(Math.floor(total / 60) % 60).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}
export function activityWarning(frame?: ActivitySnapshot) {
  return !!frame && (frame.active_count >= frame.limit || frame.workload.overdue_tasks.length > 0
    || frame.workload.overdue_subtasks.length > 0 || frame.workload.near_deadline.length > 0
    || (frame.workload.overtime_seconds ?? 0) > (frame.workload.overtime_threshold_seconds ?? 0)
    || (frame.workload.remaining_capacity_seconds != null && frame.workload.estimated_remaining_seconds > frame.workload.remaining_capacity_seconds)
    || frame.workload.overlap_seconds > 0);
}
export function fiveSlots(frame?: ActivitySnapshot) {
  return Array.from({ length: 5 }, (_, index) => ({ number: index + 1,
    context: frame?.contexts.find(row => row.status === 'RUNNING' && row.slot === index + 1) }));
}
