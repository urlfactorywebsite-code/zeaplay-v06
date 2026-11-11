"""Phase 6 review: real transactions, synthetic identities, no external delivery."""

# ruff: noqa: F401, F811
import importlib
import json
from datetime import timedelta

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.services import workload_notifications as alerts
from backend.tests.test_subtask_rewards import complete, create
from backend.tests.test_task_activity import change, confirmed, seed
from backend.tests.test_task_audit_foundation import engine, harness
from backend.tests.test_workload_notifications import (
    NOW,
    api,
    emit,
    no_external_notification_sinks,
    rows,
)


def test_creator_assignee_manager_and_watcher_is_one_recipient(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        owner = db.get(m.User, "owner")
        owner.manager_id = owner.id
        task = db.get(m.Task, "task")
        task.assigned_to_id = owner.id
        task.followers = [owner]
        db.commit()
        for _ in range(20):
            emit(db, "same-multi-role")
        db.commit()
        assert [n.user_id for n in rows(db, "test")] == ["owner"]


def test_nested_failure_preserves_outer_commit_fanout(harness, monkeypatch):
    from backend.app.services import task_events

    engine, tenant, _ = harness
    sent = []
    monkeypatch.setattr(task_events, "publish_task_event", sent.append)
    with Session(engine) as db:
        emit(db, "outer", only={"worker"})
        with pytest.raises(RuntimeError), db.begin_nested():
            emit(db, "rolled-back", only={"watcher"})
            raise RuntimeError("Synthetic savepoint failure")
        assert sent == []
        db.commit()
        assert sent == [
            {
                "type": "notifications.changed",
                "tenant_id": str(tenant),
                "user_id": "worker",
            }
        ]
        assert [n.user_id for n in rows(db, "test")] == ["worker"]


def test_out_of_order_work_replay_cannot_revive_fifth_alert(harness, monkeypatch):
    from backend.app.services import task_activity

    engine, _, _ = harness
    original = alerts.from_event
    with Session(engine) as db:
        seed(db)
        with monkeypatch.context() as temporary:
            temporary.setattr(alerts, "from_event", lambda *a: None)
            for i in range(5):
                change(db, f"work-{i}")
            db.commit()
            change(db, "work-4", "PAUSE")
            db.commit()
        event = db.scalar(
            sa.select(m.AuditEvent).where(
                m.AuditEvent.task_id == "work-4",
                m.AuditEvent.event_type == "work.started",
            )
        )
        for _ in range(5):
            original(db, event)
        db.commit()
        assert not rows(db, "active_limit")
        assert task_activity.snapshot(db, actor_id="owner")["active_count"] == 4


def test_out_of_order_status_delivery_preserves_event_chronology(harness, monkeypatch):
    engine, _, _ = harness
    original = alerts.from_event
    with Session(engine) as db:
        with monkeypatch.context() as temporary:
            temporary.setattr(alerts, "from_event", lambda *a: None)
            child = create(db, 1)[0]
            complete(db, child)
            db.commit()
        events = list(
            db.scalars(
                sa.select(m.AuditEvent)
                .where(m.AuditEvent.subtask_id == child.id)
                .order_by(m.AuditEvent.created_at)
            )
        )
        for event in reversed(events):
            original(db, event)
        db.commit()
        notes = rows(db)
        count = len(notes)
        for event in events:
            original(db, event)
        db.commit()
        assert len(rows(db)) == count
        by_key = {n.dedupe_key: n for n in notes if n.user_id == "worker"}
        for event in events:
            matches = [
                n
                for n in by_key.values()
                if n.dedupe_key
                == alerts._event_key(event.tenant_id, event.id, n.alert_kind)
            ]
            for notice in matches:
                assert alerts._created_at(notice.created_at) == alerts._created_at(
                    event.created_at
                )
        assert any(n.alert_kind == "subtask_completed" for n in notes)
        assert db.get(m.User, "worker").points == 100


@pytest.mark.parametrize("change", ["threshold", "deadline", "completed"])
def test_stale_deadline_is_not_pushed_after_policy_or_task_change(
    harness, monkeypatch, change
):
    from backend.app.services import notification_dispatcher

    engine, _, _ = harness
    sent = []
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    monkeypatch.setattr(
        notification_dispatcher,
        "deliver_stored_notification",
        lambda db, n, **kw: sent.append(n.alert_kind),
    )
    with Session(engine) as db:
        task = db.get(m.Task, "task")
        task.due_at = (NOW + timedelta(hours=2)).replace(tzinfo=None)
        pref = m.NotificationPreference(
            user_id="worker", module="tasks", near_deadline_hours=4
        )
        db.add(pref)
        db.commit()
        alerts.scan(db)
        old = rows(db, "approaching_deadline")
        assert len(old) == 3
        if change == "threshold":
            pref.near_deadline_hours = 1
        elif change == "deadline":
            task.due_at = (NOW + timedelta(days=2)).replace(tzinfo=None)
        else:
            task.status = m.TaskStatusEnum.DONE
        db.commit()
        alerts.run_delivery(db)
        assert "approaching_deadline" not in sent
        assert all(not n.delivery_pending for n in old)
        # Increasing the threshold observes a new due instant once, with no
        # duplicate rows on repeated scans; no historical reward is touched.
        if change == "deadline":
            pref.near_deadline_hours = 72
            db.commit()
            alerts.scan(db)
            alerts.scan(db)
            assert len(rows(db, "approaching_deadline")) == 6


@pytest.mark.parametrize("operation", ["deadline", "completed", "deleted"])
def test_stale_subtask_deadline_and_completed_child_not_pushed(
    harness, monkeypatch, operation
):
    from backend.app.services import notification_dispatcher, subtasks

    engine, _, _ = harness
    sent = []
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    monkeypatch.setattr(
        notification_dispatcher,
        "deliver_stored_notification",
        lambda db, n, **kw: sent.append(n.alert_kind),
    )
    with Session(engine) as db:
        child = subtasks.create(
            db,
            actor_id="owner",
            task_id="task",
            data={
                "title": "Overdue child",
                "planned_start_date": NOW.date() - timedelta(days=2),
                "planned_end_date": NOW.date() - timedelta(days=1),
            },
        )
        db.commit()
        alerts.scan(db)
        assert rows(db, "subtask_overdue")
        if operation == "deadline":
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=child.id,
                data={
                    "expected_version": child.version,
                    "planned_end_date": NOW.date() + timedelta(days=5),
                },
            )
        elif operation == "completed":
            complete(db, child)
        else:
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=child.id,
                data={"expected_version": child.version, "deleted": True},
            )
        db.commit()
        alerts.run_delivery(db)
        assert "subtask_overdue" not in sent


