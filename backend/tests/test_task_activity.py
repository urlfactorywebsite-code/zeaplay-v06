"""Phase 4: isolated personal activity, productive time and transactional tests."""

# ruff: noqa: F811 -- imported pytest disposable fixtures.
import importlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace as Row
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app import schemas
from backend.app.services import subtasks
from backend.app.services import task_activity as activity
from backend.tests.test_backup_manager import harness as backup_harness  # noqa: F401
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401
from backend.tests.test_task_tabs_review import harness as api_harness  # noqa: F401

UTC = timezone.utc
NOW = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch):
    state = [NOW]
    monkeypatch.setattr(m, "utc_now", lambda: state[0])
    return state


def seed(db, count=6):
    for index in range(count):
        db.add(
            m.Task(
                id=f"work-{index}",
                title=f"Work {index}",
                created_by_id="owner",
                assigned_to_id="worker",
            )
        )
    db.commit()


def change(db, task="work-0", action="START", user="owner", **values):
    return activity.command(db, actor_id=user, task_id=task, action=action, **values)


def confirmed(db, start, end, task="work-0", **values):
    data = schemas.ConfirmedWorkInput(
        started_at=start,
        ended_at=end,
        confirmed=True,
        request_id=str(uuid.uuid4()),
        **values,
    )
    return activity.record_work(db, actor_id="owner", task_id=task, data=data)


def test_five_parents_sixth_denied_and_pause_resume(harness, clock):
    engine, _, _ = harness
    with Session(engine, autoflush=False) as db:
        seed(db)
        for i in range(5):
            change(db, f"work-{i}", expected_version=0)
        db.commit()
        assert activity.snapshot(db, actor_id="owner")["active_count"] == 5
        with pytest.raises(HTTPException) as error:
            change(db, "work-5", expected_version=0)
        assert (
            error.value.status_code == 409
            and "five active parent" in error.value.detail
        )
        db.commit()
        change(db, action="PAUSE", expected_version=1)
        change(db, "work-5", expected_version=0)
        with pytest.raises(HTTPException) as error:
            change(db, action="RESUME", expected_version=2)
        assert error.value.status_code == 409
        change(db, "work-5", "PAUSE", expected_version=1)
        change(db, action="RESUME", expected_version=2)
        db.commit()
        assert activity.snapshot(db, actor_id="owner")["active_count"] == 5
        # Globally shared status does not define the user's slot count.
        assert db.get(m.Task, "work-0").status == m.TaskStatusEnum.TODO


def test_personal_elapsed_reload_switch_and_replay_do_not_write_actuals(harness, clock):
    engine, _, _ = harness
    with Session(engine, autoflush=False) as db:
        seed(db)
        children = [
            subtasks.create(
                db,
                actor_id="owner",
                task_id="work-0",
                data={
                    "title": name,
                    "planned_start_date": "2026-11-02",
                    "planned_end_date": "2026-11-03",
                },
            )
            for name in ("A", "B")
        ]
        key = children[0].id
        request = str(uuid.uuid4())
        row = change(db, subtask_id=key, expected_version=0, request_id=request)
        assert row.version == 1
        clock[0] += timedelta(seconds=60)
        row = change(db, subtask_id=children[1].id, expected_version=1)
        assert row.slot == 1 and row.elapsed_ms == 60000
        clock[0] += timedelta(seconds=30)
        change(db, action="PAUSE", subtask_id=children[1].id, expected_version=2)
        db.commit()
        # Replaying an acknowledged Start after Pause cannot restart work.
        change(db, subtask_id=key, expected_version=0, request_id=request)
        assert row.status == "PAUSED" and row.version == 3
        assert all(
            c.actual_start_at is None and c.actual_end_at is None for c in children
        )
    clock[0] += timedelta(hours=2)
    with Session(engine, autoflush=False) as db:
        result = activity.snapshot(db, actor_id="owner")
        assert (
            result["active_count"] == 0
            and result["contexts"][0]["elapsed_seconds"] == 90
        )
        assert result["contexts"][0]["subtask_elapsed_seconds"] == 30
        change(db, action="RESUME", subtask_id=row.subtask_id, expected_version=3)
        db.commit()
    clock[0] += timedelta(seconds=15)
    with Session(engine) as db:
        result = activity.snapshot(db, actor_id="owner")
        assert result["contexts"][0]["elapsed_seconds"] == 105
        assert result["contexts"][0]["subtask_elapsed_seconds"] == 45
        assert result["workload"]["manual_seconds"] == 0


