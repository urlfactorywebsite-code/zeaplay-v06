"""Disposable schema/repository checks; no installed app, providers or databases."""

import importlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, timezone
from threading import Barrier, Event

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app import schemas
from backend.app.database import Base
from backend.app.services import audit_logger as repo
from backend.app.tickets.models import XpLedger

UTC = timezone.utc


@pytest.fixture
def engine(tmp_path):
    url = os.getenv("ZEA_TASK_AUDIT_TEST_URL")
    if url:
        target = sa.engine.make_url(url)
        assert (
            target.host == "127.0.0.1"
            and target.database == "zea_subtask_phase1"
            and target.username == "phase1"
        ), "Only the disposable Phase 1 database is allowed"
    engine = sa.create_engine(url or f"sqlite:///{tmp_path / 'schema.db'}")
    namespace = "phase1_" + uuid.uuid4().hex
    if url:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public"
            )
            conn.exec_driver_sql(f'CREATE SCHEMA "{namespace}"')
        engine.dispose()

    @sa.event.listens_for(engine, "connect")
    def configure(connection, _):
        if url:
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{namespace}", public')
                cursor.execute("SET TIME ZONE 'UTC'")
            connection.commit()
        else:
            connection.create_function(
                "to_tsvector", 2, lambda lang, value: value, deterministic=True
            )
            connection.execute("PRAGMA foreign_keys=ON")

    yield engine
    if url:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{namespace}" CASCADE')
    engine.dispose()


@pytest.fixture
def harness(engine):
    Base.metadata.create_all(engine)
    first, other = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as db:
        for key, tenant, role in [
            ("owner", first, m.RoleEnum.OWNER),
            ("worker", first, m.RoleEnum.USER),
            ("watcher", first, m.RoleEnum.USER),
            ("foreign", other, m.RoleEnum.OWNER),
        ]:
            db.add(
                m.User(
                    id=key,
                    tenant_id=tenant,
                    name=key,
                    email=key + "@example.com",
                    role=role,
                    hashed_password="fixture",
                    points=100,
                )
            )
        db.commit()
        db.add_all(
            [
                m.Task(
                    id="task",
                    title="Preserve",
                    created_by_id="owner",
                    assigned_to_id="worker",
                ),
                m.Task(id="other", title="Foreign", created_by_id="foreign"),
            ]
        )
        db.commit()
        db.add(m.Subtask(id="legacy", task_id="task", title="Original", completed=True))
        db.get(m.Task, "task").followers = [db.get(m.User, "watcher")]
        db.commit()
    return engine, first, other


def activity(db, **changes):
    kwargs = {
        "actor_id": "owner",
        "task_id": "task",
        "data": {
            "event_type": "task.status_changed",
            "before": {"status": "TODO"},
            "after": {"status": "IN_PROGRESS"},
        },
    }
    kwargs.update(changes)
    return repo.record_task_activity(db, **kwargs)


def adjustment(event_id, **changes):
    values = {
        "user_id": "worker",
        "component_type": "BONUS",
        "points": 7,
        "policy_version": "v2",
        "idempotency_key": "fixture-key",
        "activity_event_id": event_id,
        "reason": "Synthetic adjustment",
    }
    values.update(changes)
    return values


def test_activation_only_new_subtasks_and_no_wallet_recalculation(harness):
    engine, tenant, _ = harness
    with Session(engine) as db:
        before = repo.create_policy_subtask(
            db,
            actor_id="owner",
            task_id="task",
            title="Before activation",
            planned_start_date="2026-11-02",
            planned_end_date="2026-11-03",
        )
        assert before.point_policy_version == "legacy"
        db.add(
            m.TaskWorkflowSettings(
                tenant_id=tenant,
                enabled=True,
                point_policy_version="v2",
                activated_at=m.utc_now() - timedelta(seconds=2),
            )
        )
        db.commit()
        after = repo.create_policy_subtask(
            db,
            actor_id="owner",
            task_id="task",
            title="After activation",
            planned_start_date="2026-11-02",
            planned_end_date="2026-11-03",
        )
        assert after.point_policy_version == "v2"
        assert db.get(m.Subtask, "legacy").point_policy_version == "legacy"
        assert db.get(m.Subtask, "legacy").completed is True
        assert db.get(m.User, "owner").points == db.get(m.User, "worker").points == 100
        # Old writers do not silently activate new reward rules.
        db.add(m.Subtask(id="old-writer", task_id="task", title="Compatible"))
        db.commit()
        assert db.get(m.Subtask, "old-writer").point_policy_version == "legacy"


