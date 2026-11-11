"""Frozen v2 database guards, shared by migration f6b8d0e2a4c6 and fresh installs.

Extends the original guards; does not reinterpret or recalculate legacy rewards.
"""

LOOKUP_INDEXES = (
    (
        "audit_events",
        "ix_audit_events_actor_v2",
        ("actor_id",),
        "audit_schema_version = 2",
    ),
    ("audit_events", "ix_audit_events_task_ref", ("task_id",), None),
    ("audit_events", "ix_audit_events_subtask_ref", ("subtask_id",), None),
    ("xp_ledger", "ix_xp_ledger_user_v2", ("user_id",), "record_version = 2"),
    ("xp_ledger", "ix_xp_ledger_task_ref", ("task_id",), None),
    ("xp_ledger", "ix_xp_ledger_subtask_ref", ("subtask_id",), None),
    ("task_work_intervals", "ix_task_work_intervals_task_ref", ("task_id",), None),
    (
        "task_work_intervals",
        "ix_task_work_intervals_subtask_ref",
        ("subtask_id",),
        None,
    ),
    ("task_work_intervals", "ix_task_work_intervals_user_ref", ("user_id",), None),
    (
        "task_work_intervals",
        "ix_task_work_intervals_actor_ref",
        ("created_by_id",),
        None,
    ),
)


def task_audit_guard_specs_v2(dialect):
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
    old_policy_children = "EXISTS (SELECT 1 FROM subtasks s WHERE s.task_id=OLD.id AND s.point_policy_version<>'legacy')"
    owned_policy_children = "EXISTS (SELECT 1 FROM subtasks s JOIN tasks t ON t.id=s.task_id WHERE t.created_by_id=OLD.id AND s.point_policy_version<>'legacy')"
    new_owner_differs = "EXISTS (SELECT 1 FROM users a JOIN users b ON b.id=NEW.created_by_id WHERE a.id=OLD.created_by_id AND a.tenant_id<>b.tenant_id)"
    legacy_activity_fields = " OR ".join(
        f"NEW.{field} IS NOT NULL"
        for field in ("task_id", "subtask_id", "correlation_id")
    )
    legacy_activity_fields += " OR (NEW.before IS NOT NULL AND CAST(NEW.before AS TEXT)<>'null') OR (NEW.after IS NOT NULL AND CAST(NEW.after AS TEXT)<>'null')"
    legacy_ledger_fields = " OR ".join(
        f"NEW.{field} IS NOT NULL"
        for field in (
            "task_id",
            "subtask_id",
            "component_type",
            "policy_version",
            "idempotency_key",
            "activity_event_id",
            "reason",
            "reversal_of_id",
        )
    )
    # Managed workflow is independent of the reward-policy activation marker.
    workflow_valid = """NEW.workflow_version IN (0,2)
        AND ((NEW.workflow_version=0 AND NEW.workflow_status IS NULL)
          OR (NEW.workflow_version=2 AND NEW.planned_start_date IS NOT NULL
            AND NEW.planned_end_date IS NOT NULL
            AND NEW.workflow_status IN ('TODO','IN_PROGRESS','PAUSED','TESTING','COMPLETED')
            AND NEW.completed=(NEW.workflow_status='COMPLETED')
            AND (NEW.workflow_status<>'COMPLETED' OR
              (NEW.actual_start_at IS NOT NULL AND NEW.actual_end_at IS NOT NULL))))"""
    date_valid = "true"
    if dialect == "sqlite":
        date_valid = " AND ".join(
            [
                *[
                    f"(NEW.{field} IS NULL OR (length(NEW.{field})=10 AND date(NEW.{field})=NEW.{field}))"
                    for field in ("planned_start_date", "planned_end_date")
                ],
                *[
                    f"(NEW.{field} IS NULL OR julianday(NEW.{field}) IS NOT NULL)"
                    for field in ("actual_start_at", "actual_end_at", "created_at")
                ],
            ]
        )
    guards = [
        (
            "activity_shape_insert",
            "audit_events",
            "INSERT",
            f"NEW.audit_schema_version=1 AND ({legacy_activity_fields})",
        ),
        (
            "activity_shape_update",
            "audit_events",
            "UPDATE",
            f"NEW.audit_schema_version=1 AND ({legacy_activity_fields})",
        ),
        (
            "ledger_shape_insert",
            "xp_ledger",
            "INSERT",
            f"NEW.record_version=1 AND ({legacy_ledger_fields})",
        ),
        (
            "ledger_shape_update",
            "xp_ledger",
            "UPDATE",
            f"NEW.record_version=1 AND ({legacy_ledger_fields})",
        ),
        (
            "subtask_shape_insert",
            "subtasks",
            "INSERT",
            f"NOT COALESCE(({workflow_valid} AND {date_valid}), false)",
        ),
        (
            "subtask_shape_update",
            "subtasks",
            "UPDATE",
            f"(NEW.workflow_version {distinct} OLD.workflow_version AND NOT (OLD.workflow_version=0 AND NEW.workflow_version=2)) OR NOT COALESCE(({workflow_valid} AND {date_valid}), false)",
        ),
        (
            "task_policy_owner",
            "tasks",
            "UPDATE",
            f"NEW.created_by_id {distinct} OLD.created_by_id AND {new_owner_differs} AND {old_policy_children}",
        ),
        (
            "user_policy_owner",
            "users",
            "UPDATE",
            f"(NEW.tenant_id {distinct} OLD.tenant_id OR NEW.id {distinct} OLD.id) AND ({owned_policy_children} OR EXISTS (SELECT 1 FROM xp_ledger x WHERE x.user_id=OLD.id AND x.record_version=2))",
        ),
    ]
    changed = " OR ".join(
        f"NEW.{field} {distinct} OLD.{field}"
        for field in (
            "title",
            "planned_start_date",
            "planned_end_date",
            "actual_start_at",
            "actual_end_at",
            "priority_override",
            "completed",
            "workflow_status",
            "workflow_version",
        )
    )
    legal_transition = " OR ".join(
        f"(OLD.workflow_status='{origin}' AND NEW.workflow_status IN ({targets}))"
        for origin, targets in (
            ("TODO", "'IN_PROGRESS'"),
            ("IN_PROGRESS", "'PAUSED','TESTING','COMPLETED'"),
            ("PAUSED", "'IN_PROGRESS'"),
            ("TESTING", "'IN_PROGRESS','COMPLETED'"),
            ("COMPLETED", "'TODO'"),
        )
    )
    guards.extend(
        [
            (
                "subtask_version",
                "subtasks",
                "UPDATE",
                f"(OLD.workflow_version=2 OR NEW.workflow_version=2) AND ({changed}) AND NEW.version<>OLD.version+1",
            ),
            (
                "subtask_transition",
                "subtasks",
                "UPDATE",
                f"OLD.workflow_version=2 AND NEW.workflow_status {distinct} OLD.workflow_status AND NOT COALESCE(({legal_transition}),false)",
            ),
        ]
    )
    return guards


