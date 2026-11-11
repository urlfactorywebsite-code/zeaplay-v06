"""Real task handlers and disposable SQLite; no installed app or external services."""
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.database import Base, get_db
from backend.app.dependencies import get_current_active_user
from backend.app.routers import comments, tasks
from backend.app.task_calendar import calendar_bounds


@pytest.fixture
def harness(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'tasks.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def sqlite_search_function(connection, _record):
        # SQLite uses ILIKE search, not PostgreSQL full-text search. This only
        # permits the existing generated column to be created in this fixture.
        connection.create_function("to_tsvector", 2, lambda _language, value: value, deterministic=True)

    Base.metadata.create_all(engine)
    tenant, foreign = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as db:
        for key, group, role in (("owner", tenant, models.RoleEnum.OWNER), ("peer", tenant, models.RoleEnum.USER), ("foreign", foreign, models.RoleEnum.OWNER)):
            db.add(models.User(id=key, name=key, email=f"{key}@example.com", tenant_id=group, hashed_password="fixture", role=role))
        db.flush()
        dependency = models.Task(id="dependency", title="Dependency", created_by_id="owner", due_at=datetime(2026, 10, 29, 18, 30, tzinfo=UTC).replace(tzinfo=None))
        task = models.Task(id="main", title="Main", created_by_id="owner", due_at=datetime(2026, 10, 29, 18, 29, 59, tzinfo=UTC).replace(tzinfo=None), attachments=["existing-attachment"], dependencies=[dependency])
        task.subtasks = [models.Subtask(id="sub", title="Keep subtask", completed=False)]
        db.add_all([dependency, task, models.Task(id="foreign-task", title="Foreign", created_by_id="foreign")])
        db.flush()
        db.add(models.Comment(id="comment", task_id="main", user_id="owner", content="Keep comment"))
        db.add(models.AuditEvent(id="existing-history", actor_id="owner", event_type="task.created", entity_type="task", entity_id="main", payload={"status": "TODO"}))
        db.commit()
    identity = {"id": "owner"}
    app = FastAPI()
    app.include_router(tasks.router)
    app.include_router(comments.router)

    def session():
        with Session(engine) as db:
            yield db

    def actor():
        with Session(engine) as db:
            return db.get(models.User, identity["id"])

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_active_user] = actor
    for name in ("get_cached_json", "set_cached_json", "invalidate_prefix", "trigger_n8n_event", "process_badge_event", "award_task_completion_points"):
        monkeypatch.setattr(tasks, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks.task_events, "publish_task_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks.notification_service, "create_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks.task_link_service, "handle_task_completion", lambda *args, **kwargs: None)
    monkeypatch.setattr(comments, "trigger_n8n_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(comments, "process_badge_event", lambda *args, **kwargs: None)
    with TestClient(app) as client:
        yield client, engine, identity
    engine.dispose()


def test_task_lists_and_direct_reads_do_not_cross_tenants(harness):
    client, _, _ = harness
    assert {task["id"] for task in client.get("/tasks").json()} == {"main", "dependency"}
    assert client.get("/tasks/foreign-task").status_code == 404
    assert client.patch("/tasks/foreign-task", json={"status": "IN_PROGRESS"}).status_code == 404


@pytest.mark.parametrize("path", ["/tasks/main", "/tasks/main/complete"])
def test_completion_cannot_bypass_an_unfinished_dependency(harness, path):
    client, engine, _ = harness
    response = client.patch(path, json={"status": "DONE"}) if path.endswith("main") else client.post(path)
    assert response.status_code == 409, response.text
    with Session(engine) as db:
        assert db.get(models.Task, "main").status == models.TaskStatusEnum.TODO


def test_status_change_retains_comments_attachments_subtasks_and_dependencies(harness):
    client, engine, _ = harness
    response = client.patch("/tasks/main", json={"status": "IN_PROGRESS"})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["attachments"] == ["existing-attachment"]
    assert [item["id"] for item in value["subtasks"]] == ["sub"]
    assert [item["id"] for item in value["dependencies"]] == ["dependency"]
    with Session(engine) as db:
        assert db.get(models.Comment, "comment").content == "Keep comment"
        assert db.query(models.AuditEvent).filter_by(entity_id="main", audit_schema_version=1).count() == 2
        activity = db.query(models.AuditEvent).filter_by(task_id="main", event_type="work.started").one()
        assert activity.actor_id == "owner" and activity.after["status"] == "RUNNING"
        assert db.get(models.AuditEvent, "existing-history").payload == {"status": "TODO"}


def test_peer_cannot_update_unrelated_task(harness):
    client, _, identity = harness
    identity["id"] = "peer"
    assert client.patch("/tasks/main", json={"status": "IN_PROGRESS"}).status_code == 403


@pytest.mark.parametrize("field,value", [("assigned_to_id", "foreign"), ("approver_id", "foreign"), ("follower_ids", ["foreign"]), ("dependencies", ["foreign-task"])])
def test_task_updates_reject_cross_tenant_members_and_dependencies(harness, field, value):
    client, _, _ = harness
    assert client.patch("/tasks/main", json={field: value}).status_code == 404


def test_completion_allowed_after_dependency_is_finished_and_preserves_approval(harness):
    client, engine, _ = harness
    with Session(engine) as db:
        db.get(models.Task, "dependency").status = models.TaskStatusEnum.DONE
        db.get(models.Task, "main").approval_required = True
        db.commit()
    response = client.patch("/tasks/main", json={"status": "DONE"})
    assert response.status_code == 200, response.text
    assert response.json()["approval_status"] == "pending"
    assert response.json()["completed_at"]


def test_foreign_task_comments_and_author_spoofing_are_rejected(harness):
    client, engine, _ = harness
    with Session(engine) as db:
        db.add(models.Comment(id="foreign-comment", task_id="foreign-task", user_id="foreign", content="Private"))
        db.commit()
    assert client.get("/comments/task/foreign-task").status_code == 404
    assert client.delete("/comments/foreign-comment").status_code == 404
    assert client.post("/comments", json={"task_id": "main", "user_id": "foreign", "content": "Spoof"}).status_code == 404
    assert client.get("/comments/task/main").json()[0]["content"] == "Keep comment"


def test_calendar_summary_and_day_tasks_agree_at_local_midnight(harness):
    client, _, _ = harness
    params = {"start_date": "2026-10-30", "end_date": "2026-10-30", "timezone": "Asia/Kolkata"}
    summary = client.get("/tasks/calendar/summary", params=params)
    assert summary.status_code == 200, summary.text
    assert summary.json()["days"][0]["total"] == 1
    response = client.get("/tasks/calendar/tasks", params=params)
    assert [task["id"] for task in response.json()] == ["dependency"]
    # Omitted timezone retains the legacy UTC contract.
    params.pop("timezone")
    assert client.get("/tasks/calendar/summary", params=params).json()["days"][0]["total"] == 0


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25)])
def test_calendar_dst_days_use_exclusive_next_midnight(harness, day, hours):
    client, engine, _ = harness
    lower, upper = calendar_bounds(day, day, ZoneInfo("America/New_York"))
    assert upper - lower == timedelta(hours=hours)
    with Session(engine) as db:
        for key, timestamp in (("before", lower - timedelta(microseconds=1)), ("first", lower), ("last", upper - timedelta(microseconds=1)), ("after", upper)):
            db.add(models.Task(id=key, title=key, created_by_id="owner", due_at=timestamp))
        db.commit()
    params = {"start_date": day.isoformat(), "end_date": day.isoformat(), "timezone": "America/New_York"}
    assert client.get("/tasks/calendar/summary", params=params).json()["days"][0]["total"] == 2
    assert {task["id"] for task in client.get("/tasks/calendar/tasks", params=params).json()} == {"first", "last"}