def test_poison_delivery_rolls_back_only_its_savepoint(harness, monkeypatch):
    from backend.app.services import notification_dispatcher

    engine, _, _ = harness
    accepted = []

    def deliver(db, note, **kw):
        if note.user_id == "worker":
            db.execute(sa.text("INSERT INTO users (id) VALUES ('worker')"))
        accepted.append(note.id)

    monkeypatch.setattr(notification_dispatcher, "deliver_stored_notification", deliver)
    with Session(engine) as db:
        for n in rows(db):
            n.delivery_pending = False
        emit(db, "poison")
        db.commit()
        assert alerts.run_delivery(db) == 3
        notes = rows(db, "test")
        worker = next(n for n in notes if n.user_id == "worker")
        assert worker.delivery_pending and worker.delivery_attempts == 1
        assert len(accepted) == 2
        assert all(not n.delivery_pending for n in notes if n.user_id != "worker")
        assert db.info["phase6_delivery_stats"]["retried"] == 1


def test_new_session_restart_retries_one_stored_receipt(harness, monkeypatch):
    from backend.app.services import notification_dispatcher

    engine, _, _ = harness
    received = []

    def fail(*a, **kw):
        raise RuntimeError("Transient provider failure")

    monkeypatch.setattr(notification_dispatcher, "deliver_stored_notification", fail)
    with Session(engine) as db:
        for n in rows(db):
            n.delivery_pending = False
        emit(db, "restart", only={"worker"})
        db.commit()
        alerts.run_delivery(db)
        notice_id = rows(db, "test")[0].id
    monkeypatch.setattr(
        notification_dispatcher,
        "deliver_stored_notification",
        lambda db, n, **kw: received.append(n.id),
    )
    with Session(engine) as restarted:
        restarted.get(m.Notification, notice_id).next_delivery_at = (
            m.utc_now() - timedelta(seconds=1)
        )
        restarted.commit()
        alerts.run_delivery(restarted)
        emit(restarted, "restart", only={"worker"})
        restarted.commit()
        alerts.run_delivery(restarted)
        assert received == [notice_id]
        assert len(rows(restarted, "test")) == 1


