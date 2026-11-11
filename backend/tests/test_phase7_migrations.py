"""Rehearse all V2 revisions together on a synthetic pre-V2 schema."""
# ruff: noqa: F811 -- disposable engine fixture
import importlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from backend.app import models as m
from backend.tests.test_subtask_schema_rehearsal import fingerprint, old_schema
from backend.tests.test_task_audit_foundation import engine  # noqa: F401

REVISIONS = (
    "e5a7c9d1f3b5_task_audit_foundation", "f6b8d0e2a4c6_subtask_workflow",
    "g7c9e1f3a5d7_subtask_rewards", "h8d0f2a4c6e8_reward_accounting_guards",
    "i9e1a3c5d7f9_task_activity", "j0f2b4d6e8a0_workload_notifications",
    "k1a3c5e7f9b1_notification_queue_review",
)


def before_v2():
    metadata = old_schema()
    for name in ("task_activity_contexts", "task_work_corrections"):
        if name in metadata.tables:
            metadata.remove(metadata.tables[name])
    additions = {
        "subtasks": {"deleted_at", "reward_timezone"},
        "xp_ledger": {"calculation_inputs"},
        "notifications": {"tenant_id", "dedupe_key", "alert_kind", "dismissed_at", "delivery_pending", "delivery_attempts", "next_delivery_at"},
        "notification_preferences": {"sound_enabled", "near_deadline_hours", "productive_capacity_hours", "overtime_threshold_minutes", "quiet_start", "quiet_end"},
        "push_subscriptions": {"tenant_id", "binding_key"},
    }
    for name, fields in additions.items():
        table = metadata.tables[name]
        for index in list(table.indexes):
            if any(column.name in fields for column in index.columns) or any(
                field in str(index.dialect_options[dialect].get("where", ""))
                for field in fields for dialect in ("sqlite", "postgresql")
            ):
                table.indexes.remove(index)
        for constraint in list(table.constraints):
            if any(column.name in fields for column in constraint.columns) or (
                isinstance(constraint, sa.CheckConstraint) and any(field in str(constraint.sqltext) for field in fields)
            ):
                table.constraints.remove(constraint)
        for column in list(table.columns):
            if column.name in fields:
                table._columns.remove(column)
    return metadata


def apply(connection, monkeypatch, names=REVISIONS):
    for name in names:
        module = importlib.import_module("backend.alembic.versions." + name)
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        if hasattr(module, "context"):
            monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        module.upgrade()


def seed(connection, metadata):
    instant = datetime(2020, 2, 29, 12, tzinfo=UTC)
    tenant = uuid.uuid4()
    connection.execute(metadata.tables["users"].insert(), [{
        "id": key, "tenant_id": tenant, "name": key, "email": key + "@example.invalid",
        "hashed_password": "synthetic-not-a-credential", "role": m.RoleEnum.OWNER,
        "points": 1234,
    } for key in ("creator", "employee")])
    connection.execute(metadata.tables["tasks"].insert(), [{
        "id": f"old-task-{i}", "title": f"Historical {i}", "created_by_id": "creator",
        "assigned_to_id": "employee", "status": m.TaskStatusEnum.DONE, "priority": m.TaskPriorityEnum.HIGH,
        "created_at": instant, "updated_at": instant,
    } for i in range(100)])
    connection.execute(metadata.tables["subtasks"].insert(), [{
        "id": f"old-child-{i}", "task_id": f"old-task-{i % 100}", "title": f"Checklist {i}", "completed": True,
    } for i in range(500)])
    connection.execute(metadata.tables["xp_ledger"].insert(), [{
        "id": uuid.uuid4(), "tenant_id": tenant, "user_id": "employee", "event_type": "historical",
        "points": 7, "ref_type": "ticket", "ref_id": str(i), "created_at": instant,
    } for i in range(100)])
    connection.execute(metadata.tables["audit_events"].insert(), [{
        "id": f"old-event-{i}", "actor_id": "creator", "event_type": "task.updated",
        "entity_type": "task", "entity_id": f"old-task-{i % 100}", "created_at": instant,
        "payload": {"historical": True},
    } for i in range(200)])
    connection.execute(metadata.tables["notifications"].insert(), [{
        "id": f"old-note-{i}", "user_id": "employee", "type": m.NotificationTypeEnum.TASK_ASSIGNED,
        "message": "Historical inbox", "is_read": i % 2 == 0, "created_at": instant,
    } for i in range(100)])


