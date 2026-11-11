"""Synthetic Phase 4 race, read-load and resource regressions; no installed DB."""

# ruff: noqa: F811 -- imported disposable pytest fixtures
import asyncio
import json
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.services import subtask_rewards as rewards
from backend.app.services import task_activity as activity
from backend.app.ws import tasks as sockets
from backend.tests.test_task_activity import NOW, change, clock, seed  # noqa: F401
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401
from backend.tests.test_task_tabs_review import harness as api_harness  # noqa: F401


def history(db, count=5, users=1, running=True, work=0):
    tenant = db.get(m.User, "owner").tenant_id
    ids = ["owner"] if users == 1 else [f"profile-{u:03}" for u in range(users)]
    for user in ids:
        if user != "owner":
            db.add(
                m.User(
                    id=user,
                    tenant_id=tenant,
                    name=user,
                    email=user + "@example.test",
                    hashed_password="fixture",
                    role=m.RoleEnum.USER,
                )
            )
    db.flush()
    rows = []
    for user in ids:
        for i in range(count):
            task_id, child_id, context_id = (
                f"{prefix}-{user}-{i}" for prefix in ("p", "s", "c")
            )
            db.add(
                m.Task(
                    id=task_id,
                    title=task_id,
                    assigned_to_id=user,
                    created_by_id="owner",
                    estimated_hours=1,
                )
            )
            rows.append((user, task_id, child_id, context_id, i))
    db.flush()
    db.add_all(
        [
            m.Subtask(id=child, task_id=parent, title=child)
            for _, parent, child, _, _ in rows
        ]
    )
    db.flush()
    events, contexts = [], []
    for user, parent, child, key, number in rows:
        event_id = str(uuid.uuid4())
        state = {
            "context_id": key,
            "user_id": user,
            "subtask_id": child,
            "status": "RUNNING" if running else "PAUSED",
            "slot": number + 1 if running else None,
            "elapsed_ms": 1000,
            "resumed_at": NOW.isoformat() if running else None,
            "version": 1,
        }
        events.append(
            m.AuditEvent(
                id=event_id,
                audit_schema_version=2,
                tenant_id=tenant,
                actor_id=user,
                task_id=parent,
                subtask_id=child,
                event_type="work.started" if running else "work.paused",
                entity_type="subtask",
                entity_id=child,
                before={"subtask_id": child, "elapsed_ms": 0},
                after=state,
                payload={},
                created_at=NOW,
            )
        )
        contexts.append(
            m.TaskActivityContext(
                id=key,
                tenant_id=tenant,
                user_id=user,
                task_id=parent,
                subtask_id=child,
                status=state["status"],
                slot=state["slot"],
                elapsed_ms=1000,
                resumed_at=NOW if running else None,
                version=1,
                activity_event_id=event_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    db.add_all(events)
    db.flush()
    db.add_all(contexts)
    db.commit()
    for user in ids:
        for index in range(work):
            parent, child = f"p-{user}-{index % count}", f"s-{user}-{index % count}"
            start = NOW - timedelta(minutes=(work - index) * 10)
            end = start + timedelta(minutes=5)
            event = m.AuditEvent(
                audit_schema_version=2,
                tenant_id=tenant,
                actor_id=user,
                task_id=parent,
                subtask_id=child,
                event_type="subtask.manual_work_logged",
                entity_type="subtask",
                entity_id=child,
                after={"started_at": start.isoformat(), "ended_at": end.isoformat()},
                payload={},
                created_at=NOW,
            )
            db.add(event)
            db.flush()
            db.add(
                m.TaskWorkInterval(
                    tenant_id=tenant,
                    task_id=parent,
                    subtask_id=child,
                    user_id=user,
                    created_by_id=user,
                    started_at=start,
                    ended_at=end,
                    activity_event_id=event.id,
                    request_id=str(uuid.uuid4()),
                    created_at=NOW,
                )
            )
    db.commit()
    return ids


def test_profile_snapshots_are_read_only(harness, clock, record_property):
    engine, _, _ = harness
    with Session(engine) as db:
        history(db)
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", capture)
    durations = []
    try:
        for _ in range(10):
            started = time.perf_counter()
            with Session(engine) as db:
                frame = activity.snapshot(db, actor_id="owner")
                assert frame["active_count"] == 5
                assert all(c["actual_start_at"] is None for c in frame["contexts"])
            durations.append((time.perf_counter() - started) * 1000)
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
    writes = [
        s
        for s in statements
        if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert writes == []
    # Snapshot reads never need private notes, attachments, auth fields from
    # related task users, or dependency/follower collections.
    assert not any("task_work_intervals.note" in sql for sql in statements)
    record_property(
        "profile",
        json.dumps(
            {
                "requests": 10,
                "sql_per_snapshot": len(statements) / 10,
                "median_ms": statistics.median(durations),
                "max_ms": max(durations),
                "writes": 0,
            }
        ),
    )


def test_long_child_history_does_not_exceed_sql_expression_depth(harness, clock):
    engine, _, _ = harness
    with Session(engine) as db:
        history(db, count=1100, running=False)
        result = activity.snapshot(db, actor_id="owner")
        assert len(result["contexts"]) == 1100
        assert result["active_count"] == 0
        assert all(c["subtask_elapsed_seconds"] == 1 for c in result["contexts"])


def test_postgres_independent_users_do_not_take_exclusive_tenant_turns(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Real PostgreSQL lock modes required")
    with Session(engine) as db:
        seed(db)
        db.get(m.Task, "work-1").assigned_to_id = "watcher"
        db.commit()
    entered, release = Event(), Event()

    def first():
        with Session(engine) as db:
            change(db, user="worker")
            entered.set()
            assert release.wait(10)
            db.commit()

    def second():
        with Session(engine) as db:
            change(db, task="work-1", user="watcher")
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(first)
        assert entered.wait(10)
        two = pool.submit(second)
        try:
            two.result(timeout=5)
        finally:
            release.set()
        one.result(timeout=10)


def test_postgres_crossed_creator_actor_locks_and_reward_barrier(harness):
    engine, tenant, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Real PostgreSQL lock modes required")
    with Session(engine) as db:
        seed(db)
        db.get(m.Task, "work-1").created_by_id = "worker"
        db.get(m.Task, "work-1").assigned_to_id = "owner"
        db.commit()
    gate = Barrier(2)

    def start(user, task):
        with Session(engine) as db:
            gate.wait(timeout=10)
            change(db, task=task, user=user)
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(start, "worker", "work-0"),
            pool.submit(start, "owner", "work-1"),
        ]
        for future in futures:
            future.result(timeout=15)
    entered, release, exclusive = Event(), Event(), Event()

    def hold():
        with Session(engine) as db:
            change(db, user="worker", action="PAUSE")
            entered.set()
            assert release.wait(10)
            db.commit()

    def reward():
        with Session(engine) as db:
            rewards.tenant_lock(db, tenant)
            exclusive.set()
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(hold)
        assert entered.wait(10)
        second = pool.submit(reward)
        try:
            assert not exclusive.wait(0.2)
        finally:
            release.set()
        first.result(timeout=10)
        second.result(timeout=10)
    assert exclusive.is_set()


def test_postgres_pause_resume_switch_cas_races(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Real PostgreSQL transactions required")
    with Session(engine) as db:
        seed(db)
        change(db)
        db.add_all(
            [m.Subtask(id=child, title=child, task_id="work-0") for child in ["a", "b"]]
        )
        db.commit()
    for version, commands in [
        (1, [("PAUSE", None), ("START", "a")]),
        (2, [("START", "a"), ("START", "b")]),
    ]:
        gate = Barrier(2)

        def submit(command, gate=gate, version=version):
            with Session(engine) as db:
                gate.wait(timeout=10)
                try:
                    change(
                        db,
                        action=command[0],
                        subtask_id=command[1],
                        expected_version=version,
                    )
                    db.commit()
                    return 200
                except HTTPException as e:
                    db.rollback()
                    return e.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, commands))
        assert sorted(outcomes) == [200, 409]
    with Session(engine) as db:
        result = activity.snapshot(db, actor_id="owner")
        assert result["active_count"] == 1 and result["contexts"][0]["version"] == 3


def test_profile_two_hundred_user_snapshots(harness, clock, record_property):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Owned PostgreSQL load fixture required")
    with Session(engine) as db:
        subjects = history(db, users=200, work=10)
    durations, writes, statements = [], [], []
    mutex = Lock()

    def capture(conn, cursor, statement, parameters, context, many):
        with mutex:
            statements.append(1)
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

    sa.event.listen(engine, "before_cursor_execute", capture)

    def request(subject):
        begin = time.perf_counter()
        with Session(engine) as db:
            frame = activity.snapshot(db, actor_id=subject)
            assert frame["active_count"] == 5 and len(frame["contexts"]) == 5
            assert frame["workload"]["manual_seconds"] == 3000
        return (time.perf_counter() - begin) * 1000

    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            durations = list(pool.map(request, subjects))
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
    elapsed = time.perf_counter() - started
    assert not writes
    record_property(
        "profile",
        json.dumps(
            {
                "users": 200,
                "concurrency": 20,
                "requests": len(durations),
                "seconds": elapsed,
                "requests_per_second": len(durations) / elapsed,
                "sql_per_snapshot": len(statements) / len(durations),
                "median_ms": statistics.median(durations),
                "p95_ms": sorted(durations)[int(len(durations) * 0.95) - 1],
                "writes": 0,
            }
        ),
    )


def test_targeted_socket_fanout_checks_each_identity_once(monkeypatch, record_property):
    class Socket:
        def __init__(self, user):
            self.state = SimpleNamespace(navigation_identity=(user, "tenant"))
            self.messages = []

        async def accept(self):
            pass

        async def send_json(self, value):
            self.messages.append(value)

        async def close(self, code):
            pass

    checks = []
    monkeypatch.setattr(
        sockets,
        "_delivery_allowed",
        lambda socket, subject: (
            checks.append((socket.state.navigation_identity, subject)) or True
        ),
    )

    async def run():
        manager = sockets.TaskConnectionManager()
        clients = [Socket(f"user-{i}") for i in range(200)]
        duplicate = Socket("user-0")
        for client in [*clients, duplicate]:
            await manager.connect("tenant", client)
        await manager.broadcast(None, {"type": "private"})
        assert not any(c.messages for c in clients)
        await manager.broadcast(
            "tenant",
            {"type": "work.changed", "tenant_id": "tenant", "user_id": "user-0"},
        )
        assert len(checks) == 1 and len(duplicate.messages) == 1
        assert len(clients[0].messages) == 1 and not any(
            c.messages for c in clients[1:]
        )
        for client in [*clients, duplicate]:
            await manager.disconnect("tenant", client)
        assert manager._connections == {}

    asyncio.run(run())
    record_property(
        "fanout",
        json.dumps(
            {
                "users": 200,
                "tabs": 201,
                "authorization_checks": len(checks),
                "deliveries": 2,
            }
        ),
    )


def test_backward_server_clock_is_a_conflict_without_false_elapsed(harness, clock):
    engine, _, _ = harness
    with Session(engine) as db:
        seed(db)
        change(db)
        db.commit()
        clock[0] -= timedelta(seconds=1)
        with pytest.raises(HTTPException) as failure:
            change(db, action="PAUSE", expected_version=1)
        assert (
            failure.value.status_code == 409 and "Server clock" in failure.value.detail
        )
        db.commit()
        row = db.scalar(sa.select(m.TaskActivityContext))
        assert row.version == 1 and row.elapsed_ms == 0
        clock[0] += timedelta(seconds=11)
        change(db, action="PAUSE", expected_version=1)
        db.commit()
        assert row.elapsed_ms == 10000 and row.version == 2


def test_signed_watch_subscription_revocation_and_heartbeat_cleanup(
    api_harness, monkeypatch
):
    from sqlalchemy.orm import sessionmaker
    from starlette.websockets import WebSocketDisconnect

    from backend.app.auth import create_access_token
    from backend.app.routers import tasks
    from backend.app.services import navigation_sockets

    client, engine, identity = api_harness
    sessions = sessionmaker(engine)
    monkeypatch.setattr(sockets, "SessionLocal", sessions)
    monkeypatch.setattr(navigation_sockets, "SessionLocal", sessions)
    monkeypatch.setattr(sockets, "manager", sockets.TaskConnectionManager())
    client.app.include_router(sockets.router)
    with Session(engine) as db:
        db.get(m.User, "owner").role = m.RoleEnum.MANAGER
        db.get(m.User, "peer").manager_id = "owner"
        db.get(m.Task, "main").assigned_to_id = "peer"
        db.commit()
        tenant = str(db.get(m.User, "owner").tenant_id)
        foreign = str(db.get(m.User, "foreign").tenant_id)

    def token(user, group):
        return create_access_token(user, extra_claims={"tenant_id": group})

    def publish(payload):
        client.portal.call(sockets.broadcast_task_event, payload)

    monkeypatch.setattr(tasks.task_events, "publish_task_event", publish)
    with (
        client.websocket_connect(
            f"/ws/tasks?token={token('owner', tenant)}"
        ) as manager,
        client.websocket_connect(f"/ws/tasks?token={token('peer', tenant)}") as peer,
        client.websocket_connect(
            f"/ws/tasks?token={token('foreign', foreign)}"
        ) as outsider,
    ):
        manager.send_json({"type": "activity.watch", "user_id": "peer"})
        assert manager.receive_json() == {
            "type": "activity.watching",
            "user_id": "peer",
        }
        for socket in [peer, outsider]:
            socket.send_json({"type": "activity.watch", "user_id": "owner"})
            assert socket.receive_json()["type"] == "activity.watch_denied"
        identity["id"] = "peer"
        response = client.post(
            "/tasks/main/activity",
            json={
                "action": "START",
                "expected_version": 0,
                "request_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 200, response.text
        assert peer.receive_json()["user_id"] == "peer"
        assert manager.receive_json()["user_id"] == "peer"
        with Session(engine) as db:
            db.get(m.User, "peer").manager_id = None
            db.commit()
        response = client.post(
            "/tasks/main/activity",
            json={
                "action": "PAUSE",
                "expected_version": 1,
                "request_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 200
        assert peer.receive_json()["user_id"] == "peer"
        with pytest.raises(WebSocketDisconnect) as revoked:
            manager.receive_json()
        assert revoked.value.code == 1008
        client.portal.call(
            sockets.broadcast_task_event, {"type": "sentinel", "tenant_id": foreign}
        )
        assert outsider.receive_json()["type"] == "sentinel"
    assert sockets.manager._connections == {}

    async def count_heartbeats():
        return sum(
            getattr(t.get_coro(), "__name__", "") == "_heartbeat"
            for t in asyncio.all_tasks()
        )

    assert client.portal.call(count_heartbeats) == 0


def test_postgres_snapshot_lookup_query_plans(harness, clock, record_property):
    engine, tenant, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Real PostgreSQL query plans required")
    with Session(engine) as db:
        history(db, users=200)
    plans = {}
    with engine.begin() as conn:
        for table in ["tasks", "users", "task_activity_contexts"]:
            conn.exec_driver_sql(f"ANALYZE {table}")
        queries = {
            "contexts": sa.select(m.TaskActivityContext).where(
                m.TaskActivityContext.tenant_id == tenant,
                m.TaskActivityContext.user_id == "profile-000",
            ),
            "parents": sa.select(m.Task.id).where(
                sa.or_(
                    m.Task.assigned_to_id == "profile-000",
                    m.Task.id.in_([f"p-profile-000-{i}" for i in range(5)]),
                ),
                m.Task.creator.has(m.User.tenant_id == tenant),
            ),
        }
        for name, query in queries.items():
            sql = str(
                query.compile(
                    dialect=conn.dialect, compile_kwargs={"literal_binds": True}
                )
            )
            plans[name] = conn.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql
            ).scalar_one()
    text = json.dumps(plans)
    assert "ix_activity_tenant_user_status" in text or "uq_activity_user_parent" in text
    assert "ix_tasks_assignee_status_updated" in text
    record_property("query_plans", text)
