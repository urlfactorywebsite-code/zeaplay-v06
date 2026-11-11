"""Phase 6: sanitized SQLite/PostgreSQL transactions, no delivery providers."""

# ruff: noqa: F811
import importlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.database import get_db
from backend.app.dependencies import get_current_active_user
from backend.app.routers import notification_preferences, notifications
from backend.app.services import task_activity as activity
from backend.app.services import workload_notifications as alerts
from backend.app.tickets.models import XpLedger
from backend.tests.test_subtask_rewards import activate, complete, create
from backend.tests.test_task_activity import change, confirmed, seed
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401

UTC = timezone.utc
NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_external_notification_sinks(monkeypatch):
    from backend.app.services import notification_dispatcher

    monkeypatch.setattr(
        notification_dispatcher, "trigger_n8n_event", lambda *a, **k: None
    )
    monkeypatch.setattr(
        notification_dispatcher.audit_logger, "log_event", lambda *a, **k: None
    )


def rows(db, kind=None):
    query = sa.select(m.Notification).where(m.Notification.alert_kind.is_not(None))
    if kind:
        query = query.where(m.Notification.alert_kind == kind)
    return list(db.scalars(query))


def emit(db, source="one", **kwargs):
    alerts.emit(
        db,
        task=db.get(m.Task, "task"),
        kind="test",
        source=source,
        message="Safe alert",
        **kwargs,
    )


