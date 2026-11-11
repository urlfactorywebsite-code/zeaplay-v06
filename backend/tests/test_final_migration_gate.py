"""Reject silent production guard drift using real PostgreSQL catalog state."""
# ruff: noqa: F811 -- shared disposable fixture
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext

from backend.tests.test_phase7_migrations import apply, before_v2, seed
from backend.tests.test_task_audit_foundation import engine  # noqa: F401


@pytest.mark.parametrize("drift", [
    "DROP TRIGGER zea_ledger_update ON xp_ledger",
    "ALTER TABLE xp_ledger DISABLE TRIGGER zea_ledger_delete",
    "ALTER TABLE xp_ledger ENABLE REPLICA TRIGGER zea_ledger_update",
    "DROP TRIGGER zea_v5_context_update ON task_activity_contexts",
    "DROP INDEX uq_xp_ledger_tenant_idempotency; CREATE UNIQUE INDEX uq_xp_ledger_tenant_idempotency ON xp_ledger(id)",
    "DROP INDEX ix_notification_pending_chronology; CREATE INDEX ix_notification_pending_chronology ON notifications(id)",
])
def test_readiness_rejects_missing_disabled_replica_or_spoofed_guards(engine, monkeypatch, drift):
    if engine.dialect.name != "postgresql":
        pytest.skip("Production PostgreSQL catalog guard")
    with engine.begin() as connection:
        legacy = before_v2()
        legacy.create_all(connection)
        seed(connection, legacy)
        apply(connection, monkeypatch)
        MigrationContext.configure(connection)._ensure_version_table()
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('k1a3c5e7f9b1')")
        connection.exec_driver_sql(drift)
    script = (Path(__file__).parents[1] / "sql" / "zeaplay_v2_phase7_readiness.sql").read_text(encoding="utf-8")
    with engine.connect() as connection, pytest.raises(sa.exc.DBAPIError, match="(guards|indexes) missing"):
        connection.execute(sa.text(script))