@pytest.mark.parametrize("params", [{"timezone": "Invalid/Zone"}, {"end_date": "2029-10-29"}, {"start_date": "9999-12-31", "end_date": "9999-12-31"}])
def test_invalid_calendar_queries_are_rejected(harness, params):
    client, _, _ = harness
    query = {"start_date": "2026-10-29", "end_date": "2026-10-30", **params}
    for endpoint in ("summary", "tasks"):
        assert client.get(f"/tasks/calendar/{endpoint}", params=query).status_code == 400


def test_permission_sensitive_task_caches_do_not_survive_demotion(harness, monkeypatch):
    client, engine, _ = harness
    cache = {}
    monkeypatch.setattr(tasks, "get_cached_json", cache.get)
    monkeypatch.setattr(tasks, "set_cached_json", lambda key, value, **kwargs: cache.__setitem__(key, value))
    with Session(engine) as db:
        db.add(models.Task(id="peer-task", title="Peer task", created_by_id="peer"))
        db.commit()
    assert "peer-task" in {task["id"] for task in client.get("/tasks").json()}
    with Session(engine) as db:
        db.get(models.User, "owner").role = models.RoleEnum.USER
        db.commit()
    assert "peer-task" not in {task["id"] for task in client.get("/tasks").json()}


def test_task_creation_and_offset_deadline_normalization(harness):
    client, _, _ = harness
    response = client.post("/tasks", json={"title": "Created", "assigned_to_ids": [], "due_at": "2026-10-30T00:00:00+05:30"})
    assert response.status_code == 201, response.text
    assert response.json()[0]["due_at"] == "2026-10-29T18:30:00"
    response = client.patch("/tasks/main", json={"due_at": "2026-10-30T00:00:00+05:30"})
    assert response.status_code == 200, response.text
    assert response.json()["due_at"] == "2026-10-29T18:30:00"