@pytest.fixture
def api(harness, monkeypatch):
    from backend.app.routers import push, tasks

    engine, _, _ = harness
    identity = {"id": "worker"}
    app = FastAPI()
    app.include_router(notifications.router)
    app.include_router(notification_preferences.router)
    app.include_router(tasks.router)
    app.include_router(push.router)
    app.add_exception_handler(
        activity.ActivityLimitExceeded, alerts.limit_error_handler
    )

    def session():
        with Session(engine) as db:
            yield db

    def actor():
        with Session(engine) as db:
            return db.get(m.User, identity["id"])

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_active_user] = actor
    monkeypatch.setattr(notifications.audit_logger, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(notifications, "_publish_inbox", lambda *a: None)
    with TestClient(app) as client:
        yield client, engine, identity


def test_recipient_roles_are_deduplicated_and_visibility_checked(harness):
    engine, tenant, _ = harness
    with Session(engine) as db:
        worker = db.get(m.User, "worker")
        worker.manager_id = "owner"  # creator and reporting manager overlap
        task = db.get(m.Task, "task")
        task.followers.append(db.get(m.User, "foreign"))  # malformed legacy membership
        db.commit()
        emit(db)
        db.commit()
        assert {n.user_id for n in rows(db, "test")} == {"worker", "owner", "watcher"}
        assert all(n.tenant_id == tenant for n in rows(db, "test"))
        worker.manager_id = "foreign"
        emit(db, "two")
        db.commit()
        assert not any(n.user_id == "foreign" for n in rows(db, "test"))


def test_notification_deduplication_namespace_includes_tenant(harness):
    engine, first, other = harness
    with Session(engine) as db:
        emit(db, "same-state")
        db.commit()
        # Synthetic legacy accounts without immutable financial/work history
        # may move workspaces. Old receipts retain their original ownership.
        db.get(m.User, "owner").tenant_id = other
        db.get(m.User, "worker").tenant_id = other
        db.commit()
        emit(db, "same-state")
        db.commit()
        worker_notes = [n for n in rows(db, "test") if n.user_id == "worker"]
        assert {n.tenant_id for n in worker_notes} == {first, other}
        assert len({n.dedupe_key for n in worker_notes}) == 2
        visible = list(db.scalars(alerts.visible_query(db.get(m.User, "worker"))))
        assert len(visible) == 1 and visible[0].tenant_id == other


def test_manager_without_task_visibility_gets_no_private_details(harness):
    engine, tenant, _ = harness
    with Session(engine) as db:
        db.add(
            m.User(
                id="manager",
                name="Manager",
                email="manager@example.test",
                tenant_id=tenant,
                role=m.RoleEnum.MANAGER,
                hashed_password="fixture",
            )
        )
        db.get(m.User, "worker").manager_id = "manager"
        db.commit()
        emit(db)
        db.commit()
        assert "manager" not in {n.user_id for n in rows(db, "test")}
        task = db.get(m.Task, "task")
        task.followers.append(db.get(m.User, "manager"))
        db.commit()
        emit(db, "visible")
        db.commit()
        assert "manager" in {n.user_id for n in rows(db, "test")}


def test_event_reprocessing_and_dismissed_alert_cannot_duplicate(api):
    client, engine, _ = api
    with Session(engine) as db:
        emit(db)
        db.commit()
        note = next(n for n in rows(db, "test") if n.user_id == "worker")
        note_id = note.id
    assert client.delete(f"/notifications/{note_id}").status_code == 204
    with Session(engine) as db:
        emit(db)
        db.commit()
        assert len(rows(db, "test")) == 3
        assert db.get(m.Notification, note_id).dismissed_at
    assert all(
        n["id"] != note_id for n in client.get("/notifications/inbox").json()["items"]
    )


def test_unread_count_scopes_all_pages_and_actions(api):
    client, engine, identity = api
    with Session(engine) as db:
        for i in range(7):
            emit(db, str(i))
        db.commit()
        foreign_id = next(n.id for n in rows(db) if n.user_id == "foreign")
    page = client.get("/notifications/inbox?limit=2").json()
    assert len(page["items"]) == 2 and page["unread_count"] >= 7
    assert client.post(f"/notifications/{foreign_id}/read").status_code == 404
    assert client.delete(f"/notifications/{foreign_id}").status_code == 404
    assert client.post("/notifications/read-all").status_code == 204
    assert client.get("/notifications/inbox").json()["unread_count"] == 0
    identity["id"] = "foreign"
    assert all(
        n["related_task_id"] != "task"
        for n in client.get("/notifications/inbox").json()["items"]
    )


def test_access_revocation_hides_existing_alerts_and_rejects_mutations(api):
    client, engine, identity = api
    with Session(engine) as db:
        emit(db)
        db.commit()
        note_id = next(n.id for n in rows(db, "test") if n.user_id == "watcher")
        db.get(m.Task, "task").followers = []
        db.commit()
    identity["id"] = "watcher"
    assert client.get("/notifications/inbox").json()["unread_count"] == 0
    assert client.post(f"/notifications/{note_id}/read").status_code == 404
    assert client.delete(f"/notifications/{note_id}").status_code == 404


def test_disabled_task_module_hides_and_suppresses_task_details(api, monkeypatch):
    from backend.app.navigation_registry import default_rules
    from backend.app.services import notification_dispatcher

    client, engine, _ = api
    pushed = []
    monkeypatch.setattr(
        notification_dispatcher, "push_if_enabled", lambda db, **kw: pushed.append(kw)
    )
    with Session(engine) as db:
        for n in rows(db):
            n.delivery_pending = False
        emit(db)
        db.commit()
        note_id = next(n.id for n in rows(db, "test") if n.user_id == "worker")
        rules = default_rules()
        rules["tasks"]["enabled"] = False
        rules["dashboard"]["enabled"] = False
        db.add(
            m.NavigationPolicy(
                tenant_id=str(db.get(m.User, "worker").tenant_id),
                pages=rules,
                version=1,
                updated_by="owner",
                updated_at=NOW,
            )
        )
        db.commit()
        emit(db, "suppressed")
        db.commit()
        assert len(rows(db, "test")) == 3
        alerts.run_delivery(db)
        assert not pushed
    assert client.get("/notifications/inbox").json()["items"] == []
    assert client.post(f"/notifications/{note_id}/read").status_code == 404
    assert client.delete(f"/notifications/{note_id}").status_code == 404


def test_preferences_validate_preserve_omitted_values_and_clear_overrides(api):
    client, _, _ = api

    def save(**kwargs):
        return client.post(
            "/notification/preferences",
            json={"preferences": [{"module": "tasks", "push_enabled": True, **kwargs}]},
        )

    assert save(near_deadline_hours=0).status_code == 422
    assert save(productive_capacity_hours=-1).status_code == 422
    assert save(quiet_start="25:00", quiet_end="08:00").status_code == 422
    assert save(quiet_start="22:00").status_code == 422
    assert (
        save(
            sound_enabled=True,
            near_deadline_hours=6,
            productive_capacity_hours=4,
            overtime_threshold_minutes=15,
            quiet_start="22:00",
            quiet_end="06:00",
        ).status_code
        == 200
    )
    pref = next(p for p in save().json() if p["module"] == "tasks")
    assert (
        pref["near_deadline_hours"] == 6
        and pref["sound_enabled"]
        and pref["productive_capacity_hours"] == 4
    )
    assert (
        save(
            productive_capacity_hours=None, quiet_start=None, quiet_end=None
        ).status_code
        == 200
    )
    pref = next(
        p
        for p in client.get("/notification/preferences").json()
        if p["module"] == "tasks"
    )
    assert pref["productive_capacity_hours"] is None and pref["quiet_start"] is None


def test_concurrent_preference_creation_has_one_row_and_no_lost_partial_settings(api):
    client, engine, _ = api
    barrier = Barrier(4)

    def save(i):
        barrier.wait(timeout=15)
        return client.post(
            "/notification/preferences",
            json={
                "preferences": [
                    {
                        "module": "tasks",
                        "push_enabled": True,
                        "near_deadline_hours": 12 + i,
                        "sound_enabled": True,
                    }
                ]
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(save, range(4))) == [200] * 4
    assert (
        client.post(
            "/notification/preferences",
            json={"preferences": [{"module": "tasks", "push_enabled": False}]},
        ).status_code
        == 200
    )
    with Session(engine) as db:
        prefs = list(
            db.scalars(
                sa.select(m.NotificationPreference).where(
                    m.NotificationPreference.user_id == "worker"
                )
            )
        )
        assert len(prefs) == 1 and prefs[0].sound_enabled and not prefs[0].push_enabled
        assert prefs[0].near_deadline_hours in {12, 13, 14, 15}


@pytest.mark.parametrize(
    "hour,expected", [(21, False), (22, True), (0, True), (5, True), (6, False)]
)
def test_quiet_hours_overnight_boundary(hour, expected):
    pref = m.NotificationPreference(quiet_start="22:00", quiet_end="06:00")
    assert (
        alerts.quiet(pref, m.User(timezone="UTC"), NOW.replace(hour=hour)) is expected
    )


def test_transaction_interruption_rolls_back_notifications_and_rewards(
    harness, monkeypatch
):
    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: datetime.now(UTC) - timedelta(days=1))
    with Session(engine) as db:
        activate(db)
        children = create(db, 2)
        db.commit()
        before = len(rows(db))
        child = sorted(children, key=lambda c: (c.created_at, c.id))[1]
        complete(db, child)
        assert rows(db, "points_credited")
        db.rollback()
        assert len(rows(db)) == before
        assert db.scalar(sa.select(sa.func.count()).select_from(XpLedger)) == 0
        assert db.get(m.User, "worker").points == 100


def test_ledger_components_replay_and_reversal_alerts(harness, monkeypatch):
    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: datetime.now(UTC) - timedelta(days=1))
    with Session(engine) as db:
        activate(db)
        children = create(db, 2)
        child = sorted(children, key=lambda c: (c.created_at, c.id))[1]
        complete(db, child)
        db.commit()
        assert rows(db, "points_credited") and rows(db, "bonus_applied")
        before = len(rows(db))
        entries = list(db.scalars(sa.select(XpLedger)))
        for row in entries:
            alerts.from_ledger(db, row)
        db.commit()
        assert len(rows(db)) == before
        from backend.app.services import subtasks

        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=child.id,
            data={"expected_version": child.version, "action": "REOPEN"},
        )
        db.commit()
        assert len(rows(db, "points_reversed")) == 6
        assert db.get(m.User, "worker").points == 100


def test_five_context_alert_and_denied_request_is_idempotent(harness, monkeypatch):
    engine, _, _ = harness
    with Session(engine) as db:
        seed(db)
        for i in range(5):
            change(db, f"work-{i}")
        db.commit()
        assert len(rows(db, "active_limit")) == 2
        request_id = str(uuid.uuid4())
        with pytest.raises(activity.ActivityLimitExceeded) as error:
            change(db, "work-5", request_id=request_id)
        db.rollback()
    from backend.app import database

    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine))
    for _ in range(2):
        result = alerts.limit_error_handler(None, error.value)
        assert result.status_code == 409
    with Session(engine) as db:
        assert len(rows(db, "active_limit_denied")) == 2
        assert (
            db.scalar(
                sa.select(sa.func.count())
                .select_from(m.TaskActivityContext)
                .where(m.TaskActivityContext.status == "RUNNING")
            )
            == 5
        )


