"""Additional subtask rewards: additive storage, no activation or historical posting."""

import importlib
import re
import sys

import sqlalchemy as sa
from alembic import context, op

revision = "g7c9e1f3a5d7"
down_revision = "f6b8d0e2a4c6"
branch_labels = None
depends_on = None


def upgrade():
    if context.is_offline_mode():
        raise RuntimeError("Subtask rewards require online schema validation")
    bind = op.get_bind()
    if bind.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("Unsupported reward database")
    if (
        bind.dialect.name == "sqlite"
        and not bind.connection.driver_connection.in_transaction
    ):
        bind.exec_driver_sql("BEGIN")
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("SET LOCAL lock_timeout='5s'")
        bind.exec_driver_sql("SET LOCAL statement_timeout='120s'")
    module = sys.modules.get("app.models") or sys.modules.get("backend.app.models")
    ddl = importlib.import_module(
        module.__package__ + ".services.subtask_reward_schema"
    )
    with bind.begin_nested():
        before = {
            table: {c["name"]: c for c in sa.inspect(bind).get_columns(table)}
            for table in ("subtasks", "xp_ledger", "task_workflow_settings")
        }
        if "workflow_version" not in before["subtasks"]:
            raise RuntimeError("Apply Phase 2 before additional subtask rewards")
        for table, column in (
            (
                "subtasks",
                sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            ),
            ("subtasks", sa.Column("reward_timezone", sa.String(64), nullable=True)),
            ("xp_ledger", sa.Column("calculation_inputs", sa.JSON(), nullable=True)),
            (
                "task_workflow_settings",
                sa.Column("reward_policy_data", sa.JSON(), nullable=True),
            ),
        ):
            old = before[table].get(column.name)
            if not old:
                op.add_column(table, column)
            elif (
                not old["nullable"]
                or not isinstance(old["type"], type(column.type))
                or (
                    isinstance(column.type, sa.DateTime)
                    and bind.dialect.name == "postgresql"
                    and not old["type"].timezone
                )
            ):
                raise RuntimeError(f"Incompatible reward column: {table}.{column.name}")
        # This revision never creates/cuts over a tenant policy or posts a wallet.
        invalid = bind.execute(
            sa.text(
                "SELECT 1 FROM subtasks WHERE point_policy_version=:p AND (workflow_version<>2 OR created_at IS NULL OR reward_timezone IS NULL) LIMIT 1"
            ),
            {"p": ddl.POLICY},
        ).first()
        if invalid:
            raise RuntimeError(
                "Reconcile pre-existing reserved policy records; no retroactive adoption"
            )
        for _, table, operation, invalid in ddl.guard_specs(bind.dialect.name):
            if (
                operation == "INSERT"
                and bind.execute(
                    sa.text(f"SELECT 1 FROM {table} AS NEW WHERE {invalid} LIMIT 1")
                ).first()
            ):
                raise RuntimeError(
                    f"Reconcile incompatible reward state before migration: {table}"
                )
        for table, name, columns, unique, predicate in ddl.INDEXES:
            current = {i["name"]: i for i in sa.inspect(bind).get_indexes(table)}.get(
                name
            )
            if current:
                if (
                    current["column_names"] != list(columns)
                    or bool(current["unique"]) != unique
                    or re.sub(
                        r"[()\s]",
                        "",
                        str(
                            current.get("dialect_options", {}).get(
                                bind.dialect.name + "_where", ""
                            )
                        ).replace("::text", ""),
                    ).lower()
                    != re.sub(r"[()\s]", "", predicate or "").lower()
                ):
                    raise RuntimeError(f"Incompatible reward index: {name}")
            else:
                options = (
                    {
                        "sqlite_where": sa.text(predicate),
                        "postgresql_where": sa.text(predicate),
                    }
                    if predicate
                    else {}
                )
                op.create_index(name, table, list(columns), unique=unique, **options)
        for statement in ddl.statements(bind.dialect.name):
            op.execute(sa.text(statement))


def downgrade():
    raise RuntimeError(
        "Retain reward schema and immutable ledger on application rollback; roll forward safely"
    )