def test_same_parent_and_different_users_have_independent_slots(harness, clock):
    engine, _, _ = harness
    with Session(engine) as db:
        seed(db)
        for user in ("owner", "worker"):
            for i in range(5):
                change(db, f"work-{i}", user=user)
        db.commit()
        assert activity.snapshot(db, actor_id="owner")["active_count"] == 5
        assert activity.snapshot(db, actor_id="worker")["active_count"] == 5
        assert (
            db.scalar(sa.select(sa.func.count()).select_from(m.TaskActivityContext))
            == 10
        )


def test_manual_confirmation_overlap_correction_and_idempotency(harness, clock):
    engine, _, _ = harness
    with Session(engine, autoflush=False) as db:
        seed(db)
        start = NOW.replace(hour=9, minute=0)
        row = confirmed(db, start, start + timedelta(hours=1))
        data = schemas.ConfirmedWorkInput(
            started_at=start,
            ended_at=start + timedelta(hours=1),
            confirmed=True,
            request_id=row.request_id,
        )
        assert (
            activity.record_work(db, actor_id="owner", task_id="work-0", data=data).id
            == row.id
        )
        with pytest.raises(HTTPException, match="409") as error:
            confirmed(
                db, start + timedelta(minutes=30), start + timedelta(hours=2), "work-1"
            )
        assert "overlaps" in error.value.detail and row.id in error.value.detail
        replacement = confirmed(
            db, start, start + timedelta(minutes=30), supersedes_id=row.id
        )
        confirmed(
            db, start + timedelta(minutes=30), start + timedelta(hours=1), "work-1"
        )
        db.commit()
        assert row.ended_at == start + timedelta(hours=1)  # original unchanged
        assert replacement.id != row.id
        result = activity.snapshot(db, actor_id="owner")
        assert result["workload"]["manual_seconds"] == 3600
        assert result["active_count"] == 0
        assert db.get(m.Task, "work-0").completed_at is None
        with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
            db.execute(sa.update(m.TaskWorkCorrection).values(request_id="mutated"))
    for confirm in (False, 1, "true"):
        with pytest.raises(ValueError):
            schemas.ConfirmedWorkInput(
                started_at=NOW,
                ended_at=NOW + timedelta(hours=1),
                request_id="bad",
                confirmed=confirm,
            )


def test_union_allocates_historical_overlap_once_across_scopes():
    def interval(key, begin, end, task):
        return Row(
            id=key,
            task_id=task,
            subtask_id=None,
            created_at=NOW,
            started_at=NOW + timedelta(minutes=begin),
            ended_at=NOW + timedelta(minutes=end),
        )

    rows = [
        interval("a", 0, 60, "one"),
        interval("b", 30, 90, "two"),
        interval("c", 40, 50, "one"),
    ]
    result = activity.allocate(rows)
    assert result["total_seconds"] == 90 * 60 and result["overlap_seconds"] == 40 * 60
    assert result["by_scope"] == {("one", None): 3600, ("two", None): 1800}
    assert activity.allocate(list(reversed(rows))) == result
    assert (
        activity.allocate(
            rows, NOW + timedelta(minutes=45), NOW + timedelta(minutes=75)
        )["total_seconds"]
        == 1800
    )


def test_capacity_is_configured_and_breaks_are_not_double_deducted():
    values = {
        prefix + suffix: None
        for prefix in ("morning_break", "lunch_break", "evening_break")
        for suffix in ("_start", "_end")
    }
    user = Row(shift_start=None, shift_end=None, **values)
    assert activity.capacity(user, NOW.date(), ZoneInfo("UTC")) is None
    user.shift_start, user.shift_end = "09:00", "17:00"
    user.morning_break_start, user.morning_break_end = "12:00", "12:30"
    user.lunch_break_start, user.lunch_break_end = "12:15", "13:00"
    assert activity.capacity(user, NOW.date(), ZoneInfo("UTC")) == 7 * 3600
    user.shift_start, user.shift_end = "22:00", "06:00"
    user.morning_break_start = user.morning_break_end = user.lunch_break_start = (
        user.lunch_break_end
    ) = None
    assert activity.capacity(user, NOW.date(), ZoneInfo("UTC")) == 8 * 3600


