"""Frozen reward accounting hardening; append guards without changing v1-v3."""

POLICY = "subtask-additional-v1"


def guard_specs():
    reserved = f"(NEW.ref_type='{POLICY}' OR NEW.policy_version='{POLICY}')"
    valid = (
        f"NEW.ref_type='{POLICY}' AND NEW.policy_version='{POLICY}' "
        "AND NEW.record_version=2 AND NEW.ref_id=NEW.subtask_id "
        "AND NEW.event_type='subtask.rewards_reconciled' "
        "AND ((NEW.component_type IN ('BASE','BONUS') AND NEW.points>0 AND NEW.reversal_of_id IS NULL) "
        "OR (NEW.component_type='PENALTY' AND NEW.points<0 AND NEW.reversal_of_id IS NULL) "
        f"OR (NEW.component_type='REVERSAL' AND EXISTS (SELECT 1 FROM xp_ledger x WHERE x.id=NEW.reversal_of_id AND x.ref_type='{POLICY}' AND x.reversal_of_id IS NULL AND x.component_type IN ('BASE','BONUS','PENALTY'))))"
    )
    assignee = (
        "EXISTS (SELECT 1 FROM tasks t JOIN users owner ON owner.id=t.created_by_id "
        "JOIN users recipient ON recipient.id=t.assigned_to_id "
        "WHERE t.id=NEW.task_id AND owner.tenant_id<>recipient.tenant_id)"
    )
    return [
        (
            "ledger_accounting",
            "xp_ledger",
            "INSERT",
            f"{reserved} AND NOT COALESCE(({valid}),false)",
        ),
        (
            "subtask_assignee",
            "subtasks",
            "INSERT",
            f"NEW.point_policy_version='{POLICY}' AND {assignee}",
        ),
        (
            "task_assignee",
            "tasks",
            "UPDATE",
            (
                f"EXISTS (SELECT 1 FROM subtasks s WHERE s.task_id=NEW.id AND s.point_policy_version='{POLICY}') "
                "AND NEW.assigned_to_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users owner JOIN users recipient ON recipient.id=NEW.assigned_to_id WHERE owner.id=NEW.created_by_id AND owner.tenant_id=recipient.tenant_id)"
            ),
        ),
        (
            "assignee_tenant",
            "users",
            "UPDATE",
            (
                "(NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id) AND EXISTS (SELECT 1 FROM tasks t JOIN subtasks s ON s.task_id=t.id "
                f"WHERE t.assigned_to_id=OLD.id AND s.point_policy_version='{POLICY}')"
            ),
        ),
    ]


def statements(dialect):
    result = []
    for suffix, table, operation, invalid in guard_specs():
        name = "zea_v4_" + suffix
        if dialect == "sqlite":
            result.extend(
                [
                    f"DROP TRIGGER IF EXISTS {name}",
                    f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT CASE WHEN {invalid} THEN RAISE(ABORT,'reward accounting invariant violated') END; END",
                ]
            )
        elif dialect == "postgresql":
            locks = ""
            if suffix == "subtask_assignee":
                locks = f"IF NEW.point_policy_version='{POLICY}' THEN PERFORM 1 FROM users WHERE id=(SELECT assigned_to_id FROM tasks WHERE id=NEW.task_id) FOR SHARE; END IF; "
            elif suffix == "task_assignee":
                locks = f"IF EXISTS (SELECT 1 FROM subtasks WHERE task_id=NEW.id AND point_policy_version='{POLICY}') THEN PERFORM 1 FROM users WHERE id=NEW.assigned_to_id FOR SHARE; END IF; "
            result.extend(
                [
                    f"CREATE OR REPLACE FUNCTION {name}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {locks}IF {invalid} THEN RAISE EXCEPTION 'reward accounting invariant violated' USING ERRCODE='23514'; END IF; RETURN NEW; END; $$",
                    f"DROP TRIGGER IF EXISTS {name} ON {table}",
                    f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_guard()",
                ]
            )
        else:
            raise RuntimeError("Unsupported reward database")
    return result