def test_legacy_inbox_insert_gets_one_after_commit_invalidation(harness, monkeypatch):
    from backend.app.services import task_events

    engine, tenant, _ = harness
    sent = []
    monkeypatch.setattr(task_events, "publish_task_event", sent.append)
    with Session(engine) as db:
        db.add(
            m.Notification(
                user_id="worker",
                type=m.NotificationTypeEnum.TASK_UPDATED,
                message="Existing integration",
                is_read=False,
            )
        )
        db.flush()
        assert sent == []
        db.commit()
        assert sent == [
            {
                "type": "notifications.changed",
                "tenant_id": str(tenant),
                "user_id": "worker",
            }
        ]


def test_live_badge_count_handles_unread_state_and_removed_watcher(api):
    client, engine, identity = api
    identity["id"] = "watcher"
    with Session(engine) as db:
        emit(db, "badge", only={"watcher"})
        db.commit()
        note_id = rows(db, "test")[0].id
    initial = client.get("/notifications/inbox").json()["unread_count"]
    assert client.post(f"/notifications/{note_id}/read").status_code == 204
    assert client.get("/notifications/inbox").json()["unread_count"] == initial - 1
    with Session(engine) as db:
        db.get(m.Notification, note_id).is_read = False
        db.commit()
    assert client.get("/notifications/inbox").json()["unread_count"] == initial
    with Session(engine) as db:
        db.get(m.Task, "task").followers = []
        db.commit()
    assert client.get("/notifications/inbox").json()["unread_count"] == 0


def test_batched_fanout_keeps_one_row_per_authorized_recipient(
    harness, record_property
):
    engine, tenant, _ = harness
    with Session(engine) as db:
        people = [
            m.User(
                id=f"batch-{i:03}",
                tenant_id=tenant,
                email=f"batch-{i}@example.test",
                name=f"Synthetic {i}",
                hashed_password="fixture",
                role=m.RoleEnum.USER,
                status=m.UserStatusEnum.ACTIVE,
            )
            for i in range(205)
        ]
        db.add_all(people)
        db.flush()
        db.get(m.Task, "task").followers = people
        db.commit()
        statements = []

        def track(conn, cursor, statement, params, context, many):
            if statement.lower().startswith("insert into notifications"):
                statements.append(statement)

        sa.event.listen(engine, "before_cursor_execute", track)
        try:
            emit(db, "large-fanout")
            emit(db, "large-fanout")
            db.commit()
        finally:
            sa.event.remove(engine, "before_cursor_execute", track)
        assert len(rows(db, "test")) == 207
        assert len(statements) == 6  # Three bounded INSERTs per replay, not 207.
        record_property(
            "recipient_batch",
            json.dumps(
                {"recipients": 207, "replays": 2, "insert_statements": len(statements)}
            ),
        )


def test_additive_queue_index_upgrade_is_repeatable_and_keeps_data(
    harness, monkeypatch
):
    engine, _, _ = harness
    module = importlib.import_module(
        "backend.alembic.versions.k1a3c5e7f9b1_notification_queue_review"
    )
    with engine.begin() as connection:
        before = connection.execute(sa.select(m.Notification.__table__)).all()
        connection.exec_driver_sql("DROP INDEX ix_notification_pending_chronology")
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        module.upgrade()
        module.upgrade()
        module.downgrade()
        assert connection.execute(sa.select(m.Notification.__table__)).all() == before
        assert "ix_notification_pending_chronology" in {
            i["name"] for i in sa.inspect(connection).get_indexes("notifications")
        }


