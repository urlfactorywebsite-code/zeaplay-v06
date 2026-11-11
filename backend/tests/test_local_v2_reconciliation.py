"""Reconcile the observed old-column/startup-created-table local schema safely."""
# ruff: noqa: F811 -- guarded disposable database fixture
from pathlib import Path

import pytest
import sqlalchemy as sa

from backend.app.database import Base
from backend.checks import reconcile_local_v2_schema as repair
from backend.tests.test_phase7_migrations import before_v2, seed
from backend.tests.test_task_audit_foundation import engine  # noqa: F401

GATE = (Path(__file__).parents[1] / "sql" / "zeaplay_v2_phase7_readiness.sql").read_text(encoding="utf-8")


@pytest.fixture
def mixed(engine):
    if engine.dialect.name != "postgresql":
        pytest.skip("Observed local PostgreSQL adoption contract")
    with engine.begin() as connection:
        legacy = before_v2()
        legacy.create_all(connection)
        seed(connection, legacy)
        Base.metadata.create_all(connection)
    return engine


def test_mixed_local_schema_repair_preserves_original_rows_and_is_repeatable(mixed):
    with mixed.begin() as connection:
        columns, before = repair.original_snapshot(connection)
        result = repair.reconcile(connection, gate_sql=GATE)
        assert result["known_empty_settings_adopted"]
        assert not result["alembic_stamped"]
    with mixed.begin() as connection:
        assert repair.original_snapshot(connection, columns)[1] == before
        assert connection.exec_driver_sql("SELECT count(*) FROM subtasks WHERE workflow_version=0 AND point_policy_version='legacy' AND actual_start_at IS NULL AND actual_end_at IS NULL AND created_at IS NULL").scalar_one() == 500
        assert connection.exec_driver_sql("SELECT count(*) FROM xp_ledger WHERE record_version=2").scalar_one() == 0
        assert repair.reconcile(connection, gate_sql=GATE)["mode"] == "verified_existing_repair"
        assert "alembic_version" not in sa.inspect(connection).get_table_names()


@pytest.mark.parametrize("drift", ["versioned", "unknown_column", "policy"])
def test_refuses_unreviewed_local_adoption_without_mutation(mixed, drift):
    with mixed.begin() as connection:
        if drift == "versioned":
            connection.exec_driver_sql("CREATE TABLE alembic_version(version_num varchar(32))")
        elif drift == "unknown_column":
            connection.exec_driver_sql("ALTER TABLE task_workflow_settings ADD COLUMN unexpected_field text")
        else:
            connection.exec_driver_sql("INSERT INTO task_workflow_settings(tenant_id,point_policy_version,enabled,version) SELECT tenant_id,'legacy',false,1 FROM users LIMIT 1")
    with pytest.raises(RuntimeError, match="Refusing"), mixed.begin() as connection:
        repair.reconcile(connection, gate_sql=GATE)
    with mixed.connect() as connection:
        assert "planned_start_date" not in {c["name"] for c in sa.inspect(connection).get_columns("subtasks")}


def test_interrupted_local_repair_rolls_back_all_ddl_and_data(mixed, monkeypatch):
    revision = repair._revision(repair.REVISIONS[2])
    monkeypatch.setattr(revision, "upgrade", lambda: (_ for _ in ()).throw(RuntimeError("synthetic interruption")))
    with pytest.raises(RuntimeError, match="synthetic interruption"), mixed.begin() as connection:
        repair.reconcile(connection, gate_sql=GATE)
    with mixed.connect() as connection:
        assert "planned_start_date" not in {c["name"] for c in sa.inspect(connection).get_columns("subtasks")}
        assert connection.exec_driver_sql("SELECT count(*) FROM xp_ledger").scalar_one() == 100


def test_repeat_verification_rejects_missing_application_column(mixed):
    with mixed.begin() as connection:
        repair.reconcile(connection, gate_sql=GATE)
    with mixed.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE notification_preferences DROP COLUMN sound_enabled")
    with pytest.raises(RuntimeError, match="incomplete V2 columns"), mixed.begin() as connection:
        repair.reconcile(connection, gate_sql=GATE)
