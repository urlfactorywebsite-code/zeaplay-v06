"""Reviewed column allowlists. New database columns are NEVER exported automatically.

Opaque integration/audit payloads and credential tables are intentionally omitted.
Discovery compares the loaded schema with this registry and fails closed on drift.
"""

from .. import models as core_models  # noqa: F401
from ..database import Base
from ..tickets import models as ticket_models  # noqa: F401

FIELDS = {
    "departments": "id name",
    "users": "id tenant_id name email employer_id role department_id manager_id manager_email webex_person_id shift_name shift_start shift_end morning_break_start morning_break_end lunch_break_start lunch_break_end evening_break_start evening_break_end title phone location timezone profile_bio notes skills projects status points tasks_created tasks_completed clarity_scores claimed_reward_ids unlocked_achievement_ids avatar_asset_id avatar_frame profile_image_key profile_image_url created_at updated_at",
    "avatar_assets": "tenant_id storage_provider thumbnail_path id name storage_type file_path data_url external_url mime_type is_default created_by_id created_at updated_at",
    "tasks": "id title description status priority team task_group_id ticket_id assigned_to_id created_by_id approval_required approval_status approver_id created_at updated_at due_at assigned_at completed_at recurrence_rule recurring_task_id clarity_rating attachments estimated_hours tags",
    "subtasks": "id task_id title completed planned_start_date planned_end_date actual_start_at actual_end_at priority_override point_policy_version version created_at workflow_version workflow_status",
    "comments": "id task_id user_id content created_at",
    "task_messages": "id task_id author_id message mentions is_deleted edited_at created_at",
    "kanban_columns": "id title order",
    "achievements": "id title description points icon",
    "user_achievements": "user_id achievement_id unlocked_at",
    "badges": "id name description tier tier_group tier_order bonus_xp image_url image_asset_path state is_system created_at updated_at",
    "badge_rules": "badge_id rules created_at updated_at",
    "user_badge_progress": "id user_id badge_id status progress_value progress_state earned_at created_at updated_at",
    "reward_icons": "id key url label",
    "rewards": "id title description image_source image_ref xp_required dept_whitelist auto_redeem allow_multiple_claims expires_at status created_by_id updated_by_id created_at updated_at",
    "reward_claims": "id reward_id user_id status xp_spent claimed_at resolved_at approver_id",
    "reward_logs": "id actor_id subject_type subject_id action created_at",
    "approvals": "id scope_type scope_id requested_by approver_id order_index status comment sla_hours created_at acted_at",
    "task_transfer_requests": "id task_id from_user_id to_user_id requested_by_id approved_by_id status note created_at acted_at",
    "audit_events": "id actor_id event_type entity_type entity_id created_at audit_schema_version tenant_id task_id subtask_id before after correlation_id",
    "audit_logs": "id tenant_id actor_id actor_role action category entity_type entity_id target_user_id approval_id ip_address user_agent source severity status reason trigger route method created_at deleted_at",
    "audit_retention_config": "id retention_days created_at updated_at last_applied_at",
    "tool_categories": "id name description display_order status created_at updated_at",
    "tools": "id name description website_url preview_image_url category_id tags pricing_type is_internal status created_by approved_by review_reason created_at updated_at",
    "user_favorite_tools": "user_id tool_id created_at",
    "notifications": "id user_id type title body message entity_type entity_id deep_link is_read related_task_id related_reward_id related_chat_id created_at tenant_id dedupe_key alert_kind dismissed_at delivery_pending delivery_attempts next_delivery_at",
    "notification_preferences": "id user_id module push_enabled updated_at sound_enabled near_deadline_hours productive_capacity_hours overtime_threshold_minutes quiet_start quiet_end",
    "chat_conversations": "id tenant_id name description avatar_url type project_id team_id direct_key is_private is_archived created_by_id created_at updated_at last_message_at",
    "chat_participants": "id conversation_id user_id role is_admin joined_at last_read_message_id last_read_at is_muted is_pinned",
    "chat_messages": "id conversation_id sender_id message_type client_id content reply_to_message_id edited_at deleted_at created_at updated_at",
    "message_reactions": "id message_id user_id emoji created_at",
    "message_attachments": "id message_id file_name original_file_name mime_type file_size storage_key url created_at",
    "pinned_messages": "id conversation_id message_id pinned_by created_at",
    "message_mentions": "message_id mentioned_user_id",
    "points_table_config": "id points_config task_creation_points clarity_points_per_star manager_overdue_penalty created_at updated_at",
    "release_notes": "id version_label content_mode details_text updated_by_id created_at updated_at",
    "email_templates": "tenant_id id notification_type subject body created_at updated_at",
    "task_templates": "id title description priority team subtasks attachments estimated_hours tags featured_image department_id recurrence_rule created_by_id created_at updated_at",
    "media_files": "id user_id department_id media_type bucket object_key original_filename content_type size_bytes checksum crop_metadata status created_at updated_at deleted_at",
    "media_items": "id owner_id filename ext mime_type size_bytes category storage_provider storage_path public_url width height checksum_sha256 created_at updated_at deleted_at original_id",
    "levels": "id name bg_image is_active season_id created_by_id created_at",
    "level_nodes": "id level_id type x y width height title description xp_threshold reward_id require_confirm animation_key created_at updated_at",
    "level_edges": "id level_id from_node to_node path created_at updated_at",
    "level_events": "id level_id node_id event_type user_id created_at",
    "seasons": "id name description start_date end_date is_active theme bonus_multiplier created_at updated_at",
    "user_progress": "id user_id level_id season_id current_points total_points_earned level_unlocked_at created_at updated_at",
    "navigation_policies": "tenant_id pages version updated_by updated_at",
    "feature_flags": "key label group description enabled created_at updated_at",
    "tickets": "id tenant_id department_id created_by owner_id assigned_user_id title description due_at sla_hours approval_enabled approval_type min_approvals approval_deadline approval_approver_ids approval_status status priority sla_first_response_minutes sla_resolution_minutes first_response_due_at resolution_due_at first_response_at resolved_at closed_at resolution_type created_at updated_at deleted_at",
    "ticket_followers": "id tenant_id ticket_id user_id created_at deleted_at",
    "ticket_approvals": "id tenant_id ticket_id attempt_no approval_type min_approvals status requested_by approval_deadline created_at updated_at",
    "ticket_approval_users": "id tenant_id ticket_id approval_id user_id decision comment decided_at sequence_order created_at",
    "ticket_participants": "id tenant_id ticket_id user_id role added_by created_at deleted_at",
    "ticket_comments": "id tenant_id ticket_id user_id is_internal body edited_at created_at deleted_at",
    "ticket_comment_mentions": "id tenant_id comment_id mentioned_user_id created_at deleted_at",
    "ticket_attachments": "id tenant_id ticket_id file_key file_name mime_type size_bytes uploaded_by created_at deleted_at",
    "ticket_activity_logs": "id tenant_id ticket_id event_type actor_id created_at deleted_at",
    "ticket_status_history": "id tenant_id ticket_id from_status to_status actor_user_id moved_at_utc",
    "ticket_close_events": "id ticket_id closed_by close_reason duplicate_ticket_id created_at",
    "ticket_approval_cycles": "id tenant_id ticket_id approval_type deadline_utc attempts_left status requested_by requested_at_utc completed_at_utc",
    "ticket_approval_items": "id tenant_id cycle_id approver_user_id message status acted_at_utc order_index",
    "ticket_tasks": "id tenant_id ticket_id title description status assigned_to created_by due_at_utc priority points completed_at_utc created_at_utc updated_at_utc",
    "points_ledger": "id tenant_id user_id ticket_id task_id points reason created_at_utc created_by",
    "ticket_audit_logs": "id tenant_id ticket_id event_type actor_user_id created_at_utc summary",
    "ticket_sla_policies": "id tenant_id department_id priority first_response_minutes resolution_minutes created_at updated_at deleted_at",
    "ticket_task_links": "id tenant_id ticket_id task_id created_at deleted_at",
    "ticket_notifications": "id tenant_id user_id type title body is_read created_at deleted_at",
    "xp_ledger": "id tenant_id user_id event_type points ref_type ref_id created_at deleted_at record_version task_id subtask_id component_type policy_version idempotency_key activity_event_id reason reversal_of_id",
    "task_workflow_settings": "tenant_id enabled point_policy_version activated_at version",
    "task_work_intervals": "id tenant_id task_id subtask_id user_id created_by_id started_at ended_at note activity_event_id request_id created_at",
    "task_activity_contexts": "id tenant_id user_id task_id subtask_id status slot elapsed_ms resumed_at version activity_event_id created_at updated_at",
    "task_work_corrections": "id tenant_id user_id original_interval_id replacement_interval_id activity_event_id request_id created_at",
    "task_dependencies": "task_id depends_on_task_id",
    "task_followers": "task_id user_id created_at",
}
# Exact pre-Phase-1 archive shapes; never accept arbitrary missing columns.
LEGACY_TASK_AUDIT_FIELDS = {
    "subtasks": "id task_id title completed",
    "audit_events": "id actor_id event_type entity_type entity_id created_at",
    "xp_ledger": "id tenant_id user_id event_type points ref_type ref_id created_at deleted_at",
}
PHASE1_SUBTASK_FIELDS = ["id", "task_id", "title", "completed", "planned_start_date", "planned_end_date", "actual_start_at", "actual_end_at", "priority_override", "point_policy_version", "version", "created_at"]
# Exact previous archive versions, before Phase 3's additive fields.
PHASE2_REWARD_FIELDS = {key: FIELDS[key].split() for key in ("subtasks", "xp_ledger", "task_workflow_settings")}
FIELDS["subtasks"] += " deleted_at reward_timezone"
FIELDS["xp_ledger"] += " calculation_inputs"
FIELDS["task_workflow_settings"] += " reward_policy_data"
EXCLUDED = {
    "auth_sessions",
    "auth_refresh_tokens",
    "smtp_config",
    "owner_reset_tokens",
    "api_config",
    "multiple_api_configs",
    "multiple_smtp_configs",
    "oauth_config",
    "push_subscriptions",
    "webhook_subscriptions",
    "webhook_delivery_logs",
    "backup_jobs",
    "export_presets",
}
ALIASES = {"reward_claims": "user-rewards", "kanban_columns": "kanban-columns"}
OMITTED_FIELDS = {
    "users": {"hashed_password", "auth_epoch"},
    "tasks": {"search_vector"},
    "reward_logs": {"meta"},
    "audit_events": {"payload"},
    "audit_logs": {"old_value", "new_value", "before", "after", "metadata"},
    "release_notes": {"html", "css", "js"},
    "ticket_activity_logs": {"payload"},
    "ticket_status_history": {"metadata_json"},
    "ticket_audit_logs": {"payload_json"},
    "ticket_notifications": {"data"},
}

