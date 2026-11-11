"""Frozen Phase 3 guards. Older revision guard definitions remain unchanged."""

POLICY = "subtask-additional-v1"
INDEXES = (
    (
        "subtasks",
        "ix_subtasks_reward_order",
        ("task_id", "point_policy_version", "deleted_at", "created_at", "id"),
        False,
        None,
    ),
    (
        "xp_ledger",
        "uq_xp_ledger_subtask_component_event",
        ("tenant_id", "activity_event_id", "subtask_id", "component_type"),
        True,
        f"ref_type = '{POLICY}' AND reversal_of_id IS NULL",
    ),
)


def guard_specs(dialect):
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"

    def obj(field):
        return (
            f"json_type({field})='object'"
            if dialect == "sqlite"
            else f"json_typeof({field})='object'"
        )

    guards = [
        (
            "subtask_insert",
            "subtasks",
            "INSERT",
            f"NEW.point_policy_version='{POLICY}' AND NOT COALESCE((NEW.workflow_version=2 AND NEW.created_at IS NOT NULL AND length(NEW.reward_timezone) BETWEEN 1 AND 64),false)",
        ),
        (
            "subtask_order",
            "subtasks",
            "UPDATE",
            f"OLD.point_policy_version='{POLICY}' AND (NEW.id {distinct} OLD.id OR NEW.created_at {distinct} OLD.created_at OR NEW.reward_timezone {distinct} OLD.reward_timezone)",
        ),
        (
            "subtask_version",
            "subtasks",
            "UPDATE",
            f"NEW.deleted_at {distinct} OLD.deleted_at AND NEW.version<>OLD.version+1",
        ),
        (
            "subtask_delete",
            "subtasks",
            "DELETE",
            f"OLD.point_policy_version='{POLICY}'",
        ),
        (
            "ledger_shape",
            "xp_ledger",
            "INSERT",
            f"NEW.ref_type='{POLICY}' AND NOT COALESCE((NEW.record_version=2 AND NEW.policy_version='{POLICY}' AND NEW.subtask_id IS NOT NULL AND {obj('NEW.calculation_inputs')}),false)",
        ),
        (
            "policy_insert",
            "task_workflow_settings",
            "INSERT",
            f"NEW.point_policy_version='{POLICY}' AND NOT COALESCE(({obj('NEW.reward_policy_data')}),false)",
        ),
        (
            "policy_update",
            "task_workflow_settings",
            "UPDATE",
            f"NEW.point_policy_version='{POLICY}' AND (NOT COALESCE(({obj('NEW.reward_policy_data')}),false) OR ((CAST(NEW.reward_policy_data AS TEXT) {distinct} CAST(OLD.reward_policy_data AS TEXT) OR NEW.enabled {distinct} OLD.enabled) AND NEW.version<>OLD.version+1))",
        ),
    ]
    return guards


def statements(dialect):
    guards = guard_specs(dialect)
    result = []
    for suffix, table, operation, invalid in guards:
        name = "zea_v3_" + suffix
        if dialect == "sqlite":
            result += [
                f"DROP TRIGGER IF EXISTS {name}",
                f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT CASE WHEN {invalid} THEN RAISE(ABORT,'subtask reward invariant violated') END; END",
            ]
        else:
            result += [
                f"CREATE OR REPLACE FUNCTION {name}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {invalid} THEN RAISE EXCEPTION 'subtask reward invariant violated' USING ERRCODE='23514'; END IF; RETURN {'OLD' if operation == 'DELETE' else 'NEW'}; END; $$",
                f"DROP TRIGGER IF EXISTS {name} ON {table}",
                f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_guard()",
            ]
    return result