def test_workload_union_does_not_raise_false_overtime_and_paused_slots_are_free(
    harness, monkeypatch
):
    import uuid

    from backend.app.services import audit_logger, task_activity

    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    with Session(engine) as db:
        seed(db, 3)
        db.add(
            m.NotificationPreference(
                user_id="owner", module="tasks", productive_capacity_hours=1.75
            )
        )
        for i in range(3):
            change(db, f"work-{i}")
        db.commit()
        # The old repository accepts historical overlapping intervals. The
        # current command rejects new overlaps; projection must still union old ones.
        for parent, start, end in [("work-0", 120, 60), ("work-1", 90, 30)]:
            audit_logger.record_manual_work(
                db,
                actor_id="owner",
                task_id=parent,
                data={
                    "started_at": NOW - timedelta(minutes=start),
                    "ended_at": NOW - timedelta(minutes=end),
                    "request_id": str(uuid.uuid4()),
                },
            )
        change(db, "work-2", "PAUSE")
        task_activity.close_contexts(db, who=db.get(m.User, "owner"), task_id="work-1")
        db.commit()
        frame = task_activity.snapshot(db, actor_id="owner")
        assert frame["active_count"] == 1
        assert {c["status"] for c in frame["contexts"]} == {
            "RUNNING",
            "PAUSED",
            "COMPLETED",
        }
        assert frame["workload"]["manual_seconds"] == 5400
        assert frame["workload"]["overlap_seconds"] == 1800
        alerts.scan(db)
        assert not rows(db, "productive_overtime")


def test_retention_and_delivery_work_stays_bounded(harness, monkeypatch):
    from backend.app import database

    engine, tenant, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: NOW)
    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(alerts, "scan", lambda *a, **kw: "")
    monkeypatch.setattr(alerts, "scan_inactive_deadlines", lambda *a, **kw: "")
    monkeypatch.setattr(alerts, "run_delivery", lambda *a, **kw: 0)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(m.Notification),
            [
                {
                    "user_id": "worker",
                    "tenant_id": tenant,
                    "dedupe_key": f"retention-{i}",
                    "alert_kind": "test",
                    "type": m.NotificationTypeEnum.TASK_UPDATED,
                    "message": "Synthetic old content",
                    "is_read": True,
                    "created_at": (NOW - timedelta(days=31)).replace(tzinfo=None),
                }
                for i in range(510)
            ],
        )
    alerts.maintenance()
    with Session(engine) as db:
        assert (
            db.scalar(
                sa.select(sa.func.count())
                .select_from(m.Notification)
                .where(m.Notification.message == "Expired notification")
            )
            == 500
        )
    alerts.maintenance()
    with Session(engine) as db:
        assert (
            db.scalar(
                sa.select(sa.func.count())
                .select_from(m.Notification)
                .where(m.Notification.message == "Expired notification")
            )
            == 510
        )


def test_backlog_drain_does_not_spawn_threads_or_repeat_user_scan(monkeypatch):
    from threading import Event

    done, calls = Event(), []

    def tick(**kw):
        calls.append(kw["scan_workload"])
        if len(calls) >= 2:
            done.set()
        return {"due_remaining": len(calls) == 1}

    monkeypatch.setattr(alerts, "maintenance", tick)
    try:
        alerts.start_maintenance(interval_seconds=10)
        worker = alerts._worker_thread
        assert done.wait(timeout=3)
        assert alerts._worker_thread is worker
        assert calls == [True, False]
    finally:
        alerts.stop_maintenance(timeout_seconds=3)


def test_misrouted_cross_tenant_socket_payload_is_dropped(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from backend.app.ws import tasks

    class Socket:
        def __init__(self, tenant):
            self.state = SimpleNamespace(navigation_identity=("recipient", tenant))
            self.messages = []

        async def accept(self):
            pass

        async def send_json(self, message):
            self.messages.append(message)

    monkeypatch.setattr(tasks, "_delivery_allowed", lambda *a: True)

    async def check():
        manager = tasks.TaskConnectionManager()
        own, foreign = Socket("own"), Socket("foreign")
        await manager.connect("own", own)
        await manager.connect("foreign", foreign)
        await manager.connect(
            "own", foreign
        )  # synthetic routing fault must fail closed
        await manager.broadcast(
            "own",
            {
                "type": "notifications.changed",
                "user_id": "recipient",
                "tenant_id": "foreign",
            },
        )
        assert not own.messages and not foreign.messages
        await manager.broadcast(
            "own",
            {
                "type": "notifications.changed",
                "user_id": "recipient",
                "tenant_id": "own",
            },
        )
        assert len(own.messages) == 1 and not foreign.messages

    asyncio.run(check())


def test_scan_failure_does_not_stall_committed_delivery(harness, monkeypatch, caplog):
    from backend.app import database

    engine, _, _ = harness
    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine))

    def fail(*a, **kw):
        raise RuntimeError("Synthetic scan unavailable")

    delivered = []
    monkeypatch.setattr(alerts, "scan", fail)
    monkeypatch.setattr(alerts, "scan_inactive_deadlines", lambda *a, **kw: "")
    monkeypatch.setattr(alerts, "run_delivery", lambda *a, **kw: delivered.append(1))
    result = alerts.maintenance()
    assert delivered == [1] and result["scan_failures"] == 1
    assert "notification_workload_scan_failed scope=users" in caplog.text