def test_tenant_rbac_observer_and_manager_visibility(harness, clock):
    engine, _, _ = harness
    with Session(engine) as db:
        seed(db)
        change(db)
        with pytest.raises(HTTPException) as error:
            change(db, user="foreign")
        assert error.value.status_code == 404
        with pytest.raises(HTTPException) as error:
            change(db, user="watcher")
        assert error.value.status_code == 403
        with pytest.raises(HTTPException):
            activity.snapshot(db, actor_id="worker", user_id="owner")
        db.get(m.User, "watcher").role = m.RoleEnum.MANAGER
        db.get(m.User, "worker").manager_id = "watcher"
        db.commit()
        report = activity.snapshot(db, actor_id="watcher", user_id="worker")
        assert report["read_only"]
        with pytest.raises(HTTPException):
            activity.snapshot(db, actor_id="watcher", user_id="owner")
        for subject in ("missing", "foreign"):
            with pytest.raises(HTTPException) as hidden:
                activity.snapshot(db, actor_id="watcher", user_id=subject)
            assert hidden.value.status_code == 404


def test_postgres_concurrent_six_starts_and_parallel_resume(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Real PostgreSQL concurrency required")
    with Session(engine) as db:
        seed(db)
    gate = Barrier(6)

    def start(index):
        with Session(engine, autoflush=False) as db:
            gate.wait(timeout=15)
            try:
                change(db, f"work-{index}", expected_version=0)
                db.commit()
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        values = [pool.submit(start, i) for i in range(6)]
        assert sorted(f.result(timeout=45) for f in values) == [200] * 5 + [409]
    with Session(engine) as db:
        assert activity.snapshot(db, actor_id="owner")["active_count"] == 5


def test_workflow_start_cannot_bypass_limit_or_write_actuals(api_harness):
    client, engine, identity = api_harness
    for index in range(6):
        with Session(engine) as db:
            db.add(m.Task(id=f"work-{index}", title="Work", created_by_id="owner"))
            db.commit()
    for index in range(5):
        response = client.patch(f"/tasks/work-{index}", json={"status": "IN_PROGRESS"})
        assert response.status_code == 200, response.text
    response = client.patch("/tasks/work-5", json={"status": "IN_PROGRESS"})
    assert response.status_code == 409 and "five" in response.text
    with Session(engine) as db:
        assert db.get(m.Task, "work-5").status == m.TaskStatusEnum.TODO
    snapshot = client.get("/tasks/activity").json()
    row = next(x for x in snapshot["contexts"] if x["task_id"] == "work-0")
    body = {
        "action": "PAUSE",
        "expected_version": row["version"],
        "request_id": str(uuid.uuid4()),
    }
    assert client.post("/tasks/work-0/activity", json=body).status_code == 200
    assert client.post("/tasks/work-0/activity", json=body).status_code == 200
    assert (
        client.patch("/tasks/work-5", json={"status": "IN_PROGRESS"}).status_code == 200
    )
    identity["id"] = "foreign"
    assert client.get("/tasks/activity?user_id=owner").status_code == 404


def test_migration_rehearsal_preserves_records_and_repeats(harness, monkeypatch, clock):
    from backend.app.tickets.models import XpLedger
    from backend.tests.test_subtask_rewards import activate, complete, create

    engine, _, _ = harness
    # The database deliberately rejects future reward activation. Keep this
    # synthetic clock behind the real disposable database clock.
    clock[0] = datetime.now(UTC) - timedelta(days=1)
    with Session(engine) as db:
        activate(db)
        children = create(db, 2)
        complete(db, sorted(children, key=lambda c: (c.created_at, c.id))[1])
        confirmed(
            db, NOW - timedelta(hours=1), NOW - timedelta(minutes=30), task="task"
        )
        db.commit()
        assert db.get(m.User, "worker").points == 145
    module = importlib.import_module(
        "backend.alembic.versions.i9e1a3c5d7f9_task_activity"
    )
    with engine.begin() as connection:
        m.TaskWorkCorrection.__table__.drop(connection)
        m.TaskActivityContext.__table__.drop(connection)
        before = {
            t.name: connection.execute(sa.select(t)).all()
            for t in (
                m.User.__table__,
                m.Task.__table__,
                m.Subtask.__table__,
                m.AuditEvent.__table__,
                m.TaskWorkInterval.__table__,
                XpLedger.__table__,
            )
        }
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        module.upgrade()
        module.upgrade()
        for name, rows in before.items():
            assert (
                connection.execute(sa.select(m.Base.metadata.tables[name])).all()
                == rows
            )
        with pytest.raises(RuntimeError, match="Retain"):
            module.downgrade()


def test_direct_subtask_start_and_pause_share_the_five_parent_gate(harness, clock):
    engine, _, _ = harness
    with Session(engine, autoflush=False) as db:
        seed(db)
        for i in range(5):
            change(db, f"work-{i}")
        child = subtasks.create(
            db,
            actor_id="owner",
            task_id="work-5",
            data={
                "title": "Managed",
                "planned_start_date": "2026-11-02",
                "planned_end_date": "2026-11-03",
            },
        )
        db.commit()
        with pytest.raises(HTTPException) as error:
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="work-5",
                subtask_id=child.id,
                data={"expected_version": 1, "action": "START"},
            )
        assert error.value.status_code == 409
        db.commit()
        db.refresh(child)
        assert child.status == "TODO" and child.actual_start_at is None
        change(db, action="PAUSE")
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="work-5",
            subtask_id=child.id,
            data={"expected_version": 1, "action": "START"},
        )
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="work-5",
            subtask_id=child.id,
            data={"expected_version": 2, "action": "PAUSE"},
        )
        db.commit()
        assert activity.snapshot(db, actor_id="owner")["active_count"] == 4
        assert child.actual_start_at is None and child.actual_end_at is None