def test_http_sixth_attempt_alert_survives_rejected_transaction(api, monkeypatch):
    from backend.app import database

    client, engine, _ = api
    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine))
    with Session(engine) as db:
        seed(db)
        for i in range(5):
            change(db, f"work-{i}", user="worker")
        db.commit()
    payload = {
        "action": "START",
        "expected_version": 0,
        "request_id": str(uuid.uuid4()),
    }
    for _ in range(2):
        response = client.post("/tasks/work-5/activity", json=payload)
        assert (
            response.status_code == 409
            and "five active parent" in response.json()["detail"]
        )
    with Session(engine) as db:
        assert len(rows(db, "active_limit_denied")) == 2
    assert client.post("/tasks/other/activity", json=payload).status_code == 404
    with Session(engine) as db:
        assert len(rows(db, "active_limit_denied")) == 2


def test_deadlines_repeated_scan_and_edited_deadline(harness, monkeypatch):
    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        task = db.get(m.Task, "task")
        task.due_at = (NOW + timedelta(hours=2)).replace(tzinfo=None)
        db.add(
            m.NotificationPreference(
                user_id="worker", module="tasks", near_deadline_hours=3
            )
        )
        db.add(
            m.Subtask(
                id="due-child",
                task_id="task",
                title="Late child",
                planned_end_date=NOW.date() - timedelta(days=1),
            )
        )
        db.commit()
        alerts.scan(db)
        assert len(rows(db, "approaching_deadline")) == 3
        assert len(rows(db, "subtask_overdue")) == 3
        count = len(rows(db))
        alerts.scan(db)
        assert len(rows(db)) == count
        task.due_at = (NOW - timedelta(hours=1)).replace(tzinfo=None)
        db.commit()
        alerts.scan(db)
        assert len(rows(db, "task_overdue")) == 3


def test_unassigned_legacy_task_deadline_uses_creator_responsibility(
    harness, monkeypatch
):
    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        db.add(
            m.Task(
                id="unassigned",
                created_by_id="owner",
                title="Unassigned legacy task",
                due_at=(NOW - timedelta(hours=1)).replace(tzinfo=None),
            )
        )
        db.commit()
        alerts.scan(db)
        notes = [
            n for n in rows(db, "task_overdue") if n.related_task_id == "unassigned"
        ]
        assert len(notes) == 1 and notes[0].user_id == "owner"


def test_deadline_alert_window_belongs_to_responsible_assignee(harness, monkeypatch):
    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        db.get(m.Task, "task").due_at = (NOW + timedelta(hours=2)).replace(tzinfo=None)
        db.add_all(
            [
                m.NotificationPreference(
                    user_id="owner", module="tasks", near_deadline_hours=48
                ),
                m.NotificationPreference(
                    user_id="worker", module="tasks", near_deadline_hours=1
                ),
            ]
        )
        activity.command(db, actor_id="owner", task_id="task", action="START")
        db.commit()
        alerts.scan(db)
        assert not rows(db, "approaching_deadline")


def test_manual_union_capacity_estimates_and_no_default_hours(harness, monkeypatch):
    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        seed(db, 1)
        db.get(m.Task, "work-0").estimated_hours = 10
        confirmed(db, NOW - timedelta(hours=2), NOW - timedelta(hours=1))
        db.commit()
        frame = activity.snapshot(db, actor_id="owner")
        assert frame["workload"]["manual_seconds"] == 3600
        assert frame["workload"]["capacity_seconds"] is None
        db.add(
            m.NotificationPreference(
                user_id="owner", module="tasks", productive_capacity_hours=0.5
            )
        )
        change(db)
        db.commit()
        alerts.scan(db)
        assert rows(db, "productive_overtime") and rows(db, "estimated_overload")


def test_delivery_retries_quiet_preferences_and_revoked_access(harness, monkeypatch):
    from backend.app.services import notification_dispatcher, task_events

    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    pushed, broadcast = [], []
    fail = [True]

    def push(db, **kwargs):
        pushed.append(kwargs)
        if fail[0]:
            raise RuntimeError("synthetic transient failure")

    monkeypatch.setattr(notification_dispatcher, "push_if_enabled", push)
    monkeypatch.setattr(task_events, "publish_task_event", broadcast.append)
    with Session(engine) as db:
        for n in rows(db):
            n.delivery_pending = False
        emit(db)
        db.commit()
        alerts.run_delivery(db)
        assert all(
            n.delivery_attempts == 1 and n.delivery_pending for n in rows(db, "test")
        )
        assert broadcast and all(
            b["type"] == "notifications.changed" and "title" not in b for b in broadcast
        )
        fail[0] = False
        for n in rows(db, "test"):
            n.next_delivery_at = NOW
        db.get(m.Task, "task").followers = []
        db.commit()
        alerts.run_delivery(db)
        assert all(not n.delivery_pending for n in rows(db, "test"))
        test_ids = {n.id for n in rows(db, "test")}
        assert (
            len([p for p in pushed if p["payload"]["notification_id"] in test_ids]) == 5
        )  # watcher was revoked before retry
        assert all(p["payload"]["silent"] for p in pushed)


def test_db_rejects_cross_tenant_alert(harness):
    engine, tenant, _ = harness
    with (
        engine.begin() as conn,
        pytest.raises(sa.exc.IntegrityError),
        conn.begin_nested(),
    ):
        conn.execute(
            sa.insert(m.Notification).values(
                id="bad",
                user_id="foreign",
                tenant_id=tenant,
                dedupe_key="bad",
                alert_kind="test",
                related_task_id="task",
                type=m.NotificationTypeEnum.TASK_UPDATED,
                message="Must fail",
                is_read=False,
                delivery_pending=False,
                delivery_attempts=0,
            )
        )


def test_concurrent_workers_generate_one_alert_per_recipient(harness):
    engine, _, _ = harness
    barrier = Barrier(4)

    def worker(_):
        with Session(engine) as db:
            task = db.get(m.Task, "task")
            barrier.wait(timeout=20)
            alerts.emit(
                db, task=task, kind="concurrent", source="same-event", message="Once"
            )
            db.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(4)))
    with Session(engine) as db:
        assert len(rows(db, "concurrent")) == 3


