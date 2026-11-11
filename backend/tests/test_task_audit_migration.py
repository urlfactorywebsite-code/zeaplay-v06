"""Upgrade the actual legacy shape without inventing events, times or points."""
# ruff: noqa: F811 -- pytest injects the imported disposable engine fixture.

import importlib
import uuid
from datetime import datetime

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from backend.tests.test_task_audit_foundation import engine  # noqa: F401


def legacy_tables():
    md = sa.MetaData()
    sa.Table(
        "users",
        md,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("points", sa.Integer, nullable=False),
    )
    sa.Table(
        "tasks",
        md,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("assigned_to_id", sa.String(36)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    sa.Table(
        "subtasks",
        md,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("completed", sa.Boolean, nullable=False),
    )
    sa.Table(
        "audit_events",
        md,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    sa.Table(
        "xp_ledger",
        md,
        sa.Column("id", sa.UUID, primary_key=True),
        sa.Column("tenant_id", sa.UUID, nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("points", sa.Integer, nullable=False),
        sa.Column("ref_type", sa.String(100)),
        sa.Column("ref_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    return md


def test_legacy_upgrade_preserves_rows_rewards_and_unknown_timestamps(
    engine, monkeypatch
):
    md = legacy_tables()
    migration = importlib.import_module(
        "backend.alembic.versions.e5a7c9d1f3b5_task_audit_foundation"
    )
    tenant = uuid.uuid4()
    old = datetime(2020, 1, 2, 3, 4, 5)  # noqa: DTZ001 -- legacy naive fixture
    with engine.begin() as conn:
        md.create_all(conn)
        conn.execute(
            md.tables["users"].insert(),
            {"id": "user", "tenant_id": tenant, "points": 321},
        )
        conn.execute(
            md.tables["tasks"].insert(),
            {
                "id": "task",
                "created_by_id": "user",
                "assigned_to_id": "user",
                "status": "DONE",
                "updated_at": old,
            },
        )
        conn.execute(
            md.tables["subtasks"].insert(),
            {
                "id": "child",
                "task_id": "task",
                "title": "Keep title",
                "completed": True,
            },
        )
        conn.execute(
            md.tables["audit_events"].insert(),
            {
                "id": "old-event",
                "actor_id": "user",
                "event_type": "task.updated",
                "entity_type": "task",
                "entity_id": "task",
                "payload": {"fields": ["title"]},
                "created_at": old,
            },
        )
        conn.execute(
            md.tables["xp_ledger"].insert(),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant,
                "user_id": "user",
                "event_type": "legacy",
                "points": 17,
                "created_at": old,
            },
        )
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(conn))
        )
        monkeypatch.setattr(migration.context, "is_offline_mode", lambda: False)
        migration.upgrade()
        migration.upgrade()
        row = conn.execute(sa.text("SELECT * FROM subtasks")).mappings().one()
        assert (
            row["id"] == "child" and row["title"] == "Keep title" and row["completed"]
        )
        assert row["point_policy_version"] == "legacy" and row["version"] == 1
        assert all(
            row[key] is None
            for key in [
                "planned_start_date",
                "planned_end_date",
                "actual_start_at",
                "actual_end_at",
                "created_at",
                "priority_override",
            ]
        )
        assert conn.execute(sa.text("SELECT points FROM users")).scalar_one() == 321
        assert conn.execute(sa.text("SELECT points FROM xp_ledger")).scalar_one() == 17
        event = conn.execute(sa.text("SELECT * FROM audit_events")).mappings().one()
        assert (
            event["id"] == "old-event"
            and event["audit_schema_version"] == 1
            and event["task_id"] is None
            and event["tenant_id"] is None
        )
        assert (
            conn.execute(
                sa.text("SELECT COUNT(*) FROM task_work_intervals")
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                sa.text("SELECT COUNT(*) FROM task_workflow_settings")
            ).scalar_one()
            == 0
        )
        assert "ix_audit_events_tenant_task_time" in {
            i["name"] for i in sa.inspect(conn).get_indexes("audit_events")
        }


def test_failed_upgrade_rolls_back_ddl_and_never_repairs_ambiguous_core(
    engine, monkeypatch
):
    migration = importlib.import_module(
        "backend.alembic.versions.e5a7c9d1f3b5_task_audit_foundation"
    )
    with engine.begin() as conn:
        legacy_tables().create_all(conn)
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(conn))
        )
        monkeypatch.setattr(migration.context, "is_offline_mode", lambda: False)
        original = migration._index

        def fail(*args, **kwargs):
            raise RuntimeError("Synthetic index failure")

        monkeypatch.setattr(migration, "_index", fail)
        with pytest.raises(RuntimeError, match="Synthetic index failure"):
            migration.upgrade()
        assert "planned_start_date" not in {
            c["name"] for c in sa.inspect(conn).get_columns("subtasks")
        }
        assert "task_work_intervals" not in sa.inspect(conn).get_table_names()
        monkeypatch.setattr(migration, "_index", original)
        migration.upgrade()


def test_destructive_downgrade_and_offline_guessing_are_refused(monkeypatch):
    migration = importlib.import_module(
        "backend.alembic.versions.e5a7c9d1f3b5_task_audit_foundation"
    )
    monkeypatch.setattr(migration.context, "is_offline_mode", lambda: True)
    with pytest.raises(RuntimeError, match="online"):
        migration.upgrade()
    with pytest.raises(RuntimeError, match="verified backup"):
        migration.downgrade()