def test_completion_closes_each_users_selected_context_and_preserves_actuals(
    harness, clock
):
    engine, _, _ = harness
    with Session(engine, autoflush=False) as db:
        seed(db)
        child = subtasks.create(
            db,
            actor_id="owner",
            task_id="work-0",
            data={
                "title": "Managed",
                "planned_start_date": "2026-11-02",
                "planned_end_date": "2026-11-03",
            },
        )
        child = subtasks.edit(
            db,
            actor_id="owner",
            task_id="work-0",
            subtask_id=child.id,
            data={"expected_version": 1, "action": "START"},
        )
        change(db, user="worker", subtask_id=child.id)
        child = subtasks.edit(
            db,
            actor_id="owner",
            task_id="work-0",
            subtask_id=child.id,
            data={
                "expected_version": 2,
                "actual_start_at": NOW - timedelta(hours=1),
                "actual_end_at": NOW,
                "confirm_actual_times": True,
            },
        )
        clock[0] += timedelta(minutes=2)
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="work-0",
            subtask_id=child.id,
            data={"expected_version": 3, "action": "COMPLETE"},
        )
        db.commit()
        assert child.actual_end_at == NOW and child.actual_start_at == NOW - timedelta(
            hours=1
        )
        for who in ("owner", "worker"):
            frame = activity.snapshot(db, actor_id=who)
            assert (
                frame["active_count"] == 0
                and frame["contexts"][0]["status"] == "COMPLETED"
            )
            assert frame["contexts"][0]["elapsed_seconds"] == 120


