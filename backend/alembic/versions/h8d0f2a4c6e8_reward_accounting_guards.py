"""Forward-only accounting guards; never rewrite or recalculate old rewards."""

import importlib
import sys

import sqlalchemy as sa
from alembic import context, op

revision = "h8d0f2a4c6e8"
down_revision = "g7c9e1f3a5d7"
branch_labels = None
depends_on = None


def upgrade():
    if context.is_offline_mode():
        raise RuntimeError("Reward accounting requires online preflight")
    bind = op.get_bind()
    if bind.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("Unsupported reward database")
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("SET LOCAL lock_timeout='5s'")
        bind.exec_driver_sql("SET LOCAL statement_timeout='120s'")
        # Block writers between preflight and trigger installation. Reads remain
        # available; the bounded lock timeout prevents an unbounded rollout wait.
        bind.exec_driver_sql(
            "LOCK TABLE users, tasks, subtasks, xp_ledger IN SHARE ROW EXCLUSIVE MODE"
        )
    elif not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    model = sys.modules.get("app.models") or sys.modules.get("backend.app.models")
    ddl = importlib.import_module(
        model.__package__ + ".services.subtask_reward_guards_v4"
    )
    with bind.begin_nested():
        if "calculation_inputs" not in {
            c["name"] for c in sa.inspect(bind).get_columns("xp_ledger")
        }:
            raise RuntimeError("Apply Phase 3 before accounting hardening")
        for _, table, operation, invalid in ddl.guard_specs():
            # A task UPDATE guard is also valid against the current row image.
            invalid = invalid.replace("OLD.", "NEW.")
            if bind.execute(
                sa.text(f"SELECT 1 FROM {table} AS NEW WHERE {invalid} LIMIT 1")
            ).first():
                raise RuntimeError(
                    f"Inconsistent existing reward accounting in {table}; manual review required"
                )
        for statement in ddl.statements(bind.dialect.name):
            op.execute(sa.text(statement))


def downgrade():
    raise RuntimeError("Retain accounting guards and immutable history; roll forward")
