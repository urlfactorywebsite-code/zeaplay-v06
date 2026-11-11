import { DateTime } from 'luxon';
import type { Subtask, SubtaskAction, SubtaskChanges, SubtaskStatus, TaskPriority } from '../types';

export const subtaskStatusLabels: Record<SubtaskStatus, string> = {
  TODO: 'To Do', IN_PROGRESS: 'In Progress', PAUSED: 'Paused', TESTING: 'Testing', COMPLETED: 'Completed',
};
export const subtaskActions: Record<SubtaskStatus, Array<{ action: SubtaskAction; label: string }>> = {
  TODO: [{ action: 'START', label: 'Start' }],
  IN_PROGRESS: [{ action: 'PAUSE', label: 'Pause' }, { action: 'SEND_TO_TESTING', label: 'Send to Testing' }, { action: 'COMPLETE', label: 'Complete' }],
  PAUSED: [{ action: 'RESUME', label: 'Resume' }],
  TESTING: [{ action: 'START', label: 'Return to In Progress' }, { action: 'COMPLETE', label: 'Complete' }],
  COMPLETED: [{ action: 'REOPEN', label: 'Reopen' }],
};

export function plannedDatesError(start?: string | null, end?: string | null) {
  if (!start || !end) return 'Planned start and end dates are required.';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)
      || !DateTime.fromISO(start).isValid || !DateTime.fromISO(end).isValid) return 'Enter valid planned dates.';
  return start > end ? 'Planned start must be on or before planned end.' : '';
}

export function actualWallTime(value: string | null | undefined, zone: string) {
  return value ? DateTime.fromISO(value, { zone: 'utc' }).setZone(zone).toFormat("yyyy-MM-dd'T'HH:mm:ss") : '';
}

export function actualTimeOptions(value: string, zone: string) {
  if (!value) return [];
  const parsed = DateTime.fromISO(value, { zone });
  if (!parsed.isValid || parsed.toFormat("yyyy-MM-dd'T'HH:mm") !== value.slice(0, 16)) return [];
  return parsed.getPossibleOffsets().map(date => ({ offset: String(date.offset), label: `UTC${date.toFormat('ZZ')}`, utc: date.toUTC().toISO()! }));
}

export function actualTimeToUtc(value: string, zone: string, offset?: string) {
  const options = actualTimeOptions(value, zone);
  if (!options.length) throw new Error('This actual time does not exist in your timezone. Choose a valid time.');
  const chosen = options.length === 1 ? options[0] : options.find(option => option.offset === offset);
  if (!chosen) throw new Error('This actual time occurs twice. Confirm its UTC offset.');
  return chosen.utc;
}

export function subtaskPriority(subtask: Subtask, parent: TaskPriority) {
  return subtask.priorityOverride ?? parent;
}

export function subtaskRequest(changes: SubtaskChanges) {
  const body: Record<string, unknown> = {};
  const names = { title:'title', completed:'completed', status:'status', action:'action', version:'expected_version', deleted:'deleted',
    plannedStartDate:'planned_start_date', plannedEndDate:'planned_end_date', actualStartAt:'actual_start_at',
    actualEndAt:'actual_end_at', priorityOverride:'priority_override', confirmActualTimes:'confirm_actual_times', manage:'manage' };
  for (const [key, name] of Object.entries(names)) {
    const value = changes[key as keyof SubtaskChanges];
    if (value !== undefined) body[name] = value;
  }
  return body;
}

export function subtaskCreateRequest(row: Subtask) {
  return { title:row.title, completed:false, planned_start_date:row.plannedStartDate,
    planned_end_date:row.plannedEndDate, priority_override:row.priorityOverride ?? null };
}

export interface ApiSubtask {
  id: string; title: string; completed: boolean;
  planned_start_date?: string | null; planned_end_date?: string | null;
  actual_start_at?: string | null; actual_end_at?: string | null;
  priority_override?: TaskPriority | null; effective_priority?: TaskPriority | null;
  status?: SubtaskStatus; managed?: boolean; version?: number; point_policy_version?: string;
  deleted_at?: string | null; reward_timezone?: string | null;
}

export function mapApiSubtask(row: ApiSubtask): Subtask {
  return { id:row.id, title:row.title, completed:row.completed,
    plannedStartDate:row.planned_start_date ?? null, plannedEndDate:row.planned_end_date ?? null,
    actualStartAt:row.actual_start_at ?? null, actualEndAt:row.actual_end_at ?? null,
    priorityOverride:row.priority_override ?? null, effectivePriority:row.effective_priority ?? null,
    status:row.status ?? (row.completed ? 'COMPLETED' : 'TODO'), managed:row.managed ?? false,
    version:row.version ?? 1, pointPolicyVersion:row.point_policy_version ?? 'legacy', deletedAt:row.deleted_at ?? null, rewardTimezone:row.reward_timezone ?? null };
}