def test_all_v2_upgrades_repeat_without_rewriting_history(engine, monkeypatch, record_property):
    legacy = before_v2()
    with engine.begin() as connection:
        legacy.create_all(connection)
        seed(connection, legacy)
        fingerprints = {table.name: fingerprint(connection, table) for table in legacy.sorted_tables}
    # Retry each revision before advancing. Replaying an older adoption guard
    # over a newer schema is deliberately forbidden; Alembic head is a no-op.
    for revision in REVISIONS:
        for _ in range(2):
            with engine.begin() as connection:
                apply(connection, monkeypatch, (revision,))
                assert {table.name: fingerprint(connection, table) for table in legacy.sorted_tables} == fingerprints
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM subtasks WHERE point_policy_version='legacy' AND workflow_version=0 AND actual_start_at IS NULL AND actual_end_at IS NULL AND created_at IS NULL")) == 500
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM xp_ledger WHERE record_version=2")) == 0
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM audit_events WHERE audit_schema_version=2")) == 0
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM notifications WHERE delivery_pending IS TRUE")) == 0
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM users WHERE points=1234")) == 2
        indexes = {row["name"] for row in sa.inspect(connection).get_indexes("notifications")}
        assert "ix_notification_pending_chronology" in indexes
    record_property("migration_rehearsal", json.dumps({"upgrades": 2, "legacy_subtasks": 500, "legacy_rewards": 100, "original_tables_unchanged": len(fingerprints)}))


def test_postgres_interrupted_revision_chain_is_transactional(engine, monkeypatch):
    if engine.dialect.name != "postgresql":
        pytest.skip("Transactional PostgreSQL DDL rollback")
    legacy = before_v2()
    with engine.begin() as connection:
        legacy.create_all(connection)
        seed(connection, legacy)
    with pytest.raises(RuntimeError, match="synthetic migration interruption"), engine.begin() as connection:
        apply(connection, monkeypatch, REVISIONS[:3])
        raise RuntimeError("synthetic migration interruption")
    with engine.connect() as connection:
        assert "planned_start_date" not in {column["name"] for column in sa.inspect(connection).get_columns("subtasks")}
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM xp_ledger")) == 100
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM users WHERE points=1234")) == 2


def test_postgres_rollout_gate_is_read_only_and_rejects_wrong_revision(engine, monkeypatch):
    if engine.dialect.name != "postgresql":
        pytest.skip("Production PostgreSQL rollout gate")
    legacy = before_v2()
    with engine.begin() as connection:
        legacy.create_all(connection)
        seed(connection, legacy)
        apply(connection, monkeypatch)
        MigrationContext.configure(connection)._ensure_version_table()
        connection.exec_driver_sql("INSERT INTO alembic_version(version_num) VALUES ('k1a3c5e7f9b1')")
        before = {table.name: fingerprint(connection, table) for table in legacy.sorted_tables}
    script = (Path(__file__).parents[1] / "sql" / "zeaplay_v2_phase7_readiness.sql").read_text(encoding="utf-8")
    with engine.connect() as connection:
        connection.execute(sa.text(script))
        assert {table.name: fingerprint(connection, table) for table in legacy.sorted_tables} == before
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num='unexpected'")
    with engine.connect() as connection, pytest.raises(sa.exc.DBAPIError, match="Unexpected migration revision"):
        connection.execute(sa.text(script))