def test_storage_guards_cannot_allocate_a_sixth_slot(harness, clock):
    engine, tenant, _ = harness
    with Session(engine) as db:
        seed(db)
        for i in range(5):
            change(db, f"work-{i}")
        db.commit()
        after = {
            "context_id": "bypass",
            "user_id": "owner",
            "status": "RUNNING",
            "slot": 6,
            "elapsed_ms": 0,
            "version": 1,
            "subtask_id": None,
            "resumed_at": NOW.isoformat(),
        }
        with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
            event = activity._event(
                db, db.get(m.User, "owner"), "work-5", None, "work.started", None, after
            )
            db.add(
                m.TaskActivityContext(
                    id="bypass",
                    tenant_id=tenant,
                    user_id="owner",
                    task_id="work-5",
                    status="RUNNING",
                    slot=6,
                    elapsed_ms=0,
                    resumed_at=NOW,
                    version=1,
                    activity_event_id=event.id,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            db.flush()
        assert activity.snapshot(db, actor_id="owner")["active_count"] == 5


def test_workload_uses_manual_work_estimates_deadlines_and_configured_capacity(
    harness, clock
):
    engine, _, _ = harness
    with Session(engine) as db:
        seed(db, 3)
        user = db.get(m.User, "owner")
        user.timezone, user.shift_start, user.shift_end = "UTC", "09:00", "10:00"
        task = db.get(m.Task, "work-0")
        # Personal work must be monitored even when its task is assigned to a
        # different person; starting work never rewrites that assignment.
        task.estimated_hours = 3
        task.due_at = (NOW + timedelta(hours=1)).replace(tzinfo=None)
        db.get(m.Task, "work-1").assigned_to_id = "owner"
        db.get(m.Task, "work-1").due_at = (NOW - timedelta(hours=1)).replace(
            tzinfo=None
        )
        db.commit()
        confirmed(db, NOW - timedelta(hours=2), NOW)
        change(db)
        db.commit()
        clock[0] += timedelta(hours=3)
        data = activity.snapshot(db, actor_id="owner")["workload"]
        assert (
            data["manual_seconds"] == 7200
            and data["estimated_remaining_seconds"] == 3600
        )
        assert data["capacity_seconds"] == 3600 and data["overtime_seconds"] == 3600
        assert data["unestimated_tasks"] == 1 and len(data["overdue_tasks"]) == 2
        assert not data["near_deadline"]
        assert task.assigned_to_id == "worker"


@pytest.mark.parametrize(
    "day,start,end,expected",
    [
        ("2026-03-08", "00:00", "04:00", 3),
        ("2026-11-01", "00:00", "04:00", 5),
        ("2026-03-08", "02:30", "04:00", None),
        ("2026-11-01", "01:30", "04:00", None),
    ],
)
def test_capacity_dst_and_ambiguous_missing_boundaries(day, start, end, expected):
    user = Row(
        shift_start=start,
        shift_end=end,
        **{
            prefix + suffix: None
            for prefix in ("morning_break", "lunch_break", "evening_break")
            for suffix in ("_start", "_end")
        },
    )
    actual = activity.capacity(
        user, datetime.fromisoformat(day).date(), ZoneInfo("America/New_York")
    )
    assert actual == (expected * 3600 if expected is not None else None)


def test_transaction_interruption_rolls_back_context_and_immutable_event(
    harness, clock, monkeypatch
):
    engine, _, _ = harness
    with Session(engine, autoflush=False) as db:
        seed(db)
        baseline = db.scalar(sa.select(sa.func.count()).select_from(m.AuditEvent))
        original = activity._event

        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("Synthetic interruption")

        monkeypatch.setattr(activity, "_event", interrupted)
        with pytest.raises(RuntimeError, match="Synthetic interruption"):
            change(db)
        db.commit()
        assert (
            db.scalar(sa.select(sa.func.count()).select_from(m.TaskActivityContext))
            == 0
        )
        assert (
            db.scalar(sa.select(sa.func.count()).select_from(m.AuditEvent)) == baseline
        )


@pytest.mark.parametrize("operation", ["same_parent", "same_interval", "resume"])
def test_postgres_parallel_idempotency_and_productive_overlap(harness, operation):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Real PostgreSQL concurrency required")
    with Session(engine) as db:
        seed(db)
        if operation == "resume":
            for i in range(4):
                change(db, f"work-{i}")
            for i in (4, 5):
                change(db, f"work-{i}")
                change(db, f"work-{i}", "PAUSE")
            db.commit()
    gate = Barrier(2)
    request = str(uuid.uuid4())

    def worker(i):
        with Session(engine, autoflush=False) as db:
            gate.wait(timeout=15)
            try:
                if operation == "same_interval":
                    confirmed(db, NOW - timedelta(hours=1), NOW, f"work-{i}")
                elif operation == "same_parent":
                    change(db, expected_version=0, request_id=request)
                else:
                    change(db, f"work-{i + 4}", "RESUME", expected_version=2)
                db.commit()
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, i) for i in range(2)]
        assert sorted(f.result(timeout=45) for f in futures) == (
            [200, 200] if operation == "same_parent" else [200, 409]
        )
    with Session(engine) as db:
        if operation == "same_parent":
            assert (
                db.scalar(sa.select(sa.func.count()).select_from(m.TaskActivityContext))
                == 1
            )
            assert (
                db.scalar(
                    sa.select(sa.func.count())
                    .select_from(m.AuditEvent)
                    .where(m.AuditEvent.event_type == "work.started")
                )
                == 1
            )
        if operation == "same_interval":
            assert (
                db.scalar(sa.select(sa.func.count()).select_from(m.TaskWorkInterval))
                == 1
            )


def test_manager_hidden_tasks_have_occupied_redacted_slots(harness, clock):
    engine, _, _ = harness
    with Session(engine) as db:
        seed(db)
        db.get(m.User, "watcher").role = m.RoleEnum.MANAGER
        db.get(m.User, "worker").manager_id = "watcher"
        db.commit()
        change(db, user="worker")
        db.commit()
        result = activity.snapshot(db, actor_id="watcher", user_id="worker")
        assert result["active_count"] == 1 and result["contexts"][0]["restricted"]
        assert result["contexts"][0]["task_id"] == "" and "Work 0" not in str(result)


