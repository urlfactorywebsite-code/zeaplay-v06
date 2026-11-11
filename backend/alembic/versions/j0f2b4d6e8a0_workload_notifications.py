"""Extend the existing notification inbox; no historical alerts or rewards."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "j0f2b4d6e8a0"
down_revision = "i9e1a3c5d7f9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError("Unsupported notification database")
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("SET LOCAL lock_timeout='5s'")
        bind.exec_driver_sql("SET LOCAL statement_timeout='120s'")
    elif not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    existing = {c["name"] for c in sa.inspect(bind).get_columns("push_subscriptions")}
    for column in [
        sa.Column("tenant_id", UUID(as_uuid=True)),
        sa.Column("binding_key", sa.String(36)),
    ]:
        if column.name not in existing:
            op.add_column("push_subscriptions", column)
    if "uq_push_binding_key" not in {
        i["name"] for i in sa.inspect(bind).get_indexes("push_subscriptions")
    }:
        op.create_index(
            "uq_push_binding_key", "push_subscriptions", ["binding_key"], unique=True
        )
    existing = {c["name"] for c in sa.inspect(bind).get_columns("notifications")}
    for column in [
        sa.Column("tenant_id", UUID(as_uuid=True)),
        sa.Column("dedupe_key", sa.String(128)),
        sa.Column("alert_kind", sa.String(64)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "delivery_pending", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "delivery_attempts", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("next_delivery_at", sa.DateTime(timezone=True)),
    ]:
        if column.name not in existing:
            op.add_column("notifications", column)
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("notifications")}
    for name, columns, unique in [
        ("uq_notification_recipient_event", ["user_id", "dedupe_key"], True),
        ("ix_notification_inbox", ["user_id", "created_at", "id"], False),
        ("ix_notification_delivery", ["delivery_pending", "next_delivery_at"], False),
    ]:
        if name not in indexes:
            options = (
                {
                    "postgresql_where": sa.text("dismissed_at IS NULL"),
                    "sqlite_where": sa.text("dismissed_at IS NULL"),
                }
                if name == "ix_notification_inbox"
                else {}
            )
            op.create_index(name, "notifications", columns, unique=unique, **options)
    existing = {
        c["name"] for c in sa.inspect(bind).get_columns("notification_preferences")
    }
    for column in [
        sa.Column(
            "sound_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "near_deadline_hours", sa.Integer(), server_default="24", nullable=False
        ),
        sa.Column("productive_capacity_hours", sa.Float()),
        sa.Column(
            "overtime_threshold_minutes",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("quiet_start", sa.String(5)),
        sa.Column("quiet_end", sa.String(5)),
    ]:
        if column.name not in existing:
            op.add_column("notification_preferences", column)
    if bind.dialect.name == "postgresql" and "ck_notification_workload_policy" not in {
        c["name"]
        for c in sa.inspect(bind).get_check_constraints("notification_preferences")
    }:
        op.create_check_constraint(
            "ck_notification_workload_policy",
            "notification_preferences",
            "near_deadline_hours > 0 AND overtime_threshold_minutes >= 0 AND (productive_capacity_hours IS NULL OR productive_capacity_hours > 0)",
        )
    import importlib
    import sys

    models = sys.modules.get("app.models") or sys.modules.get("backend.app.models")
    statements = importlib.import_module(
        models.__package__ + ".services.notification_schema"
    ).statements
    for statement in statements(bind.dialect.name):
        bind.exec_driver_sql(statement)


def downgrade():
    # Keeping durable alerts and dedupe keys is safer than a destructive downgrade.
    raise RuntimeError(
        "Phase 6 is additive. Roll back application code and retain notification columns/data; do not downgrade this revision."
    )