def task_audit_guard_statements_v2(dialect):
    statements = []
    guards = task_audit_guard_specs_v2(dialect)
    for name, table, operation, invalid in guards:
        name = "zea_v2_" + name
        if dialect == "sqlite":
            statements.extend(
                [
                    f"DROP TRIGGER IF EXISTS {name}",
                    f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT CASE WHEN {invalid} THEN RAISE(ABORT, 'task workflow invariant violated') END; END",
                ]
            )
        elif dialect == "postgresql":
            statements.extend(
                [
                    f"CREATE OR REPLACE FUNCTION {name}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {invalid} THEN RAISE EXCEPTION 'task workflow invariant violated' USING ERRCODE='23514'; END IF; RETURN NEW; END; $$",
                    f"DROP TRIGGER IF EXISTS {name} ON {table}",
                    f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_guard()",
                ]
            )
        else:
            raise RuntimeError("Task audit supports PostgreSQL and SQLite only")
    if dialect == "postgresql":
        for table, condition in (
            ("audit_events", "audit_schema_version=2"),
            ("xp_ledger", "record_version=2"),
            ("task_work_intervals", "true"),
        ):
            name = "zea_v2_" + table + "_truncate"
            statements.extend(
                [
                    f"CREATE OR REPLACE FUNCTION {name}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF EXISTS (SELECT 1 FROM {table} WHERE {condition}) THEN RAISE EXCEPTION 'immutable task history cannot be truncated' USING ERRCODE='23514'; END IF; RETURN NULL; END; $$",
                    f"DROP TRIGGER IF EXISTS {name} ON {table}",
                    f"CREATE TRIGGER {name} BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {name}_guard()",
                ]
            )
    return statements
