"""Cross-phase HTTP/SQL regression with real login, JWT, guards and accounting.

Only external/cache/asynchronous audit sinks are suppressed. No production
database, startup bootstrap, reward calculation or authorization is mocked.
"""
# ruff: noqa: F811 -- shared disposable database fixtures
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from threading import Barrier

import pytest
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from backend.app import models as m
from backend.app.auth import hash_password
from backend.app.database import get_db
from backend.app.navigation_guard import enforce_navigation_policy
from backend.app.routers import (
    auth,
    comments,
    config,
    notification_preferences,
    notifications,
    tasks,
    users,
)
from backend.app.services import audit_logger, notification_dispatcher, task_activity
from backend.app.services import subtask_rewards as rewards
from backend.app.services import workload_notifications as alerts
from backend.app.tickets.models import XpLedger
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401

PASSWORD = "phase7-synthetic-password"
PLAN = {"planned_start_date": "2026-11-02", "planned_end_date": "2026-11-03"}


@lru_cache(maxsize=1)
def fixture_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def system(harness, monkeypatch):
    engine, _tenant, _ = harness
    with Session(engine) as db:
        for user in db.scalars(sa.select(m.User)):
            user.hashed_password = fixture_hash()
            user.timezone = "Asia/Kolkata"
        db.get(m.User, "worker").manager_id = "owner"
        db.commit()
    app = FastAPI(dependencies=[Depends(enforce_navigation_policy)])
    for router in (auth.router, config.router, tasks.router, comments.router,
                   notifications.router, notification_preferences.router, users.router):
        app.include_router(router)
        app.include_router(router, prefix="/api")
    app.add_exception_handler(task_activity.ActivityLimitExceeded, alerts.limit_error_handler)

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = session
    from backend.app import database
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(engine))
    monkeypatch.setattr(audit_logger, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(notification_dispatcher, "trigger_n8n_event", lambda *a, **k: None)
    for name in ("get_cached_json", "set_cached_json", "invalidate_prefix", "trigger_n8n_event"):
        monkeypatch.setattr(tasks, name, lambda *a, **k: None)
    monkeypatch.setattr(comments, "trigger_n8n_event", lambda *a, **k: None)
    monkeypatch.setattr(users, "trigger_n8n_event", lambda *a, **k: None)
    monkeypatch.setattr(users, "send_notification_email", lambda *a, **k: None)
    # Capture the existing after-commit transport; durable notifications remain real.
    published = []
    from backend.app.services import task_events
    monkeypatch.setattr(task_events, "publish_task_event", lambda *events, **event: published.append((events, event)))
    with TestClient(app) as client:
        yield client, engine, published


def login(client, key="owner"):
    response = client.post("/api/auth/login", json={"email": f"{key}@example.com", "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]["access_token"]}


def ok(client, method, path, headers, *, code=200, **kwargs):
    response = client.request(method, path, headers=headers, **kwargs)
    assert response.status_code == code, response.text
    return response.json() if response.content else None


def parent(client, headers, count=3):
    return ok(client, "POST", "/api/tasks", headers, code=201, json={
        "title": "Phase 7 integration", "team": "IT Support", "priority": "HIGH",
        "assigned_to_id": "worker", "follower_ids": ["watcher"],
        "due_at": "2026-11-04T18:29:59Z",
        "subtasks": [{"title": f"Child {i + 1}", **PLAN} for i in range(count)],
    })[0]


def edit(client, headers, task_id, child, **changes):
    data = ok(client, "PATCH", f"/api/tasks/{task_id}/subtasks/{child['id']}", headers,
              json={"expected_version": child["version"], **changes})
    # Soft-deleted children intentionally disappear from the legacy task response.
    return next((row for row in data["subtasks"] if row["id"] == child["id"]), None)


def finish(client, headers, task_id, child, *, late=False):
    child = edit(client, headers, task_id, child, action="START")
    child = edit(client, headers, task_id, child,
                 actual_start_at="2026-11-03T10:00:00+05:30",
                 actual_end_at=("2026-11-04T00:00:00+05:30" if late else "2026-11-03T11:00:00+05:30"),
                 confirm_actual_times=True)
    return edit(client, headers, task_id, child, action="COMPLETE")


def test_authenticated_workflow_rewards_information_notifications_and_legacy(system, record_property):
    client, engine, published = system
    owner, worker, watcher, foreign = (login(client, key) for key in ("owner", "worker", "watcher", "foreign"))
    foreign_before = ok(client, "GET", "/api/notifications/inbox", foreign)["unread_count"]
    assert client.get("/api/tasks").status_code == 401
    assert client.post("/api/auth/login", json={"email": "worker@example.com", "password": "wrong"}).status_code == 401
    policy = ok(client, "PATCH", "/api/config/subtask-rewards", owner,
                json={"enabled": True, "expected_version": 0})
    assert policy["enabled"]
    assert client.patch("/api/config/subtask-rewards", headers=worker,
                        json={"enabled": False, "expected_version": policy["version"]}).status_code == 403
    assert client.post("/api/tasks", headers=owner, json={"title": "Invalid", "subtasks": [{"title": "Missing plan"}]}).status_code == 422
    task = parent(client, owner)
    task_id = task["id"]
    children = task["subtasks"]
    # Original creation order is authoritative; HTTP array ordering is not a reward input.
    with Session(engine) as db:
        ids = list(db.scalars(sa.select(m.Subtask.id).where(m.Subtask.task_id == task_id).order_by(m.Subtask.created_at, m.Subtask.id)))
    children = sorted(children, key=lambda row: ids.index(row["id"]))
    assert task["subtask_rewards"]["available_base"] == 60
    inherited = children[0]
    assert inherited["effective_priority"] == "HIGH"
    override = edit(client, owner, task_id, children[1], priority_override="LOW")
    assert override["effective_priority"] == "LOW"
    # Full workflow preserves manually entered timestamps through every status action.
    for action, status in [("START", "IN_PROGRESS"), ("PAUSE", "PAUSED"), ("RESUME", "IN_PROGRESS"), ("SEND_TO_TESTING", "TESTING")]:
        override = edit(client, worker, task_id, override, action=action)
        assert override["status"] == status
        assert override["actual_start_at"] is override["actual_end_at"] is None
    assert client.patch(f"/api/tasks/{task_id}/subtasks/{override['id']}", headers=worker,
                        json={"expected_version": override["version"], "action": "COMPLETE"}).status_code == 422
    override = edit(client, worker, task_id, override, actual_start_at="2026-11-03T10:00:00+05:30",
                    actual_end_at="2026-11-03T11:00:00+05:30", confirm_actual_times=True)
    times = override["actual_start_at"], override["actual_end_at"]
    children[1] = edit(client, worker, task_id, override, action="COMPLETE")
    assert (children[1]["actual_start_at"], children[1]["actual_end_at"]) == times
    children[2] = finish(client, worker, task_id, children[2], late=True)
    with Session(engine) as db:
        entries = list(db.scalars(sa.select(XpLedger).where(XpLedger.task_id == task_id)))
        totals = {component: sum(row.points for row in entries if row.component_type == component)
                  for component in ("BASE", "BONUS", "PENALTY")}
        assert totals == {"BASE": 60, "BONUS": 15, "PENALTY": -15}
        assert db.get(m.User, "worker").points == 160
        assert not any(row.subtask_id == children[0]["id"] for row in entries)
        assert db.get(m.Subtask, "legacy").point_policy_version == "legacy"
        assert db.get(m.Subtask, "legacy").actual_end_at is None
        before = len(entries)
    # A repeated action is rejected; the state remains financially idempotent.
    assert client.patch(f"/api/tasks/{task_id}/subtasks/{children[2]['id']}", headers=worker,
                        json={"expected_version": children[2]["version"], "action": "COMPLETE"}).status_code == 409
    with Session(engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(XpLedger).where(XpLedger.task_id == task_id)) == before
    for section in ("overview", "timeline", "subtasks", "points", "activity"):
        data = ok(client, "GET", f"/api/tasks/{task_id}/information?section={section}", owner)
        assert data["task_id"] == task_id
        assert client.get(f"/api/tasks/{task_id}/information?section={section}", headers=foreign).status_code == 404
    activity = ok(client, "GET", f"/api/tasks/{task_id}/information?section=activity&page_size=100", owner)
    assert any(row["actor"]["id"] == "worker" for row in activity["items"] if row.get("actor"))
    for headers in (owner, worker, watcher):
        inbox = ok(client, "GET", "/api/notifications/inbox", headers)
        assert inbox["unread_count"] > 0
        note_ids = [note["id"] for note in inbox["items"]]
        assert len(note_ids) == len(set(note_ids))
    assert ok(client, "GET", "/api/notifications/inbox", foreign)["unread_count"] == foreign_before
    assert published  # only committed changes reach the existing event transport
    # Reopen reverses bonus/base; removing the first child removes the next ordinal reward.
    children[1] = edit(client, worker, task_id, children[1], action="REOPEN")
    edit(client, owner, task_id, children[0], deleted=True)
    with Session(engine) as db:
        deleted = db.get(m.Subtask, children[0]["id"])
        deleted_version = deleted.version
    restored = edit(client, owner, task_id, {**children[0], "version": deleted_version}, deleted=False)
    assert restored and restored["actual_start_at"] is None
    # Parent assignment moves completed-child credits through immutable compensations.
    ok(client, "PATCH", f"/api/tasks/{task_id}", owner, json={"assigned_to_id": "watcher"})
    with Session(engine) as db:
        entries = list(db.scalars(sa.select(XpLedger).where(XpLedger.task_id == task_id)))
        signed = {key: sum(row.points for row in entries if row.user_id == key) for key in ("worker", "watcher")}
        assert signed == {"worker": 0, "watcher": 15}
        assert all(db.get(m.User, key).points == 100 + delta for key, delta in signed.items())
        assert any(row.component_type == "REVERSAL" for row in entries)
    record_property("accounting", json.dumps({"additional_components": totals, "after_reopen_and_reassignment": signed}))


def test_authenticated_activity_slots_manual_work_and_parallel_http(system):
    client, engine, _ = system
    owner, worker = login(client), login(client, "worker")
    parents = [parent(client, owner, count=0) for _ in range(6)]
    barrier = Barrier(6)

    def start(task):
        barrier.wait(timeout=30)
        return client.post(f"/api/tasks/{task['id']}/activity", headers=worker,
                           json={"action": "START", "expected_version": 0, "request_id": str(uuid.uuid4())})

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(start, parents))
    assert sorted(response.status_code for response in responses) == [200] * 5 + [409]
    frame = ok(client, "GET", "/api/tasks/activity", worker)
    assert frame["active_count"] == 5
    running = next(row for row in frame["contexts"] if row.get("status") == "RUNNING")
    paused = ok(client, "POST", f"/api/tasks/{running['task_id']}/activity", worker,
                json={"action": "PAUSE", "expected_version": running["version"], "request_id": str(uuid.uuid4())})
    assert paused["active_count"] == 4
    rejected = parents[next(i for i, response in enumerate(responses) if response.status_code == 409)]
    ok(client, "POST", f"/api/tasks/{rejected['id']}/activity", worker,
       json={"action": "START", "expected_version": 0, "request_id": str(uuid.uuid4())})
    row = next(row for row in paused["contexts"] if row.get("task_id") == running["task_id"])
    assert client.post(f"/api/tasks/{row['task_id']}/activity", headers=worker,
                       json={"action": "RESUME", "expected_version": row["version"], "request_id": str(uuid.uuid4())}).status_code == 409
    work = {"started_at": "2026-11-03T10:00:00+05:30", "ended_at": "2026-11-03T11:00:00+05:30",
            "confirmed": True, "request_id": "manual-phase7"}
    first = ok(client, "POST", f"/api/tasks/{parents[0]['id']}/work-intervals", worker, code=201, json=work)
    second = ok(client, "POST", f"/api/tasks/{parents[0]['id']}/work-intervals", worker, code=201, json=work)
    assert first["id"] == second["id"]
    overlap = client.post(f"/api/tasks/{parents[1]['id']}/work-intervals", headers=worker,
                          json={**work, "request_id": "overlap-phase7"})
    assert overlap.status_code == 409
    # A new authenticated session refetches persisted clocks, no browser state required.
    refreshed = ok(client, "GET", "/api/tasks/activity", login(client, "worker"))
    assert refreshed["active_count"] == 5
    with Session(engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(m.TaskWorkInterval)) == 1
        assert db.scalar(sa.select(sa.func.count()).select_from(m.TaskActivityContext).where(m.TaskActivityContext.status == "RUNNING")) == 5


def test_interrupted_http_reward_posting_rolls_back_status_ledger_and_inbox(system, monkeypatch):
    client, engine, published = system
    owner, worker = login(client), login(client, "worker")
    ok(client, "PATCH", "/api/config/subtask-rewards", owner, json={"enabled": True, "expected_version": 0})
    task = parent(client, owner, count=2)
    with Session(engine) as db:
        child_id = db.scalar(sa.select(m.Subtask.id).where(m.Subtask.task_id == task["id"]).order_by(m.Subtask.created_at.desc(), m.Subtask.id.desc()))
    child = next(row for row in task["subtasks"] if row["id"] == child_id)
    child = edit(client, worker, task["id"], child, action="START")
    child = edit(client, worker, task["id"], child, actual_start_at="2026-11-03T10:00:00Z",
                 actual_end_at="2026-11-03T11:00:00Z", confirm_actual_times=True)
    with Session(engine) as db:
        before = db.scalar(sa.select(sa.func.count()).select_from(m.Notification))
    emitted_before = len(published)
    real_adjust = rewards.adjust_wallet

    def interrupted(*args, **kwargs):
        real_adjust(*args, **kwargs)
        raise RuntimeError("synthetic interruption after wallet write")

    monkeypatch.setattr(rewards, "adjust_wallet", interrupted)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        edit(client, worker, task["id"], child, action="COMPLETE")
    with Session(engine) as db:
        assert db.get(m.Subtask, child_id).workflow_status == "IN_PROGRESS"
        assert db.get(m.Subtask, child_id).version == child["version"]
        assert db.get(m.User, "worker").points == 100
        assert db.scalar(sa.select(sa.func.count()).select_from(XpLedger).where(XpLedger.task_id == task["id"])) == 0
        assert db.scalar(sa.select(sa.func.count()).select_from(m.Notification)) == before
    assert len(published) == emitted_before


@pytest.mark.parametrize("role", ["owner", "admin", "manager", "user"])
def test_public_registration_cannot_join_existing_workspace_with_any_role(system, role):
    client, engine, _ = system
    with Session(engine) as db:
        tenant = str(db.get(m.User, "owner").tenant_id)
        before = db.scalar(sa.select(sa.func.count()).select_from(m.User))
    response = client.post("/api/auth/register", json={
        "name": "Synthetic enrollment probe", "email": f"registration-{role}@example.com",
        "password": PASSWORD, "role": role, "employer_id": tenant,
    })
    assert response.status_code == 403
    with Session(engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(m.User)) == before


def test_simultaneous_public_registration_provisions_workspace_only_once(system):
    client, engine, _ = system
    tenant = str(uuid.uuid4())
    barrier = Barrier(2)

    def register(index):
        barrier.wait(timeout=20)
        return client.post("/auth/register", json={"name": "Synthetic founder",
                           "email": f"founder-{index}@example.com", "password": PASSWORD,
                           "role": "owner", "employer_id": tenant})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(register, range(2)))
    assert sorted(response.status_code for response in responses) == [201, 403]
    with Session(engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(m.User).where(m.User.tenant_id == uuid.UUID(tenant))) == 1


def test_authorized_user_creation_and_login_are_preserved(system):
    client, engine, _ = system
    owner, worker = login(client), login(client, "worker")
    payload = {"name": "Authorized employee", "email": "authorized-employee@example.com", "password": PASSWORD, "role": "user"}
    assert client.post("/api/users", headers=worker, json=payload).status_code == 403
    created = ok(client, "POST", "/api/users", owner, code=201, json=payload)
    assert created["role"] == "user"
    with Session(engine) as db:
        assert db.get(m.User, created["id"]).tenant_id == db.get(m.User, "owner").tenant_id
    assert client.post("/api/auth/login", json={"email": payload["email"], "password": PASSWORD}).status_code == 200