def test_reward_event_replay_in_reverse_order_never_changes_accounting(
    harness, monkeypatch
):
    from backend.app.services import subtasks
    from backend.app.tickets.models import XpLedger
    from backend.tests.test_subtask_rewards import activate

    engine, _, _ = harness
    original = alerts.from_ledger
    with Session(engine) as db:
        with monkeypatch.context() as temporary:
            temporary.setattr(alerts, "from_ledger", lambda *a: None)
            activate(db)
            children = create(db, 2)
            child = sorted(children, key=lambda row: (row.created_at, row.id))[1]
            complete(db, child)
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=child.id,
                data={"expected_version": child.version, "action": "REOPEN"},
            )
            db.commit()
        entries = list(db.scalars(sa.select(XpLedger).order_by(XpLedger.created_at)))
        before = db.get(m.User, "worker").points
        for entry in reversed(entries):
            original(db, entry)
        db.commit()
        count = len(rows(db))
        for entry in entries:
            original(db, entry)
        db.commit()
        assert db.get(m.User, "worker").points == before == 100
        assert sum(row.points for row in entries) == 0
        assert len(rows(db)) == count
        for entry in entries:
            matches = [
                n
                for n in rows(db)
                if n.dedupe_key
                == alerts._event_key(
                    entry.tenant_id, f"ledger:{entry.id}", n.alert_kind
                )
            ]
            assert len(matches) == 3
            assert all(
                alerts._created_at(n.created_at) == alerts._created_at(entry.created_at)
                for n in matches
            )


def test_delivery_batch_limit_is_enforced_and_monitoring_has_no_task_details(
    harness, monkeypatch, caplog
):
    import logging

    from backend.app.services import notification_dispatcher

    engine, tenant, _ = harness
    sent = []
    monkeypatch.setattr(
        notification_dispatcher,
        "deliver_stored_notification",
        lambda db, n, **kw: sent.append(n.id),
    )
    with Session(engine) as db:
        for n in rows(db):
            n.delivery_pending = False
        db.commit()
        db.execute(
            sa.insert(m.Notification),
            [
                {
                    "user_id": "worker",
                    "tenant_id": tenant,
                    "dedupe_key": f"burst-{i}",
                    "alert_kind": "test",
                    "type": m.NotificationTypeEnum.TASK_UPDATED,
                    "message": "DO_NOT_LOG_PRIVATE_DETAILS",
                    "related_task_id": "task",
                    "is_read": False,
                    "delivery_pending": True,
                }
                for i in range(120)
            ],
        )
        db.commit()
        before = db.scalar(sa.select(sa.func.count()).select_from(m.Notification))
        with caplog.at_level(logging.INFO, logger=alerts.__name__):
            processed = alerts.run_delivery(db, limit=100000)
        stats = db.info["phase6_delivery_stats"]
        assert (
            stats["selected"] == 100 and 0 < processed <= 100 and stats["due_remaining"]
        )
        assert len(sent) == processed and stats["delivered"] == processed
        assert (
            db.scalar(sa.select(sa.func.count()).select_from(m.Notification)) == before
        )
        assert "notification_delivery_batch" in caplog.text
        assert "DO_NOT_LOG_PRIVATE_DETAILS" not in caplog.text


def _push_devices(db, monkeypatch):
    import uuid

    from backend.app.services import push_service

    monkeypatch.setattr(push_service, "get_vapid_public_key", lambda: "fixture-public")
    monkeypatch.setattr(
        push_service, "_get_vapid_private_key", lambda: "fixture-private"
    )
    monkeypatch.setattr(
        push_service, "_get_vapid_subject", lambda: "mailto:fixture@example.test"
    )
    for name in ["a", "b", "c"]:
        db.add(
            m.PushSubscription(
                id=f"device-{name}",
                user_id="worker",
                tenant_id=db.get(m.User, "worker").tenant_id,
                binding_key=str(uuid.uuid4()),
                endpoint=f"https://push.example.test/{name}",
                p256dh="fixture",
                auth="fixture",
            )
        )
    db.commit()
    return push_service


