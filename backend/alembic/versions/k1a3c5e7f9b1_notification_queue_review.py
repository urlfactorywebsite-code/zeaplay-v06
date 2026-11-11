"""Add a bounded pending-queue lookup; retain existing rows and indexes."""

import sqlalchemy as sa
from alembic import op

revision = "k1a3c5e7f9b1"
down_revision = "j0f2b4d6e8a0"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("SET LOCAL lock_timeout='5s'")
        bind.exec_driver_sql("SET LOCAL statement_timeout='120s'")
    elif bind.dialect.name == "sqlite":
        if not bind.connection.driver_connection.in_transaction:
            bind.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        raise RuntimeError("Unsupported notification database")
    if "ix_notification_pending_chronology" not in {
        i["name"] for i in sa.inspect(bind).get_indexes("notifications")
    }:
        op.create_index(
            "ix_notification_pending_chronology",
            "notifications",
            ["created_at", "id"],
            postgresql_where=sa.text("delivery_pending IS TRUE"),
            sqlite_where=sa.text("delivery_pending IS TRUE"),
        )


def downgrade():
    # Keeping this additive index permits application rollback without DDL or
    # loss of durable receipts, retries and idempotency tombstones.
    pass