def test_reassignment_notifies_former_recipient_without_task_data(harness, monkeypatch):
    from backend.app.services import subtask_rewards

    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: datetime.now(UTC) - timedelta(days=1))
    with Session(engine) as db:
        activate(db)
        child = sorted(create(db, 2), key=lambda c: (c.created_at, c.id))[1]
        complete(db, child)
        db.commit()
        task = db.get(m.Task, "task")
        subtask_rewards.lock_scope(db, task.id)
        task.assigned_to_id = "watcher"
        subtask_rewards.reconcile(
            db, actor_id="owner", task_id=task.id, authorized_parent_write=True
        )
        db.commit()
        reversed_notes = [
            n for n in rows(db, "points_reversed") if n.user_id == "worker"
        ]
        assert len(reversed_notes) == 2
        assert all(
            n.related_task_id is None
            and n.deep_link is None
            and "Preserve" not in n.message
            for n in reversed_notes
        )
        assert db.get(m.User, "worker").points == 100
        assert db.get(m.User, "watcher").points == 145
        assert (
            len(db.scalars(alerts.visible_query(db.get(m.User, "worker"))).all()) == 2
        )


@pytest.mark.parametrize(
    "late,expected", [(False, "bonus_applied"), (True, "penalty_applied")]
)
def test_main_payout_alerts_reuse_actual_components(
    harness, monkeypatch, late, expected
):
    from backend.app.services.gamification import award_task_completion_points

    engine, _, _ = harness
    with Session(engine) as db:
        task = db.get(m.Task, "task")
        task.priority = m.TaskPriorityEnum.HIGH
        task.due_at = NOW.replace(tzinfo=None)
        task.completed_at = (NOW + timedelta(seconds=1 if late else -1)).replace(
            tzinfo=None
        )
        task.status = m.TaskStatusEnum.DONE
        award_task_completion_points(db, task)
        db.commit()
        assert len(rows(db, "points_credited")) == 3 and len(rows(db, expected)) == 3
        assert db.get(m.User, "worker").points == (115 if late else 145)
        assert len(rows(db, "task_completed")) == 3
        assert all(
            n.type == m.NotificationTypeEnum.TASK_COMPLETED
            for n in rows(db, "task_completed")
        )
        assert (
            db.scalar(sa.select(sa.func.count()).select_from(XpLedger)) == 0
        )  # no fake historic ledger


def test_identical_assignment_and_legacy_dispatch_share_single_event(harness):
    from backend.app.services.notifications import create_notification

    engine, _, _ = harness
    with Session(engine) as db:
        task = db.get(m.Task, "task")
        task.assigned_to_id = "watcher"
        db.flush()
        for user_id in ("owner", "watcher", "owner"):
            create_notification(
                db,
                user_id=user_id,
                related_task_id=task.id,
                notification_type=m.NotificationTypeEnum.TASK_ASSIGNED,
                message="Assignment",
            )
        db.commit()
        before = len(rows(db))
        task.assigned_to_id = "watcher"
        create_notification(
            db,
            user_id="watcher",
            related_task_id=task.id,
            notification_type=m.NotificationTypeEnum.TASK_ASSIGNED,
            message="Retry",
        )
        db.commit()
        assert len(rows(db)) == before