def test_legacy_audit_backup_scope_uses_actor_and_new_events_use_tenant(harness):
    from backend.app.backups.scope import predicate

    engine, tenant, other = harness
    with Session(engine) as db:
        for key, actor in [("old-own", "owner"), ("old-foreign", "foreign")]:
            db.add(
                m.AuditEvent(
                    id=key,
                    actor_id=actor,
                    event_type="legacy",
                    entity_type="task",
                    entity_id="task",
                )
            )
        current = activity(db)
        db.commit()
        table = m.AuditEvent.__table__
        own = set(
            db.scalars(
                sa.select(table.c.id).where(predicate("audit_events", str(tenant)))
            )
        )
        foreign = set(
            db.scalars(
                sa.select(table.c.id).where(predicate("audit_events", str(other)))
            )
        )
        assert own == {"old-own", current.id}
        assert foreign == {"old-foreign"}


def test_future_activation_is_not_active_and_policy_cannot_be_retagged(harness):
    engine, tenant, _ = harness
    with Session(engine) as db:
        db.add(
            m.TaskWorkflowSettings(
                tenant_id=tenant,
                enabled=True,
                point_policy_version="future",
                activated_at=m.utc_now() + timedelta(days=1),
            )
        )
        db.commit()
        assert (
            repo.create_policy_subtask(
                db,
                actor_id="owner",
                task_id="task",
                title="Still legacy",
                planned_start_date="2026-11-02",
                planned_end_date="2026-11-03",
            ).point_policy_version
            == "legacy"
        )
        db.commit()
        with pytest.raises(sa.exc.IntegrityError):
            db.execute(
                sa.update(m.Subtask)
                .where(m.Subtask.id == "legacy")
                .values(point_policy_version="future")
            )
        db.rollback()


