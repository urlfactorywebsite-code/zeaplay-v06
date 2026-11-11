"""Harden task audit storage and add opt-in managed subtask workflow.

Existing checklist rows and rewards are untouched. Application rollback retains
this additive schema and its history; destructive downgrade is refused.
"""

import importlib
import sys

import sqlalchemy as sa
from alembic import context, op

revision = "f6b8d0e2a4c6"
down_revision = "e5a7c9d1f3b5"
branch_labels = None
depends_on = None


def upgrade():
    if context.is_offline_mode():
        raise RuntimeError("Workflow migration requires online schema validation")
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect not in ("postgresql", "sqlite"):
        raise RuntimeError("Workflow supports PostgreSQL and SQLite")
    if dialect == "postgresql":
        op.execute("SET LOCAL lock_timeout='5s'")
        op.execute("SET LOCAL statement_timeout='120s'")
    elif not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN")
    model_module = sys.modules.get("app.models") or sys.modules.get(
        "backend.app.models"
    )
    if model_module is None:
        raise RuntimeError("Load canonical ORM metadata before migrating")
    ddl = importlib.import_module(
        model_module.__package__ + ".services.task_audit_schema"
    )
    with bind.begin_nested():
        _upgrade(bind, ddl)


def _upgrade(bind, ddl):
    inspector = sa.inspect(bind)
    required = {
        "subtasks",
        "users",
        "tasks",
        "audit_events",
        "xp_ledger",
        "task_work_intervals",
        "task_workflow_settings",
    }
    if not required.issubset(inspector.get_table_names()):
        raise RuntimeError(
            "Apply and verify Phase 1 before the subtask workflow migration"
        )
    for table, columns in (
        ("xp_ledger", ["tenant_id", "idempotency_key"]),
        ("xp_ledger", ["tenant_id", "reversal_of_id"]),
        ("task_work_intervals", ["tenant_id", "request_id"]),
    ):
        indexes = inspector.get_indexes(table)
        constraints = inspector.get_unique_constraints(table)
        if not any(
            item["column_names"] == columns
            and item.get("unique", True)
            and item.get("dialect_options", {}).get(bind.dialect.name + "_where")
            is None
            for item in [*indexes, *constraints]
        ):
            raise RuntimeError(
                f"Reconcile missing unconditional idempotency constraint: {table}.{columns[-1]}"
            )
    for table, fields in {
        "subtasks": ("actual_start_at", "actual_end_at", "created_at"),
        "task_work_intervals": ("started_at", "ended_at", "created_at"),
        "task_workflow_settings": ("activated_at",),
    }.items():
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        for field in fields:
            typ = columns[field]["type"]
            if not isinstance(typ, sa.DateTime) or (
                bind.dialect.name == "postgresql" and not typ.timezone
            ):
                raise RuntimeError(
                    f"Reconcile UTC timestamp type before migration: {table}.{field}"
                )
    for table, refs in {
        "audit_events": {"task_id": "tasks", "subtask_id": "subtasks"},
        "xp_ledger": {
            "task_id": "tasks",
            "subtask_id": "subtasks",
            "activity_event_id": "audit_events",
            "reversal_of_id": "xp_ledger",
        },
        "task_work_intervals": {
            "task_id": "tasks",
            "subtask_id": "subtasks",
            "user_id": "users",
            "created_by_id": "users",
            "activity_event_id": "audit_events",
        },
    }.items():
        for column, target in refs.items():
            if bind.dialect.name == "sqlite":
                # SQLAlchemy may omit ON DELETE for SQLite ADD COLUMN inline
                # references. PRAGMA reports the engine's actual FK behavior.
                matching = any(
                    fk["from"] == column
                    and fk["table"] == target
                    and fk["to"] == "id"
                    and fk["on_delete"].upper() == "RESTRICT"
                    for fk in bind.exec_driver_sql(
                        f"PRAGMA foreign_key_list({table})"
                    ).mappings()
                )
            else:
                matching = any(
                    fk["constrained_columns"] == [column]
                    and fk["referred_table"] == target
                    and fk["referred_columns"] == ["id"]
                    and fk.get("options", {}).get("ondelete", "").upper() == "RESTRICT"
                    for fk in inspector.get_foreign_keys(table)
                )
            if not matching:
                raise RuntimeError(
                    f"Reconcile restrictive workflow reference: {table}.{column}"
                )
    for column in (
        sa.Column("workflow_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("workflow_status", sa.String(16), nullable=True),
    ):
        existing = {c["name"]: c for c in sa.inspect(bind).get_columns("subtasks")}
        if column.name not in existing:
            op.add_column("subtasks", column)
        elif existing[column.name]["nullable"] != column.nullable or not isinstance(
            existing[column.name]["type"], type(column.type)
        ):
            raise RuntimeError(f"Incompatible workflow column: subtasks.{column.name}")
        elif (
            column.name == "workflow_version"
            and str(existing[column.name].get("default"))
            .replace("::integer", "")
            .strip("()'\" ")
            != "0"
        ):
            raise RuntimeError(
                "Reconcile legacy workflow_version default before migration"
            )
        elif (
            column.name == "workflow_status"
            and existing[column.name]["type"].length is not None
            and existing[column.name]["type"].length < len("IN_PROGRESS")
        ):
            raise RuntimeError("Reconcile workflow_status capacity before migration")
    # Fail closed on incompatible existing values; do not repair historical data.
    different = "IS DISTINCT FROM" if bind.dialect.name == "postgresql" else "IS NOT"
    ownership_queries = {
        "audit_events": f"SELECT 1 FROM audit_events e LEFT JOIN tasks t ON t.id=e.task_id LEFT JOIN users u ON u.id=t.created_by_id LEFT JOIN users a ON a.id=e.actor_id WHERE e.audit_schema_version=2 AND (u.tenant_id {different} e.tenant_id OR a.tenant_id {different} e.tenant_id)",
        "xp_ledger": f"SELECT 1 FROM xp_ledger x LEFT JOIN users u ON u.id=x.user_id LEFT JOIN audit_events e ON e.id=x.activity_event_id WHERE x.record_version=2 AND (u.tenant_id {different} x.tenant_id OR e.tenant_id {different} x.tenant_id OR e.audit_schema_version {different} 2 OR e.task_id {different} x.task_id OR e.subtask_id {different} x.subtask_id)",
        "subtasks": "SELECT 1 FROM subtasks s JOIN tasks t ON t.id=s.task_id JOIN users u ON u.id=t.created_by_id LEFT JOIN task_workflow_settings p ON p.tenant_id=u.tenant_id AND p.point_policy_version=s.point_policy_version WHERE s.point_policy_version<>'legacy' AND p.activated_at IS NULL",
    }
    for table, query in ownership_queries.items():
        if bind.execute(sa.text(query + " LIMIT 1")).first():
            raise RuntimeError(f"Reconcile incompatible workflow ownership: {table}")
    for _, table, operation, invalid in ddl.task_audit_guard_specs_v2(
        bind.dialect.name
    ):
        if (
            operation == "INSERT"
            and bind.execute(
                sa.text(f"SELECT 1 FROM {table} AS NEW WHERE {invalid} LIMIT 1")
            ).first()
        ):
            raise RuntimeError(f"Reconcile incompatible workflow data: {table}")
    indexes = (
        *ddl.LOOKUP_INDEXES,
        (
            "subtasks",
            "ix_subtasks_task_workflow_status",
            ("task_id", "workflow_status"),
            None,
        ),
    )
    for table, name, columns, predicate in indexes:
        current = {
            index["name"]: index for index in sa.inspect(bind).get_indexes(table)
        }.get(name)
        if current:
            actual_predicate = str(
                current.get("dialect_options", {}).get(bind.dialect.name + "_where", "")
            ).strip("() ")
            if (
                current["column_names"] != list(columns)
                or current["unique"]
                or actual_predicate != (predicate or "")
            ):
                raise RuntimeError(f"Incompatible workflow lookup index: {name}")
        else:
            options = (
                {
                    "sqlite_where": sa.text(predicate),
                    "postgresql_where": sa.text(predicate),
                }
                if predicate
                else {}
            )
            op.create_index(name, table, list(columns), **options)
    for statement in ddl.task_audit_guard_statements_v2(bind.dialect.name):
        op.execute(sa.text(statement))


def downgrade():
    raise RuntimeError(
        "Retain additive workflow schema and history during application rollback; never discard post-backup events"
    )
