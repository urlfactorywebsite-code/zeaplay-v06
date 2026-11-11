export type InformationSection = 'overview' | 'timeline' | 'subtasks' | 'points' | 'activity';
export interface InformationPerson { id: string; name: string }
export interface InformationEvent {
  kind: 'event'; id: string; source: string; event_type: string; timestamp: string;
  actor: InformationPerson | null; subtask_id: string | null; channel: string;
  previous_status: string | null; new_status: string | null; duration_seconds: number | null;
  before: Record<string, unknown> | null; after: Record<string, unknown> | null; details: Record<string, unknown>;
}
export interface InformationSubtask {
  kind: 'subtask'; id: string; name: string; assignee: InformationPerson | null;
  effective_priority: string; priority_inherited: boolean; planned_start_date: string | null;
  planned_end_date: string | null; actual_start_at: string | null; actual_end_at: string | null;
  status: string; completed: boolean; deleted_at: string | null; created_at: string | null;
  policy_version: string; additional_base_value: number; available_base: number; earned: number | null;
  components: Record<string, number>; productive_seconds: number; elapsed_seconds: number;
}
export interface InformationOverview {
  id: string; name: string; description: string; team: string; project: string | null;
  creator: InformationPerson | null; assignees: InformationPerson[]; priority: string; status: string;
  created_at: string; updated_at: string; assigned_at: string | null;
  planned_start_date: string | null; planned_end_date: string | null;
  actual_start_at: string | null; actual_end_at: string | null; estimated_hours: number | null;
  productive_seconds: number; elapsed_seconds: number; due_at: string | null; completed_at: string | null;
  approval_status: string; approval_required: boolean; limitations: string[];
}
export interface InformationPoints {
  main_base_value: number; main_earned: number | null; subtask_base_capacity: number;
  subtask_available_base: number; subtask_earned: number; components: Record<string, number>;
  verified_net_earned: number; total_net_earned: number | null;
  subtask_components: Record<string, number>; main_recorded_components: Record<string, number>; main_recorded_net: number;
  recipients: { id: string; name: string; net: number; main_net: number; subtask_net: number; components: Record<string, number> }[]; coverage: string;
}
export interface TaskInformation {
  viewer_id: string;
  task_id: string; section: InformationSection; as_of: string;
  overview: InformationOverview | null; points: InformationPoints | null;
  items: (InformationEvent | InformationSubtask)[]; total: number; page: number; page_size: number;
  created_at: string | null; coverage: string;
}
export interface InformationOptions {
  section: InformationSection; page: number; page_size?: number; search?: string; subtask_id?: string;
}