def test_pagination_sorting_filters_and_renamed_kanban_keep_all_tasks(harness):
    client, engine, _ = harness
    with Session(engine) as db:
        db.add(models.KanbanColumn(id="TODO", title="Renamed workflow column", order=0))
        for index in range(25):
            db.add(models.Task(id=f"bulk-{index:02}", title=f"Bulk {index:02}", created_by_id="owner", priority=models.TaskPriorityEnum.HIGH, team="Review"))
        db.commit()
    params = {"search": "Bulk", "priority": "HIGH", "team": "Review", "sort_by": "title", "sort_order": "asc", "page_size": 10}
    first = client.get("/tasks/page", params={**params, "page": 1}).json()
    second = client.get("/tasks/page", params={**params, "page": 2}).json()
    assert first["total"] == 25 and first["total_pages"] == 3
    assert [task["title"] for task in first["items"]] == [f"Bulk {index:02}" for index in range(10)]
    assert [task["title"] for task in second["items"]] == [f"Bulk {index:02}" for index in range(10, 20)]
    first = client.get("/tasks/kanban", params={"page_size": 20, "page": 1}).json()["columns"][0]
    second = client.get("/tasks/kanban", params={"page_size": 20, "page": 2}).json()["columns"][0]
    assert first["title"] == "Renamed workflow column"
    assert first["count"] == 27 and len(first["items"]) == 20 and len(second["items"]) == 7
    assert not {task["id"] for task in first["items"]} & {task["id"] for task in second["items"]}
    all_tasks = first["items"] + second["items"]
    assert next(task for task in all_tasks if task["id"] == "main")["subtasks"][0]["id"] == "sub"


def test_calendar_date_filter_uses_the_same_zone_as_grouping(harness):
    client, _, _ = harness
    params = {"start_date": "2026-10-30", "end_date": "2026-10-30", "due_date": "2026-10-30", "timezone": "Asia/Kolkata"}
    assert client.get("/tasks/calendar/summary", params=params).json()["days"][0]["total"] == 1
    assert [task["id"] for task in client.get("/tasks/calendar/tasks", params=params).json()] == ["dependency"]


@pytest.mark.parametrize("change", [{"approval_required": False}, {"approver_id": "peer"}, {"completed_at": "2020-01-01T00:00:00Z"}])
def test_assignee_cannot_disable_approval_or_forge_completion_time(harness, change):
    client, engine, identity = harness
    with Session(engine) as db:
        task = db.get(models.Task, "main")
        task.assigned_to_id = "peer"
        task.approval_required = True
        db.commit()
    identity["id"] = "peer"
    assert client.patch("/tasks/main", json=change).status_code == 403
    with Session(engine) as db:
        task = db.get(models.Task, "main")
        assert task.approval_required and task.completed_at is None


def test_deployment_cannot_bypass_required_approval(harness):
    client, engine, _ = harness
    with Session(engine) as db:
        db.get(models.Task, "dependency").status = models.TaskStatusEnum.DONE
        task = db.get(models.Task, "main")
        task.status = models.TaskStatusEnum.DONE
        task.approval_required = True
        task.approval_status = models.TaskApprovalStatusEnum.PENDING
        db.commit()
    assert client.patch("/tasks/main", json={"status": "DEPLOYED"}).status_code == 409
    with Session(engine) as db:
        db.get(models.Task, "main").approval_status = models.TaskApprovalStatusEnum.APPROVED
        db.commit()
    assert client.patch("/tasks/main", json={"status": "DEPLOYED"}).status_code == 200


def test_legacy_foreign_relationships_are_not_exposed_or_deleted(harness):
    client, engine, _ = harness
    with Session(engine) as db:
        task = db.get(models.Task, "main")
        task.assigned_to_id = "foreign"
        task.followers = [db.get(models.User, "foreign")]
        task.dependencies.append(db.get(models.Task, "foreign-task"))
        db.commit()
    value = client.get("/tasks/main").json()
    assert value["assignee"] is None and value["assigned_to_id"] is None
    assert value["follower_ids"] == []
    assert [dependency["id"] for dependency in value["dependencies"]] == ["dependency"]
    page = client.get("/tasks/page").json()
    assert next(task for task in page["items"] if task["id"] == "main")["assigned_to_id"] is None
    with Session(engine) as db:
        # Privacy filtering does not rewrite historical relationships.
        assert db.get(models.Task, "main").assigned_to_id == "foreign"
        assert db.get(models.Task, "foreign-task") is not None
        db.get(models.Task, "dependency").status = models.TaskStatusEnum.DONE
        db.get(models.Task, "foreign-task").status = models.TaskStatusEnum.DONE
        db.commit()
    assert client.patch("/tasks/main", json={"status": "DONE"}).status_code == 409