def test_transient_device_failure_does_not_block_other_devices_or_lose_revocation(
    harness, monkeypatch
):
    from pywebpush import WebPushException
    from requests import Response

    engine, _, _ = harness
    attempts = []
    with Session(engine) as db:
        push_service = _push_devices(db, monkeypatch)
        for n in rows(db):
            n.delivery_pending = False
        emit(db, "multi-device", only={"worker"})
        db.commit()

        def send(**kw):
            name = kw["subscription_info"]["endpoint"].rsplit("/", 1)[1]
            attempts.append(name)
            if name == "a":
                response = Response()
                response.status_code = 410
                raise WebPushException("Synthetic expired endpoint", response=response)
            if name == "b":
                raise TimeoutError("Synthetic unavailable device")

        monkeypatch.setattr(push_service, "webpush", send)
        alerts.run_delivery(db)
        assert attempts == ["a", "b", "c"]
        assert db.get(m.PushSubscription, "device-a").revoked_at is not None
        note = rows(db, "test")[0]
        assert note.delivery_attempts == 1 and note.delivery_pending
        note.next_delivery_at = m.utc_now() - timedelta(seconds=1)
        db.commit()
        attempts.clear()
        monkeypatch.setattr(
            push_service,
            "webpush",
            lambda **kw: attempts.append(
                kw["subscription_info"]["endpoint"].rsplit("/", 1)[1]
            ),
        )
        alerts.run_delivery(db)
        assert attempts == ["c", "b"] and not note.delivery_pending
        assert len(rows(db, "test")) == 1


def test_timing_out_first_device_rotates_on_retry(harness, monkeypatch):
    from types import SimpleNamespace

    engine, _, _ = harness
    with Session(engine) as db:
        push_service = _push_devices(db, monkeypatch)
        clock = [0]
        seen = []
        monkeypatch.setattr(
            push_service, "time", SimpleNamespace(monotonic=lambda: clock[0])
        )

        def send(**kw):
            name = kw["subscription_info"]["endpoint"].rsplit("/", 1)[1]
            seen.append(name)
            if name == "a":
                clock[0] += 4
                raise TimeoutError("Synthetic slow device")

        monkeypatch.setattr(push_service, "webpush", send)
        with pytest.raises(TimeoutError):
            push_service.send_push(
                db, user_ids=["worker"], payload={}, retry_failures=True, attempt=0
            )
        assert seen == ["a"]
        seen.clear()
        clock[0] = 0
        with pytest.raises(TimeoutError):
            push_service.send_push(
                db, user_ids=["worker"], payload={}, retry_failures=True, attempt=1
            )
        assert seen == ["b", "c", "a"]


def test_pending_chronology_index_under_a_large_ready_backlog(harness, record_property):
    engine, tenant, _ = harness
    with engine.begin() as connection:
        connection.execute(
            sa.insert(m.Notification),
            [
                {
                    "id": f"backlog-{i:05}",
                    "user_id": "worker",
                    "tenant_id": tenant,
                    "dedupe_key": f"backlog-{i:05}",
                    "alert_kind": "test",
                    "type": m.NotificationTypeEnum.TASK_UPDATED,
                    "message": "Synthetic pending queue",
                    "delivery_pending": i % 2 == 0,
                    "is_read": False,
                    "created_at": (NOW - timedelta(seconds=5000 - i)).replace(
                        tzinfo=None
                    ),
                }
                for i in range(5000)
            ],
        )
        native = engine.dialect.name == "postgresql"
        if native:
            connection.exec_driver_sql("ANALYZE notifications")
        prefix = "EXPLAIN " if native else "EXPLAIN QUERY PLAN "
        query = "SELECT id FROM notifications WHERE delivery_pending IS TRUE AND (next_delivery_at IS NULL OR next_delivery_at <= CURRENT_TIMESTAMP) ORDER BY created_at,id LIMIT 100"
        plan = "\n".join(
            str(row[0] if native else row[3])
            for row in connection.exec_driver_sql(prefix + query)
        )
        assert "ix_notification_pending_chronology" in plan
        record_property("large_ready_backlog_query_plan", plan)