def test_notification_websocket_fanout_is_private_even_for_report_watchers(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from backend.app.ws import tasks as sockets

    class Socket:
        def __init__(self, user, watched=None):
            self.state = SimpleNamespace(
                navigation_identity=(user, "tenant"), activity_subject=watched
            )
            self.messages = []

        async def accept(self):
            pass

        async def send_json(self, payload):
            self.messages.append(payload)

        async def close(self, code):
            pass

    checks = []
    monkeypatch.setattr(
        sockets,
        "_delivery_allowed",
        lambda sock, subject: checks.append(subject) or True,
    )

    async def run():
        manager = sockets.TaskConnectionManager()
        owner, other_tab, manager_socket, foreign = (
            Socket("employee"),
            Socket("employee"),
            Socket("manager", "employee"),
            Socket("employee"),
        )
        for socket in (owner, other_tab, manager_socket):
            await manager.connect("tenant", socket)
        await manager.connect("foreign", foreign)
        await manager.broadcast(
            "tenant", {"type": "notifications.changed", "user_id": "employee"}
        )
        assert len(owner.messages) == len(other_tab.messages) == 1
        assert not manager_socket.messages and not foreign.messages and len(checks) == 1
        await manager.broadcast(
            None, {"type": "notifications.changed", "user_id": "employee"}
        )
        await manager.broadcast("tenant", {"type": "notifications.changed"})
        assert len(owner.messages) == 1

    asyncio.run(run())


def test_two_delivery_workers_cannot_process_same_row(harness, monkeypatch):
    if harness[0].dialect.name != "postgresql":
        pytest.skip(
            "SKIP LOCKED delivery claims require PostgreSQL; separately exercised there"
        )
    import time

    from backend.app.services import notification_dispatcher, task_events

    engine, _, _ = harness
    with Session(engine) as db:
        for n in rows(db):
            n.delivery_pending = False
        emit(db, only={"worker"})
        db.commit()
    sent = []

    def push(db, **kwargs):
        sent.append(kwargs["payload"]["notification_id"])
        time.sleep(0.1)

    monkeypatch.setattr(notification_dispatcher, "push_if_enabled", push)
    monkeypatch.setattr(task_events, "publish_task_event", lambda *a: None)
    barrier = Barrier(2)

    def worker(_):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return alerts.run_delivery(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(worker, range(2)))
    assert sorted(counts) == [0, 1] and len(sent) == 1


def test_quiet_delivery_defers_worker_push_but_keeps_inbox(harness, monkeypatch):
    from backend.app.services import notification_dispatcher, task_events

    engine, _, _ = harness
    now = [NOW.replace(hour=23)]
    monkeypatch.setattr(m, "utc_now", lambda: now[0])
    sent = []
    monkeypatch.setattr(
        notification_dispatcher, "push_if_enabled", lambda db, **kw: sent.append(kw)
    )
    monkeypatch.setattr(task_events, "publish_task_event", lambda *a: None)
    with Session(engine) as db:
        for n in rows(db):
            n.delivery_pending = False
        db.get(m.User, "worker").timezone = "UTC"
        db.add(
            m.NotificationPreference(
                user_id="worker",
                module="tasks",
                sound_enabled=True,
                quiet_start="22:00",
                quiet_end="06:00",
            )
        )
        emit(db, only={"worker"})
        db.commit()
        alerts.run_delivery(db)
        note = rows(db, "test")[0]
        assert not sent and note.delivery_pending and note.next_delivery_at > now[0]
        assert note.id in {
            n.id for n in db.scalars(alerts.visible_query(db.get(m.User, "worker")))
        }
        now[0] += timedelta(hours=7)
        alerts.run_delivery(db)
        assert len(sent) == 1 and sent[0]["payload"]["silent"] is False
        assert not note.delivery_pending


def test_disabled_push_preference_does_not_remove_durable_alert(harness, monkeypatch):
    from backend.app.services import push_service, task_events

    engine, _, _ = harness
    sent = []
    monkeypatch.setattr(
        push_service, "send_push", lambda db, **kw: sent.extend(kw["user_ids"])
    )
    monkeypatch.setattr(task_events, "publish_task_event", lambda *a: None)
    with Session(engine) as db:
        for n in rows(db):
            n.delivery_pending = False
        db.add(
            m.NotificationPreference(
                user_id="worker", module="tasks", push_enabled=False
            )
        )
        emit(db, only={"worker"})
        db.commit()
        alerts.run_delivery(db)
        assert (
            not sent and len(rows(db, "test")) == 1 and not rows(db, "test")[0].is_read
        )


def test_realtime_waits_for_outer_commit_and_coalesces_recipients(harness, monkeypatch):
    from backend.app.services import audit_logger, task_events

    engine, _, _ = harness
    sent = []
    monkeypatch.setattr(task_events, "publish_task_event", sent.append)
    with Session(engine) as db:
        with audit_logger._write_savepoint(db):
            emit(db, "rolled-back")
        assert not sent
        db.rollback()
        assert not sent
        for source in ("committed", "another"):
            with audit_logger._write_savepoint(db):
                emit(db, source)
        assert not sent
        db.commit()
        assert len(sent) == 3 and {p["user_id"] for p in sent} == {
            "worker",
            "owner",
            "watcher",
        }
        assert all(set(p) == {"type", "tenant_id", "user_id"} for p in sent)
        emit(db, "committed")
        db.commit()
        assert len(sent) == 3


def test_notification_lookup_indexes(harness, record_property):
    import json

    engine, tenant, _ = harness
    with engine.begin() as conn:
        conn.execute(
            sa.insert(m.Notification),
            [
                {
                    "id": f"plan-{i}",
                    "user_id": "owner",
                    "tenant_id": tenant,
                    "dedupe_key": f"plan-{i}",
                    "alert_kind": "profile",
                    "related_task_id": "task",
                    "type": m.NotificationTypeEnum.TASK_UPDATED,
                    "message": "Synthetic",
                    "is_read": False,
                    "delivery_pending": False,
                    "delivery_attempts": 0,
                }
                for i in range(5000)
            ],
        )
        plans = {}
        if engine.dialect.name == "postgresql":
            conn.exec_driver_sql("ANALYZE notifications")
            prefix = "EXPLAIN "
        else:
            prefix = "EXPLAIN QUERY PLAN "
        viewer = m.User(id="owner", tenant_id=tenant, role=m.RoleEnum.OWNER)
        query_session = Session(bind=conn)
        inbox_query = (
            alerts.visible_query(viewer, query_session)
            .with_only_columns(m.Notification.id)
            .order_by(m.Notification.created_at.desc(), m.Notification.id.desc())
            .limit(100)
        )
        inbox_sql = str(
            inbox_query.compile(
                dialect=engine.dialect, compile_kwargs={"literal_binds": True}
            )
        )
        query_session.close()
        for name, query in {
            "inbox": inbox_sql,
            "delivery": "SELECT id FROM notifications WHERE delivery_pending IS TRUE AND (next_delivery_at IS NULL OR next_delivery_at <= CURRENT_TIMESTAMP) ORDER BY created_at, id LIMIT 100",
        }.items():
            plans[name] = [str(row) for row in conn.exec_driver_sql(prefix + query)]
        assert "ix_notification_inbox" in str(plans["inbox"])
        assert any(name in str(plans["delivery"]) for name in ("ix_notification_delivery", "ix_notification_pending_chronology"))
        record_property("notification_query_plans", json.dumps(plans))


def test_productive_overtime_after_all_tasks_complete_and_manager_revocation(
    api, monkeypatch
):
    from backend.app import schemas

    client, engine, identity = api
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        worker = db.get(m.User, "worker")
        db.add(
            m.User(
                id="manager",
                name="Manager",
                email="manager@example.test",
                tenant_id=worker.tenant_id,
                role=m.RoleEnum.MANAGER,
                hashed_password="fixture",
            )
        )
        worker.manager_id = "manager"
        activity.record_work(
            db,
            actor_id="worker",
            task_id="task",
            data=schemas.ConfirmedWorkInput(
                started_at=NOW - timedelta(hours=2),
                ended_at=NOW - timedelta(hours=1),
                confirmed=True,
                request_id=str(uuid.uuid4()),
            ),
        )
        db.get(m.Task, "task").status = m.TaskStatusEnum.DONE
        db.add(
            m.NotificationPreference(
                user_id="worker", module="tasks", productive_capacity_hours=0.5
            )
        )
        db.commit()
        alerts.scan(db)
        notes = rows(db, "productive_overtime")
        assert {n.user_id for n in notes} == {"worker", "manager"}
        assert all(n.related_task_id is None and n.entity_id == "worker" for n in notes)
    identity["id"] = "manager"
    assert any(
        n["alert_kind"] == "productive_overtime"
        for n in client.get("/notifications/inbox").json()["items"]
    )
    with Session(engine) as db:
        db.get(m.User, "worker").manager_id = None
        db.commit()
    assert not client.get("/notifications/inbox").json()["items"]


def test_aggregate_overload_is_one_notification_per_person_across_tasks(
    harness, monkeypatch
):
    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        db.get(m.Task, "task").estimated_hours = 4
        db.add(
            m.Task(
                id="second",
                created_by_id="owner",
                assigned_to_id="worker",
                title="Second",
                estimated_hours=4,
            )
        )
        db.add(
            m.NotificationPreference(
                user_id="worker", module="tasks", productive_capacity_hours=1
            )
        )
        db.commit()
        alerts.scan(db)
        assert {n.user_id for n in rows(db, "estimated_overload")} == {
            "worker",
            "owner",
            "watcher",
        }
        assert len(rows(db, "estimated_overload")) == 3
        alerts.scan(db)
        assert len(rows(db, "estimated_overload")) == 3


def test_unfinished_managed_child_deadline_survives_completed_parent(
    harness, monkeypatch
):
    from backend.app.services import subtasks

    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        db.get(m.Task, "task").status = m.TaskStatusEnum.DONE
        child = subtasks.create(
            db,
            actor_id="owner",
            task_id="task",
            data={
                "title": "Pending child",
                "planned_start_date": (NOW - timedelta(days=2)).date(),
                "planned_end_date": (NOW - timedelta(days=1)).date(),
            },
        )
        db.commit()
        frame = activity.snapshot(db, actor_id="worker")
        assert [
            item["subtask_id"] for item in frame["workload"]["overdue_subtasks"]
        ] == [child.id]
        assert not frame["workload"]["overdue_tasks"]
        alerts.scan(db)
        assert len(rows(db, "subtask_overdue")) == 3


def test_uncaptured_legacy_deadline_is_consistent_across_employee_timezones(
    harness, monkeypatch
):
    from backend.app.services import subtasks

    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        db.get(m.User, "owner").timezone = "Asia/Kolkata"
        db.get(m.User, "worker").timezone = "America/New_York"
        child = subtasks.create(
            db,
            actor_id="owner",
            task_id="task",
            data={
                "title": "Legacy policy planned child",
                "planned_start_date": NOW.date(),
                "planned_end_date": (NOW + timedelta(days=1)).date(),
            },
        )
        assert child.point_policy_version == "legacy" and child.reward_timezone is None
        for who in ("owner", "worker"):
            db.add(
                m.NotificationPreference(
                    user_id=who, module="tasks", near_deadline_hours=48
                )
            )
        activity.command(
            db, actor_id="owner", task_id="task", subtask_id=child.id, action="START"
        )
        db.commit()
        expected = datetime(2026, 11, 3, 18, 29, 59, 999999, tzinfo=UTC)
        for who in ("owner", "worker"):
            frame = activity.snapshot(db, actor_id=who)
            assert (
                next(
                    i
                    for i in frame["workload"]["near_deadline"]
                    if i.get("subtask_id") == child.id
                )["deadline"]
                == expected
            )
        alerts.scan(db)
        assert len(rows(db, "approaching_deadline")) == 3
        assert child.reward_timezone is None and db.get(m.User, "worker").points == 100


def test_retention_scrubs_dismissed_content_but_keeps_event_identity(
    harness, monkeypatch
):
    from backend.app import database

    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(alerts, "scan", lambda *a, **k: "")
    monkeypatch.setattr(alerts, "run_delivery", lambda *a: 0)
    monkeypatch.setenv("VEE_NOTIFICATION_RETENTION_DAYS", "30")
    dismissed = NOW - timedelta(days=32)
    with Session(engine) as db:
        emit(db, only={"worker"})
        note = rows(db, "test")[0]
        note.created_at = (NOW - timedelta(days=31)).replace(tzinfo=None)
        note.is_read = True
        note.dismissed_at = dismissed
        db.commit()
        note_id, key = note.id, note.dedupe_key
    alerts.maintenance()
    with Session(engine) as db:
        note = db.get(m.Notification, note_id)
        assert (
            note.message == "Expired notification"
            and note.body is None
            and note.title is None
        )
        assert note.dedupe_key == key and note.dismissed_at == dismissed
        emit(db, only={"worker"})
        db.commit()
        assert len(rows(db, "test")) == 1 and note.is_read


def test_profile_two_hundred_employees_bounded_scans(
    harness, monkeypatch, record_property
):
    import json
    import time

    engine, tenant, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        for i in range(200):
            key = f"profile-{i:03}"
            db.add(
                m.User(
                    id=key,
                    tenant_id=tenant,
                    name=key,
                    email=key + "@example.test",
                    hashed_password="fixture",
                )
            )
            db.add(
                m.Task(
                    id=key,
                    created_by_id="owner",
                    assigned_to_id=key,
                    title=key,
                    due_at=(NOW + timedelta(hours=2)).replace(tzinfo=None),
                )
            )
        db.commit()
    statements = []

    def count(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", count)
    start = time.perf_counter()
    try:
        cursor, batches = "", 0
        while True:
            with Session(engine) as db:
                cursor = alerts.scan(db, after_user=cursor, limit=100)
            batches += 1
            if not cursor:
                break
    finally:
        sa.event.remove(engine, "before_cursor_execute", count)
    with Session(engine) as db:
        assert len(rows(db, "approaching_deadline")) == 400
    record_property(
        "notification_scan_profile",
        json.dumps(
            {
                "employees": 200,
                "batch_size": 100,
                "batches": batches,
                "seconds": round(time.perf_counter() - start, 3),
                "sql_statements": len(statements),
            }
        ),
    )


def test_existing_notification_integrations_receive_committed_row_once(
    harness, monkeypatch
):
    from backend.app.services import notification_dispatcher, task_events

    engine, tenant, _ = harness
    pushed, events, logs = [], [], []
    monkeypatch.setattr(
        notification_dispatcher, "push_if_enabled", lambda db, **kw: pushed.append(kw)
    )
    monkeypatch.setattr(
        notification_dispatcher,
        "trigger_n8n_event",
        lambda name, payload: events.append((name, payload)),
    )
    monkeypatch.setattr(notification_dispatcher.audit_logger, "log_event", logs.append)
    monkeypatch.setattr(task_events, "publish_task_event", lambda *a: None)
    with Session(engine) as db:
        for n in rows(db):
            n.delivery_pending = False
        emit(db, only={"worker"})
        db.commit()
        note = rows(db, "test")[0]
        alerts.run_delivery(db)
        alerts.run_delivery(db)
        assert len(pushed) == len(events) == len(logs) == 1
        assert events[0][0] == "notification.created"
        assert events[0][1]["id"] == note.id and events[0][1]["tenant_id"] == str(
            tenant
        )
        assert logs[0].entity_id == note.id and logs[0].target_user_id == "worker"


def test_legacy_task_deletion_keeps_one_readable_scoped_notification(api):
    client, engine, identity = api
    identity["id"] = "owner"
    assert client.delete("/tasks/task").status_code == 204
    assert client.delete("/tasks/task").status_code == 404
    with Session(engine) as db:
        notes = rows(db, "task_deleted")
        assert {n.user_id for n in notes} == {"owner", "worker", "watcher"}
        assert len(notes) == 3 and all(n.related_task_id is None for n in notes)
        assert all(n.type == m.NotificationTypeEnum.TASK_DELETED for n in notes)
        assert db.get(m.User, "worker").points == 100
    identity["id"] = "worker"
    items = client.get("/notifications/inbox").json()["items"]
    assert len(items) == 1 and items[0]["type"] == "TASK_DELETED"
    assert items[0]["deep_link"] == "/tasks"


def test_rejected_historic_task_deletion_does_not_emit_false_alert(api):
    from backend.app.services import audit_logger

    client, engine, identity = api
    identity["id"] = "owner"
    with Session(engine) as db:
        audit_logger.record_task_activity(
            db,
            actor_id="owner",
            task_id="task",
            data={"event_type": "task.note", "after": {"note": "Retained history"}},
        )
        db.commit()
    assert client.delete("/tasks/task").status_code == 409
    with Session(engine) as db:
        assert not rows(db, "task_deleted") and db.get(m.Task, "task") is not None


def test_aggregate_worker_is_singleton_retries_and_stops(monkeypatch):
    from threading import Event

    ready, calls = Event(), []

    def tick(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Synthetic transient maintenance failure")
        ready.set()

    monkeypatch.setattr(alerts, "maintenance", tick)
    try:
        alerts.start_maintenance(interval_seconds=0.01)
        thread = alerts._worker_thread
        alerts.start_maintenance(interval_seconds=0.01)
        assert alerts._worker_thread is thread
        assert ready.wait(timeout=3)
    finally:
        alerts.stop_maintenance(timeout_seconds=3)
    assert alerts._worker_thread is None and not thread.is_alive() and len(calls) >= 2


def test_additive_migration_keeps_legacy_inbox_and_wallet(harness, monkeypatch):
    engine, tenant, _ = harness
    module = importlib.import_module(
        "backend.alembic.versions.j0f2b4d6e8a0_workload_notifications"
    )
    # Synthetic old inbox tables alongside a realistic complete current schema.
    with engine.begin() as conn:
        conn.execute(
            sa.insert(XpLedger).values(
                tenant_id=tenant,
                user_id="worker",
                record_version=1,
                event_type="historic",
                ref_type="historic",
                points=17,
                created_at=datetime(2025, 1, 1, tzinfo=UTC),
            )
        )
        before = conn.execute(sa.select(m.User.id, m.User.points)).all()
        historical_ledger = conn.execute(sa.select(XpLedger.__table__)).all()
        m.Notification.__table__.drop(conn)
        m.NotificationPreference.__table__.drop(conn)
        m.PushSubscription.__table__.drop(conn)
        native = engine.dialect.name == "postgresql"
        if native:
            m.Notification.__table__.c.type.type.create(conn, checkfirst=True)
            m.Notification.__table__.c.entity_type.type.create(conn, checkfirst=True)
        notification_type = (
            m.Notification.__table__.c.type.type.name if native else "VARCHAR(64)"
        )
        entity_type = (
            m.Notification.__table__.c.entity_type.type.name
            if native
            else "VARCHAR(36)"
        )
        preference_time = "TIMESTAMP WITH TIME ZONE" if native else "TIMESTAMP"
        conn.exec_driver_sql(
            f"CREATE TABLE push_subscriptions (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE, endpoint TEXT UNIQUE NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL, user_agent TEXT, device_label VARCHAR(255), created_at {preference_time} NOT NULL, last_seen_at {preference_time}, revoked_at {preference_time})"
        )
        conn.exec_driver_sql(
            "INSERT INTO push_subscriptions(id,user_id,endpoint,p256dh,auth,created_at) VALUES ('old-device','worker','https://push.example.test/old','fixture-key','fixture-auth','2025-01-01')"
        )
        conn.exec_driver_sql(
            f"CREATE TABLE notifications (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE, type {notification_type} NOT NULL, title VARCHAR(255), body TEXT, message TEXT NOT NULL, entity_type {entity_type}, entity_id VARCHAR(36), deep_link VARCHAR(1024), is_read BOOLEAN NOT NULL, related_task_id VARCHAR(36), related_reward_id VARCHAR(36), related_chat_id VARCHAR(36) REFERENCES chat_conversations(id) ON DELETE CASCADE, created_at TIMESTAMP NOT NULL)"
        )
        conn.exec_driver_sql(
            f"CREATE TABLE notification_preferences (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE, module VARCHAR(50) NOT NULL, push_enabled BOOLEAN NOT NULL, updated_at {preference_time} NOT NULL, CONSTRAINT uq_notification_preferences_user_module UNIQUE(user_id,module))"
        )
        conn.exec_driver_sql(
            "INSERT INTO notification_preferences(id,user_id,module,push_enabled,updated_at) VALUES ('legacy-pref','worker','tasks',false,'2025-01-01')"
        )
        conn.execute(
            sa.text(
                "INSERT INTO notifications(id,user_id,type,message,is_read,created_at) VALUES ('historic','worker','TASK_UPDATED','Historic retained',false,'2025-01-01')"
            )
        )
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.upgrade()  # guarded retry cannot duplicate or erase legacy data
        assert conn.execute(
            sa.text(
                "SELECT message, dedupe_key, delivery_pending FROM notifications WHERE id='historic'"
            )
        ).one() == ("Historic retained", None, False)
        assert (
            conn.execute(sa.select(m.Notification.__table__.c.type)).scalar_one()
            == m.NotificationTypeEnum.TASK_UPDATED
        )
        assert conn.execute(
            sa.text(
                "SELECT push_enabled, sound_enabled, near_deadline_hours, productive_capacity_hours FROM notification_preferences WHERE id='legacy-pref'"
            )
        ).one() == (False, False, 24, None)
        assert conn.execute(sa.select(m.User.id, m.User.points)).all() == before
        assert conn.execute(
            sa.text(
                "SELECT user_id,tenant_id,binding_key FROM push_subscriptions WHERE id='old-device'"
            )
        ).one() == ("worker", None, None)
        assert conn.execute(sa.select(XpLedger.__table__)).all() == historical_ledger
        with pytest.raises(RuntimeError, match="retain"):
            module.downgrade()


def test_record_only_adjustment_does_not_claim_wallet_payout(harness):
    from backend.app.services import audit_logger as repo
    from backend.tests.test_task_audit_foundation import activity as audit
    from backend.tests.test_task_audit_foundation import adjustment

    engine, _, _ = harness
    with Session(engine) as db:
        event = audit(db)
        repo.append_point_adjustment(
            db, actor_id="owner", task_id="task", data=adjustment(event.id)
        )
        db.commit()
        assert not rows(db, "bonus_applied")
        assert db.get(m.User, "worker").points == 100


def test_push_actions_are_owner_scoped_and_rebind_requires_device_keys(
    api, monkeypatch
):
    import json

    from backend.app.services import push_service

    client, engine, identity = api
    payload = {
        "endpoint": "https://push.example.test/device",
        "keys": {"p256dh": "fixture-public-key", "auth": "fixture-device-proof"},
        "binding_protocol": "user-v1",
    }
    response = client.post("/push/subscribe", json=payload)
    assert response.status_code == 204
    first_key = response.headers["x-zea-push-binding"]
    assert (
        client.post("/push/subscribe", json=payload).headers["x-zea-push-binding"]
        == first_key
    )
    identity["id"] = "foreign"
    assert (
        client.post(
            "/push/unsubscribe", json={"endpoint": payload["endpoint"]}
        ).status_code
        == 204
    )
    with Session(engine) as db:
        assert db.scalar(sa.select(m.PushSubscription)).revoked_at is None
    invalid = {**payload, "keys": {"p256dh": "wrong", "auth": "wrong"}}
    assert client.post("/push/subscribe", json=invalid).status_code == 403
    rebound = client.post("/push/subscribe", json=payload)
    assert (
        rebound.status_code == 204
        and rebound.headers["x-zea-push-binding"] != first_key
    )
    second_key = rebound.headers["x-zea-push-binding"]
    sent = []
    monkeypatch.setattr(push_service, "get_vapid_public_key", lambda: "fixture-public")
    monkeypatch.setattr(
        push_service, "_get_vapid_private_key", lambda: "fixture-private"
    )
    monkeypatch.setattr(
        push_service, "_get_vapid_subject", lambda: "mailto:fixture@example.test"
    )
    monkeypatch.setattr(
        push_service, "webpush", lambda **kw: sent.append(json.loads(kw["data"]))
    )
    with Session(engine) as db:
        assert (
            push_service.send_push(
                db, user_ids=["worker"], payload={"title": "Do not send"}
            )
            == 0
        )
        assert (
            push_service.send_push(
                db, user_ids=["foreign"], payload={"title": "Own account"}
            )
            == 1
        )
        db.commit()
        assert sent == [{"title": "Own account", "binding_key": second_key}]
        # A tenant move or inactive account cannot retain the previous routing binding.
        db.get(m.User, "foreign").tenant_id = db.get(m.User, "worker").tenant_id
        db.commit()
        assert push_service.send_push(db, user_ids=["foreign"], payload={}) == 0
    assert (
        client.post(
            "/push/unsubscribe", json={"endpoint": payload["endpoint"]}
        ).status_code
        == 204
    )
    with Session(engine) as db:
        assert db.scalar(sa.select(m.PushSubscription)).revoked_at is not None


def test_concurrent_push_enrollment_has_one_owned_device_row(harness):
    from backend.app.services.push_service import save_subscription

    engine, _, _ = harness
    gate = Barrier(4)

    def enroll(_):
        gate.wait(timeout=10)
        with Session(engine) as db:
            row = save_subscription(
                db,
                user_id="worker",
                endpoint="https://push.example.test/race",
                p256dh="fixture",
                auth="fixture",
                binding_protocol="user-v1",
            )
            db.commit()
            return row.binding_key

    with ThreadPoolExecutor(max_workers=4) as pool:
        keys = list(pool.map(enroll, range(4)))
    assert len(set(keys)) == 1
    with Session(engine) as db:
        assert (
            db.scalar(sa.select(sa.func.count()).select_from(m.PushSubscription)) == 1
        )


def test_legacy_push_device_requires_authenticated_binding(harness, monkeypatch):
    from backend.app.services import push_service

    engine, _, _ = harness
    monkeypatch.setattr(push_service, "get_vapid_public_key", lambda: "fixture-public")
    monkeypatch.setattr(
        push_service, "_get_vapid_private_key", lambda: "fixture-private"
    )
    monkeypatch.setattr(
        push_service, "_get_vapid_subject", lambda: "mailto:fixture@example.test"
    )
    monkeypatch.setattr(
        push_service,
        "webpush",
        lambda **kw: pytest.fail("Unbound device must not receive account data"),
    )
    with Session(engine) as db:
        push_service.save_subscription(
            db,
            user_id="worker",
            endpoint="https://push.example.test/old",
            p256dh="fixture",
            auth="fixture",
        )
        db.commit()
        assert (
            push_service.send_push(
                db, user_ids=["worker"], payload={"title": "private"}
            )
            == 0
        )


def test_inactive_assignee_deadlines_still_reach_authorized_creator_and_watchers(
    harness, monkeypatch
):
    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        worker = db.get(m.User, "worker")
        worker.status = m.UserStatusEnum.DEACTIVATED
        worker.manager_id = "owner"
        task = db.get(m.Task, "task")
        task.due_at = (NOW - timedelta(minutes=1)).replace(tzinfo=None)
        db.commit()
        alerts.scan_inactive_deadlines(db)
        assert {n.user_id for n in rows(db, "task_overdue")} == {"owner", "watcher"}
        before = len(rows(db))
        alerts.scan_inactive_deadlines(db)
        assert len(rows(db)) == before
        worker.status = m.UserStatusEnum.ACTIVE
        db.commit()
        alerts.scan(db)
        assert len(rows(db, "task_overdue")) == 3
        assert len([n for n in rows(db, "task_overdue") if n.user_id == "worker"]) == 1


def test_new_subtask_notifies_inherited_assignment_once(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        child = create(db, 1)[0]
        db.commit()
        notices = rows(db, "subtask_assigned")
        assert {n.user_id for n in notices} == {"worker", "owner", "watcher"}
        assert all(
            n.type == m.NotificationTypeEnum.TASK_ASSIGNED
            and child.title in n.message
            and f"subtask={child.id}" in n.deep_link
            for n in notices
        )
        event = db.scalar(
            sa.select(m.AuditEvent).where(
                m.AuditEvent.subtask_id == child.id,
                m.AuditEvent.event_type == "subtask.created",
            )
        )
        alerts.from_event(db, event)
        db.commit()
        assert len(rows(db, "subtask_assigned")) == 3
