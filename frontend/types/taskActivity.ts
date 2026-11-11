/** Server snapshots keep UTC timestamps and the existing API's snake_case keys. */
export type WorkStatus = 'RUNNING' | 'PAUSED' | 'STOPPED' | 'COMPLETED';
export interface ActivityContext {
  id: string; task_id: string; subtask_id: string | null;
  task_title: string; subtask_title: string | null; priority: string | null;
  status: WorkStatus; task_status: string | null; subtask_status: string | null;
  slot: number | null; version: number; elapsed_seconds: number;
  elapsed_ms: number; resumed_at: string | null; productive_seconds: number;
  subtask_productive_seconds: number | null; subtask_elapsed_seconds: number | null;
  actual_start_at: string | null; actual_end_at: string | null; deadline: string | null;
  can_start: boolean;
  restricted?: boolean;
}
export interface WorkDeadline { task_id: string; subtask_id?: string | null; title: string; deadline: string }
export interface ActivitySnapshot {
  user_id: string; user_name: string; read_only: boolean; server_now: string;
  timezone: string; active_count: number; limit: number; contexts: ActivityContext[];
  workload: {
    period_start: string; period_end: string; manual_seconds: number; overlap_seconds: number;
    estimated_remaining_seconds: number; unestimated_tasks: number;
    capacity_seconds: number | null; overtime_seconds: number | null; capacity_note: string | null;
    remaining_capacity_seconds?: number | null; overtime_threshold_seconds?: number;
    near_deadline: WorkDeadline[]; overdue_tasks: WorkDeadline[]; overdue_subtasks: WorkDeadline[];
    near_deadline_window_hours: number;
  };
}
export interface ConfirmedWork { id: string; subtask_id: string | null; started_at: string; ended_at: string; note: string | null; superseded: boolean }
export interface ActivityCommand {
  action: 'START' | 'PAUSE' | 'RESUME' | 'STOP'; subtask_id: string | null;
  expected_version: number; request_id: string;
}
export interface WorkInput {
  started_at: string; ended_at: string; subtask_id: string | null; note: string;
  confirmed: true; request_id: string; supersedes_id?: string;
}