def test_migration_refuses_wrong_request_index(harness, monkeypatch):
    engine, _, _ = harness
    module = importlib.import_module(
        "backend.alembic.versions.i9e1a3c5d7f9_task_activity"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX uq_work_activity_request")
        connection.exec_driver_sql(
            "CREATE INDEX uq_work_activity_request ON audit_events(actor_id)"
        )
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        with pytest.raises(RuntimeError, match="request index"):
            module.upgrade()


def test_backup_roundtrip_preserves_context_and_immutable_correction(backup_harness):
    from backend.tests.test_backup_manager import confirm, export, upload

    h = backup_harness
    with Session(h.engine, autoflush=False) as db:
        activity.command(db, actor_id="owner", task_id="task", action="START")
        activity.command(db, actor_id="owner", task_id="task", action="PAUSE")
        first = confirmed(db, NOW, NOW + timedelta(minutes=30), task="task")
        confirmed(
            db, NOW, NOW + timedelta(minutes=20), task="task", supersedes_id=first.id
        )
        db.commit()
    _, archive, _ = export(h, format="json")
    validated = upload(h, archive.content)
    assert validated.status_code == 200 and validated.json()["report"]["valid"]
    restored = confirm(h, validated.json())
    assert restored.status_code == 200, restored.text
    with Session(h.engine) as db:
        frame = activity.snapshot(db, actor_id="owner")
        assert frame["active_count"] == 0
        assert frame["contexts"][0]["status"] == "PAUSED"
        assert len(activity.active_intervals(db, db.get(m.User, "owner"))) == 1
        assert (
            db.scalar(sa.select(sa.func.count()).select_from(m.TaskWorkInterval)) == 2
        )
        link = db.scalar(sa.select(m.TaskWorkCorrection))
        with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
            db.execute(
                sa.delete(m.TaskWorkCorrection).where(
                    m.TaskWorkCorrection.id == link.id
                )
            )
        with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
            db.execute(sa.update(m.TaskActivityContext).values(elapsed_ms=1))


def test_existing_websocket_delivers_private_activity_invalidation(
    api_harness, monkeypatch
):
    from sqlalchemy.orm import sessionmaker
    from starlette.websockets import WebSocketDisconnect

    from backend.app.auth import create_access_token
    from backend.app.routers import tasks
    from backend.app.services import navigation_sockets
    from backend.app.ws import tasks as sockets

    client, engine, _ = api_harness
    sessions = sessionmaker(engine)
    monkeypatch.setattr(sockets, "SessionLocal", sessions)
    monkeypatch.setattr(navigation_sockets, "SessionLocal", sessions)
    monkeypatch.setattr(sockets, "manager", sockets.TaskConnectionManager())
    client.app.include_router(sockets.router)
    with Session(engine) as db:
        tenant = str(db.get(m.User, "owner").tenant_id)
        other = str(db.get(m.User, "foreign").tenant_id)

    def token(user, group):
        return create_access_token(user, extra_claims={"tenant_id": group})

    bad = token("owner", other)
    with (
        pytest.raises(WebSocketDisconnect) as rejected,
        client.websocket_connect(f"/ws/tasks?token={bad}"),
    ):
        pass
    assert rejected.value.code == 1008

    sent = []

    def publish(payload):
        sent.append(payload)
        client.portal.call(sockets.broadcast_task_event, payload)

    monkeypatch.setattr(tasks.task_events, "publish_task_event", publish)
    with (
        client.websocket_connect(f"/ws/tasks?token={token('owner', tenant)}") as own,
        client.websocket_connect(
            f"/ws/tasks?token={token('foreign', other)}"
        ) as foreign,
    ):
        response = client.post(
            "/tasks/main/activity",
            json={
                "action": "START",
                "expected_version": 0,
                "request_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 200, response.text
        assert own.receive_json() == {
            "type": "work.changed",
            "tenant_id": tenant,
            "user_id": "owner",
        }
        assert sent == [
            {"type": "work.changed", "tenant_id": tenant, "user_id": "owner"}
        ]
        # A foreign sentinel must be its first message: no owner metadata,
        # task IDs, names, interval notes or counts leaked across tenants.
        client.portal.call(
            sockets.broadcast_task_event, {"type": "sentinel", "tenant_id": other}
        )
        assert foreign.receive_json()["type"] == "sentinel"
        assert client.get("/tasks/activity").json()["active_count"] == 1