def test_policy_history_survives_deactivation_and_later_versions(harness):
    engine, tenant, _ = harness
    with Session(engine) as db:
        old = m.TaskWorkflowSettings(
            tenant_id=tenant,
            enabled=True,
            point_policy_version="v2",
            activated_at=m.utc_now() - timedelta(days=1),
        )
        db.add(old)
        db.commit()
        child = repo.create_policy_subtask(
            db,
            actor_id="owner",
            task_id="task",
            title="v2 child",
            planned_start_date="2026-11-02",
            planned_end_date="2026-11-03",
        )
        db.commit()
        old.enabled = False
        db.commit()
        db.add(
            m.TaskWorkflowSettings(
                tenant_id=tenant,
                enabled=True,
                point_policy_version="v3",
                activated_at=m.utc_now() - timedelta(seconds=2),
            )
        )
        db.commit()
        assert (
            repo.create_policy_subtask(
                db,
                actor_id="owner",
                task_id="task",
                title="v3 child",
                planned_start_date="2026-11-02",
                planned_end_date="2026-11-03",
            ).point_policy_version
            == "v3"
        )
        # The preserved activation row validates old-policy archive restores.
        db.add(
            m.Subtask(
                id="restored-v2",
                task_id="task",
                title="Restored",
                point_policy_version="v2",
                created_at=child.created_at,
            )
        )
        db.commit()
        assert db.get(m.Subtask, child.id).point_policy_version == "v2"
        for statement in [
            sa.delete(m.TaskWorkflowSettings).where(
                m.TaskWorkflowSettings.point_policy_version == "v2"
            ),
            sa.update(m.TaskWorkflowSettings)
            .where(m.TaskWorkflowSettings.point_policy_version == "v2")
            .values(activated_at=m.utc_now()),
        ]:
            with pytest.raises(sa.exc.IntegrityError):
                db.execute(statement)
            db.rollback()
        db.add(
            m.TaskWorkflowSettings(
                tenant_id=tenant,
                enabled=True,
                point_policy_version="duplicate",
                activated_at=m.utc_now(),
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            db.flush()
        db.rollback()


def test_activity_transaction_rollback_and_actor_rbac(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        row = activity(db)
        key = row.id
        assert row.created_at.utcoffset() == timedelta(0)
        db.rollback()
        assert db.get(m.AuditEvent, key) is None
        for actor, task in [
            ("foreign", "task"),
            ("owner", "other"),
            ("watcher", "task"),
        ]:
            with pytest.raises(HTTPException):
                activity(db, actor_id=actor, task_id=task)
        assert repo.list_task_activity(db, actor_id="watcher", task_id="task") == []


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_database_protects_activity_and_parent_history(harness, operation):
    engine, _, _ = harness
    with Session(engine) as db:
        row = activity(db)
        key = row.id
        db.commit()
        stmt = (
            sa.update(m.AuditEvent)
            .where(m.AuditEvent.id == key)
            .values(payload={"changed": True})
            if operation == "update"
            else sa.delete(m.AuditEvent).where(m.AuditEvent.id == key)
        )
        with pytest.raises(sa.exc.IntegrityError):
            db.execute(stmt)
        db.rollback()
        with pytest.raises(sa.exc.IntegrityError):
            db.execute(sa.delete(m.Task).where(m.Task.id == "task"))
        db.rollback()


@pytest.mark.parametrize(
    "kind", ["foreign_actor", "foreign_task", "wrong_child", "invalid_schema"]
)
def test_raw_sql_cannot_bypass_activity_ownership(harness, kind):
    engine, tenant, _ = harness
    values = {
        "id": "raw",
        "actor_id": "owner",
        "tenant_id": tenant,
        "task_id": "task",
        "audit_schema_version": 2,
        "event_type": "task.notes_changed",
        "entity_type": "task",
        "entity_id": "task",
        "created_at": m.utc_now(),
    }
    values.update(
        {
            "foreign_actor": {"actor_id": "foreign"},
            "foreign_task": {"task_id": "other", "entity_id": "other"},
            "wrong_child": {"subtask_id": "missing"},
            "invalid_schema": {"audit_schema_version": 99},
        }[kind]
    )
    with (
        engine.begin() as conn,
        pytest.raises(sa.exc.IntegrityError),
        conn.begin_nested(),
    ):
        conn.execute(m.AuditEvent.__table__.insert(), values)


def test_ledger_idempotency_append_only_reversal_and_no_balance_change(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        event = activity(db)
        first = repo.append_point_adjustment(
            db, actor_id="owner", task_id="task", data=adjustment(event.id)
        )
        assert (
            repo.append_point_adjustment(
                db, actor_id="owner", task_id="task", data=adjustment(event.id)
            ).id
            == first.id
        )
        with pytest.raises(HTTPException) as conflict:
            repo.append_point_adjustment(
                db,
                actor_id="owner",
                task_id="task",
                data=adjustment(event.id, points=8),
            )
        assert conflict.value.status_code == 409
        reversal = repo.append_point_adjustment(
            db,
            actor_id="owner",
            task_id="task",
            data=adjustment(
                event.id,
                component_type="REVERSAL",
                points=-7,
                idempotency_key="reversal",
                reversal_of_id=first.id,
            ),
        )
        assert reversal.points == -first.points
        assert db.get(m.User, "worker").points == 100
        db.commit()
        for statement in [
            sa.update(XpLedger).where(XpLedger.id == first.id).values(points=8),
            sa.delete(XpLedger).where(XpLedger.id == first.id),
        ]:
            with pytest.raises(sa.exc.IntegrityError):
                db.execute(statement)
            db.rollback()
        assert db.scalar(sa.select(sa.func.sum(XpLedger.points))) == 0


def test_database_unique_key_and_event_tenant_binding(harness):
    engine, tenant, other = harness
    with Session(engine) as db:
        event = activity(db)
        first = repo.append_point_adjustment(
            db, actor_id="owner", task_id="task", data=adjustment(event.id)
        )
        db.commit()
        for changes in [
            {},
            {"tenant_id": other},
            {"user_id": "foreign"},
            {"activity_event_id": "missing"},
            {"event_type": "wrong.event"},
            {"component_type": "PENALTY"},
            {"record_version": 99},
        ]:
            values = dict(
                adjustment(event.id),
                id=uuid.uuid4(),
                tenant_id=tenant,
                task_id="task",
                record_version=2,
                event_type=event.event_type,
                created_at=m.utc_now(),
            )
            values.update(changes)
            if changes:
                values["idempotency_key"] = uuid.uuid4().hex
            with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
                db.execute(XpLedger.__table__.insert(), values)
        assert first.points == 7


def test_legacy_children_cannot_receive_new_policy_points(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        event = activity(
            db, subtask_id="legacy", data={"event_type": "subtask.points_changed"}
        )
        with pytest.raises(HTTPException) as error:
            repo.append_point_adjustment(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id="legacy",
                data=adjustment(event.id),
            )
        assert error.value.status_code == 409
        assert db.get(m.User, "worker").points == 100


def test_manual_work_is_separate_idempotent_utc_and_transactional(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        data = {
            "started_at": "2026-11-02T10:00:00+05:30",
            "ended_at": "2026-11-02T10:45:00+05:30",
            "request_id": "manual-1",
            "note": "Synthetic work",
        }
        row = repo.record_manual_work(db, actor_id="owner", task_id="task", data=data)
        assert (row.ended_at - row.started_at).total_seconds() == 2700
        assert row.started_at.hour == 4 and row.started_at.minute == 30
        assert (
            repo.record_manual_work(db, actor_id="owner", task_id="task", data=data).id
            == row.id
        )
        assert db.get(m.Task, "task").completed_at is None
        assert db.get(m.User, "owner").points == 100
        key = row.id
        db.rollback()
        assert db.get(m.TaskWorkInterval, key) is None
        assert db.scalar(sa.select(sa.func.count()).select_from(m.AuditEvent)) == 0


def test_schedule_expected_version_nullable_fields_and_validation(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        row = repo.update_subtask_schedule(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id="legacy",
            data={
                "expected_version": 1,
                "planned_start_date": "2026-11-02",
                "planned_end_date": "2026-11-03",
                "priority_override": "HIGH",
            },
        )
        assert row.version == 2 and row.planned_start_date == date(2026, 11, 2)
        assert row.point_policy_version == "legacy" and row.completed
        with pytest.raises(HTTPException) as stale:
            repo.update_subtask_schedule(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id="legacy",
                data={"expected_version": 1, "priority_override": None},
            )
        assert stale.value.status_code == 409
        db.rollback()
    for payload in [
        {"expected_version": 1, "actual_start_at": "2026-11-02T10:00:00"},
        {
            "expected_version": 1,
            "planned_start_date": "2026-11-03",
            "planned_end_date": "2026-11-02",
        },
        {"expected_version": 1, "point_policy_version": "new"},
    ]:
        with pytest.raises(ValidationError):
            schemas.SubtaskScheduleUpdate.model_validate(payload)


def test_raw_manual_interval_requires_matching_event_actor_and_tenant(harness):
    engine, tenant, other = harness
    with Session(engine) as db:
        event = activity(db)
        db.commit()
        start = m.utc_now() - timedelta(hours=1)
        for changes in [
            {"tenant_id": other},
            {"user_id": "foreign"},
            {"created_by_id": "worker"},
            {"ended_at": start},
        ]:
            values = {
                "id": uuid.uuid4().hex,
                "tenant_id": tenant,
                "task_id": "task",
                "user_id": "owner",
                "created_by_id": "owner",
                "started_at": start,
                "ended_at": m.utc_now(),
                "request_id": uuid.uuid4().hex,
                "activity_event_id": event.id,
            }
            values.update(changes)
            with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
                db.execute(m.TaskWorkInterval.__table__.insert(), values)


def _phase2_settings_shape(conn):
    """Rehearse frozen Phase 1 against its supported schema, before Phase 3.

    Only this disposable test schema is changed. Production revisions remain
    frozen and must run before a later application bootstraps newer columns.
    """
    for name in ("zea_v3_policy_insert", "zea_v3_policy_update"):
        suffix = (
            " ON task_workflow_settings" if conn.dialect.name == "postgresql" else ""
        )
        conn.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}{suffix}")
    conn.exec_driver_sql(
        "ALTER TABLE task_workflow_settings DROP COLUMN reward_policy_data"
    )


def test_reapply_migration_to_metadata_created_install(harness, monkeypatch):
    engine, _, _ = harness
    migration = importlib.import_module(
        "backend.alembic.versions.e5a7c9d1f3b5_task_audit_foundation"
    )
    with engine.begin() as conn:
        _phase2_settings_shape(conn)
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(conn))
        )
        monkeypatch.setattr(migration.context, "is_offline_mode", lambda: False)
        migration.upgrade()
        migration.upgrade()
        assert (
            conn.execute(
                sa.text("SELECT title FROM subtasks WHERE id='legacy'")
            ).scalar_one()
            == "Original"
        )


def test_migration_refuses_weakened_active_policy_index(harness, monkeypatch):
    engine, _, _ = harness
    migration = importlib.import_module(
        "backend.alembic.versions.e5a7c9d1f3b5_task_audit_foundation"
    )
    with engine.begin() as conn:
        _phase2_settings_shape(conn)
        conn.exec_driver_sql("DROP INDEX uq_task_workflow_settings_active_tenant")
        conn.exec_driver_sql(
            "CREATE INDEX uq_task_workflow_settings_active_tenant ON task_workflow_settings(tenant_id)"
        )
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(conn))
        )
        monkeypatch.setattr(migration.context, "is_offline_mode", lambda: False)
        with pytest.raises(RuntimeError, match="uniqueness index"):
            migration.upgrade()
        assert (
            conn.execute(sa.text("SELECT COUNT(*) FROM audit_events")).scalar_one() == 0
        )


def test_point_append_savepoint_does_not_commit_callers_transaction(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        event = activity(db)
        key = event.id
        db.commit()
        row = repo.append_point_adjustment(
            db, actor_id="owner", task_id="task", data=adjustment(key)
        )
        entry_id = row.id
        db.rollback()
        assert db.get(XpLedger, entry_id) is None
        assert db.get(m.AuditEvent, key) is not None


@pytest.mark.parametrize(
    "values",
    [
        {"version": 0},
        {"priority_override": "CRITICAL"},
        {
            "planned_start_date": date(2026, 11, 3),
            "planned_end_date": date(2026, 11, 2),
        },
    ],
)
def test_database_rejects_invalid_schedule_even_without_repository(harness, values):
    engine, _, _ = harness
    with (
        engine.begin() as conn,
        pytest.raises(sa.exc.IntegrityError),
        conn.begin_nested(),
    ):
        conn.execute(
            sa.update(m.Subtask).where(m.Subtask.id == "legacy").values(**values)
        )


def test_postgres_concurrent_idempotent_append(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Requires the named disposable PostgreSQL database")
    with Session(engine) as db:
        key = activity(db).id
        db.commit()
    barrier = Barrier(2)

    def worker():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            row = repo.append_point_adjustment(
                db, actor_id="owner", task_id="task", data=adjustment(key)
            )
            entry_id = row.id
            db.commit()
            return entry_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert results[0] == results[1]
    with Session(engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(XpLedger)) == 1
        assert db.get(m.User, "worker").points == 100


def test_postgres_tenant_change_waits_for_pending_activity(harness):
    engine, tenant, other = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    attempted = Event()

    def move_actor():
        with Session(engine) as second:
            attempted.set()
            try:
                second.execute(
                    sa.update(m.User)
                    .where(m.User.id == "owner")
                    .values(tenant_id=other)
                )
                second.commit()
                return "moved"
            except sa.exc.IntegrityError:
                second.rollback()
                return "rejected"

    with Session(engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        activity(first)
        future = pool.submit(move_actor)
        assert attempted.wait(timeout=5)
        try:
            with pytest.raises(TimeoutError):
                future.result(timeout=0.25)
        finally:
            first.commit()
        assert future.result(timeout=10) == "rejected"
        first.expire_all()
        assert first.get(m.User, "owner").tenant_id == tenant