# Relationships present in the application but missing database FK constraints.
REFERENCES = {
    "notifications": {"related_task_id": ("tasks", "id")},
    "users": {"manager_id": ("users", "id")},
    "tickets": {
        "created_by": ("users", "id"),
        "owner_id": ("users", "id"),
        "assigned_user_id": ("users", "id"),
    },
    "ticket_followers": {"user_id": ("users", "id")},
    "ticket_approvals": {"requested_by": ("users", "id")},
    "ticket_approval_users": {
        "ticket_id": ("tickets", "id"),
        "user_id": ("users", "id"),
    },
    "ticket_participants": {"user_id": ("users", "id"), "added_by": ("users", "id")},
    "ticket_comments": {"user_id": ("users", "id")},
    "ticket_comment_mentions": {"mentioned_user_id": ("users", "id")},
    "ticket_attachments": {"uploaded_by": ("users", "id")},
    "ticket_activity_logs": {"actor_id": ("users", "id")},
    "ticket_status_history": {"actor_user_id": ("users", "id")},
    "ticket_approval_cycles": {"requested_by": ("users", "id")},
    "ticket_approval_items": {"approver_user_id": ("users", "id")},
    "ticket_tasks": {"assigned_to": ("users", "id"), "created_by": ("users", "id")},
    "points_ledger": {
        "user_id": ("users", "id"),
        "ticket_id": ("tickets", "id"),
        "task_id": ("ticket_tasks", "id"),
        "created_by": ("users", "id"),
    },
    "ticket_audit_logs": {"actor_user_id": ("users", "id")},
    "ticket_task_links": {"task_id": ("tasks", "id")},
    "ticket_notifications": {"user_id": ("users", "id")},
    "xp_ledger": {"user_id": ("users", "id")},
}


def dataset_id(table):
    return ALIASES.get(table, table.replace("_", "-"))


def tables():
    return {dataset_id(name): Base.metadata.tables[name] for name in FIELDS}


def dependencies(table):
    return sorted(
        {
            dataset_id(target.name)
            for _, target, _ in references(table)
            if target.name in FIELDS and target.name != table.name
        } | ({"task-workflow-settings"} if table.name == "subtasks" else set())
    )


def references(table):
    actual = [
        (fk.parent.name, fk.column.table, fk.column.name) for fk in table.foreign_keys
    ]
    actual += [
        (name, Base.metadata.tables[target], column)
        for name, (target, column) in REFERENCES.get(table.name, {}).items()
    ]
    return actual
