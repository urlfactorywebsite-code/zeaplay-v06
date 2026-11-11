"""Frozen Phase 4 storage guards. Prior audit/reward contracts stay unchanged."""

EVENTS = (
    "work.started",
    "work.paused",
    "work.resumed",
    "work.stopped",
    "work.switched",
    "work.completed",
)
EVENT_PREDICATE = "event_type IN (" + ",".join(repr(x) for x in EVENTS) + ")"


def specs(dialect):
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"

    def value(field):
        return (
            f"json_extract(e.after,'$.{field}')"
            if dialect == "sqlite"
            else f"e.after->>'{field}'"
        )

    projection = " AND ".join(
        f"NOT(CAST({value(field)} AS TEXT) {distinct} CAST(NEW.{column} AS TEXT))"
        for field, column in (
            ("context_id", "id"),
            ("user_id", "user_id"),
            ("status", "status"),
            ("slot", "slot"),
            ("elapsed_ms", "elapsed_ms"),
            ("version", "version"),
            ("subtask_id", "subtask_id"),
        )
    )
    resumed = value("resumed_at")
    time_match = (
        f"CAST({resumed} AS TIMESTAMP WITH TIME ZONE)=NEW.resumed_at"
        if dialect == "postgresql"
        else f"julianday({resumed})=julianday(NEW.resumed_at)"
    )
    projection += f" AND ((NEW.resumed_at IS NULL AND {resumed} IS NULL) OR (NEW.resumed_at=NEW.updated_at AND {time_match}))"
    context_valid = (
        "NEW.elapsed_ms>=0 AND NEW.version>=1 AND NEW.updated_at>=NEW.created_at AND "
        "((NEW.status='RUNNING' AND NEW.slot BETWEEN 1 AND 5 AND NEW.slot IS NOT NULL AND NEW.resumed_at IS NOT NULL) "
        "OR (NEW.status IN ('PAUSED','STOPPED','COMPLETED') AND NEW.slot IS NULL AND NEW.resumed_at IS NULL)) AND "
        "EXISTS (SELECT 1 FROM users u JOIN tasks t ON t.id=NEW.task_id JOIN users owner ON owner.id=t.created_by_id "
        "WHERE u.id=NEW.user_id AND u.tenant_id=NEW.tenant_id AND owner.tenant_id=NEW.tenant_id) "
        "AND (NEW.subtask_id IS NULL OR EXISTS (SELECT 1 FROM subtasks s WHERE s.id=NEW.subtask_id AND s.task_id=NEW.task_id)) "
        "AND EXISTS (SELECT 1 FROM audit_events e WHERE e.id=NEW.activity_event_id AND e.audit_schema_version=2 AND e.tenant_id=NEW.tenant_id "
        f"AND e.task_id=NEW.task_id AND NOT(e.subtask_id {distinct} NEW.subtask_id) AND e.created_at>=NEW.updated_at AND {EVENT_PREDICATE} AND {projection})"
    )
    correction_valid = (
        "EXISTS (SELECT 1 FROM task_work_intervals a JOIN task_work_intervals b ON b.id=NEW.replacement_interval_id "
        "JOIN audit_events e ON e.id=NEW.activity_event_id WHERE a.id=NEW.original_interval_id "
        "AND a.tenant_id=NEW.tenant_id AND b.tenant_id=NEW.tenant_id AND a.user_id=NEW.user_id AND b.user_id=NEW.user_id "
        f"AND a.task_id=b.task_id AND NOT(a.subtask_id {distinct} b.subtask_id) "
        "AND e.audit_schema_version=2 AND e.tenant_id=NEW.tenant_id AND e.actor_id=NEW.user_id AND e.task_id=a.task_id "
        f"AND NOT(e.subtask_id {distinct} a.subtask_id) AND e.event_type='work.interval_corrected')"
    )
    cycle = "EXISTS (WITH RECURSIVE chain(id) AS (SELECT NEW.replacement_interval_id UNION SELECT c.replacement_interval_id FROM task_work_corrections c JOIN chain ON c.original_interval_id=chain.id) SELECT 1 FROM chain WHERE id=NEW.original_interval_id)"
    identity = " OR ".join(
        f"NEW.{key} {distinct} OLD.{key}"
        for key in ("id", "tenant_id", "user_id", "task_id", "created_at")
    )
    return [
        (
            "context_insert",
            "task_activity_contexts",
            "INSERT",
            f"NOT COALESCE(({context_valid}),false)",
        ),
        (
            "context_update",
            "task_activity_contexts",
            "UPDATE",
            f"({identity}) OR NEW.version<>OLD.version+1 OR NEW.updated_at<OLD.updated_at OR NEW.elapsed_ms<OLD.elapsed_ms OR NEW.activity_event_id=OLD.activity_event_id OR NOT COALESCE(({context_valid}),false)",
        ),
        ("context_delete", "task_activity_contexts", "DELETE", "true"),
        (
            "correction_insert",
            "task_work_corrections",
            "INSERT",
            f"NOT COALESCE(({correction_valid}),false) OR {cycle}",
        ),
        ("correction_update", "task_work_corrections", "UPDATE", "true"),
        ("correction_delete", "task_work_corrections", "DELETE", "true"),
    ]


def statements(dialect):
    result = []
    for suffix, table, operation, invalid in specs(dialect):
        name = "zea_v5_" + suffix
        if dialect == "sqlite":
            result += [
                f"DROP TRIGGER IF EXISTS {name}",
                f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT CASE WHEN {invalid} THEN RAISE(ABORT,'task activity invariant violated') END; END",
            ]
        elif dialect == "postgresql":
            result += [
                f"CREATE OR REPLACE FUNCTION {name}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {invalid} THEN RAISE EXCEPTION 'task activity invariant violated' USING ERRCODE='23514'; END IF; RETURN {'OLD' if operation == 'DELETE' else 'NEW'}; END; $$",
                f"DROP TRIGGER IF EXISTS {name} ON {table}",
                f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_guard()",
            ]
        else:
            raise RuntimeError("Unsupported task activity database")
    if dialect == "postgresql":
        for table in ("task_activity_contexts", "task_work_corrections"):
            name = "zea_v5_" + table + "_truncate"
            result += [
                f"CREATE OR REPLACE FUNCTION {name}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'task activity history cannot be truncated' USING ERRCODE='23514'; END; $$",
                f"DROP TRIGGER IF EXISTS {name} ON {table}",
                f"CREATE TRIGGER {name} BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {name}_guard()",
            ]
    return result
