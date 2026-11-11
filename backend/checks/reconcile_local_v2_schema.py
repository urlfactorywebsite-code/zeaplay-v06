"""Explicit additive reconciliation for the unversioned local development install.

Call only through a backup-first, writer-frozen operator session. This is not
startup DDL, a production rollout, or an Alembic baseline/stamp. The strict
historical migrations remain unchanged. Already-repaired installs are verified
without replaying old adoption revisions over newer records.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

REVISIONS = (
    "e5a7c9d1f3b5_task_audit_foundation",
    "f6b8d0e2a4c6_subtask_workflow",
    "g7c9e1f3a5d7_subtask_rewards",
    "h8d0f2a4c6e8_reward_accounting_guards",
    "i9e1a3c5d7f9_task_activity",
    "j0f2b4d6e8a0_workload_notifications",
    "k1a3c5e7f9b1_notification_queue_review",
)


def _revision(name):
    key = "_zea_local_reconciliation_" + name
    if key not in sys.modules:
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / (name + ".py")
        spec = importlib.util.spec_from_file_location(key, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


def original_snapshot(connection, columns=None):
    """Compare original columns/rows without exporting their private values."""
    inspector = sa.inspect(connection)
    columns = columns or {
        table: [c["name"] for c in inspector.get_columns(table)]
        for table in inspector.get_table_names() if table != "alembic_version"
    }
    preparer = connection.dialect.identifier_preparer
    values = {}
    for table, names in columns.items():
        quoted = ",".join(preparer.quote(name) for name in names)
        statement = f"SELECT {quoted} FROM {preparer.quote(table)}"
        rows = [json.dumps(list(row), default=str, sort_keys=True) for row in connection.exec_driver_sql(statement)]
        values[table] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()}
    return columns, values


def _verify(connection, gate_sql):
    # This install has no established historical Alembic baseline. Validate the
    # real guard/index/data contracts without claiming or fabricating one.
    models = sys.modules.get("app.models") or sys.modules.get("backend.app.models")
    # Ledger metadata lives in the existing ticket module, not core models.
    importlib.import_module(models.__package__ + ".tickets.models")
    inspector = sa.inspect(connection)
    for table in ("subtasks", "audit_events", "xp_ledger", "task_workflow_settings", "task_work_intervals", "task_work_corrections", "task_activity_contexts", "notifications", "notification_preferences", "push_subscriptions"):
        actual = {column["name"] for column in inspector.get_columns(table)}
        if not set(models.Base.metadata.tables[table].columns.keys()).issubset(actual):
            raise RuntimeError("Refusing incomplete V2 columns in " + table)
    body = gate_sql[gate_sql.index("DO $gate$"):gate_sql.index("\nSELECT\n    'PASS'")]
    start = body.index("    IF (SELECT count(*) FROM alembic_version)")
    end = body.index("    SELECT count(*) INTO missing_count", start)
    body = body[:start] + """    IF to_regclass('alembic_version') IS NOT NULL THEN
        RAISE EXCEPTION 'Refusing a versioned installation';
    END IF;
""" + body[end:]
    connection.execute(sa.text(body))


class _KnownEmptySettingsAdoption:
    """Project an explicitly verified startup-created later optional column.

    Only the Phase 1 adopter sees this projection, after the full real schema
    and emptiness checks below. Phase 3 sees and validates the real column.
    No column/data is removed, renamed, rewritten or hidden from later guards.
    """
    def __init__(self, inspector):
        self.inspector = inspector

    def get_columns(self, name, *args, **kwargs):
        columns = self.inspector.get_columns(name, *args, **kwargs)
        if name == "task_workflow_settings":
            return [c for c in columns if c["name"] != "reward_policy_data"]
        return columns

    def __getattr__(self, name):
        return getattr(self.inspector, name)


def reconcile(connection, *, gate_sql):
    """Caller owns the outer transaction and backup/freeze/target verification."""
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Local reconciliation requires PostgreSQL")
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if "alembic_version" in tables:
        raise RuntimeError("Refusing a versioned installation; use its reviewed migration plan")
    required = {"users", "tasks", "subtasks", "audit_events", "xp_ledger", "notifications", "notification_preferences", "push_subscriptions"}
    if not required.issubset(tables):
        raise RuntimeError("Refusing an unexpected local core schema")
    connection.exec_driver_sql("SET LOCAL lock_timeout='5s'")
    connection.exec_driver_sql("SET LOCAL statement_timeout='120s'")
    lock_tables = required | (tables & {"task_workflow_settings", "task_work_intervals", "task_activity_contexts", "task_work_corrections"})
    connection.exec_driver_sql("LOCK TABLE " + ",".join(sorted(lock_tables)) + " IN SHARE ROW EXCLUSIVE MODE")
    columns, before = original_snapshot(connection)
    child_columns = {c["name"] for c in inspector.get_columns("subtasks")}
    if "planned_start_date" in child_columns:
        _verify(connection, gate_sql)
        assert original_snapshot(connection, columns)[1] == before
        return {"mode": "verified_existing_repair", "original_tables_preserved": len(before), "alembic_stamped": False}
    if child_columns != {"id", "task_id", "title", "completed"}:
        raise RuntimeError("Refusing a partial or unexpected legacy subtask schema")
    known_extra = False
    if "task_workflow_settings" in tables:
        settings = {c["name"]: c for c in inspector.get_columns("task_workflow_settings")}
        baseline = {"tenant_id", "enabled", "point_policy_version", "activated_at", "version"}
        if set(settings) not in (baseline, baseline | {"reward_policy_data"}):
            raise RuntimeError("Refusing unknown workflow-settings schema drift")
        if connection.exec_driver_sql("SELECT 1 FROM task_workflow_settings LIMIT 1").first():
            raise RuntimeError("Refusing existing workflow policies; manual reconciliation required")
        if "reward_policy_data" in settings:
            column = settings["reward_policy_data"]
            if not column["nullable"] or not isinstance(column["type"], sa.JSON):
                raise RuntimeError("Refusing incompatible optional policy data")
            known_extra = True
    for table in ("task_work_intervals", "task_work_corrections", "task_activity_contexts"):
        if table in tables and connection.exec_driver_sql(f"SELECT 1 FROM {table} LIMIT 1").first():
            raise RuntimeError("Refusing existing V2 work records before legacy adoption")
    for name in REVISIONS:
        # Canonical models must already be loaded against an isolated bootstrap
        # engine by the operator/test wrapper; never import a live bootstrap here.
        module = _revision(name)
        previous_op, previous_sa = module.op, module.sa
        previous_offline = getattr(getattr(module, "context", None), "is_offline_mode", None)
        try:
            module.op = Operations(MigrationContext.configure(connection))
            if previous_offline is not None:
                module.context.is_offline_mode = lambda: False
            if name == REVISIONS[0] and known_extra:
                module.sa = SimpleNamespace(**{**vars(sa), "inspect": lambda bind: _KnownEmptySettingsAdoption(sa.inspect(bind))})
            module.upgrade()
        finally:
            module.op, module.sa = previous_op, previous_sa
            if previous_offline is not None:
                module.context.is_offline_mode = previous_offline
    _verify(connection, gate_sql)
    if original_snapshot(connection, columns)[1] != before:
        raise RuntimeError("Original data changed; rolling back local reconciliation")
    return {"mode": "additive_local_repair", "original_tables_preserved": len(before), "revisions_reused": len(REVISIONS), "known_empty_settings_adopted": known_extra, "alembic_stamped": False}
