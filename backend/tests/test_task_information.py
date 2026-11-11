"""Phase 5 reads against real handlers and owned disposable databases only."""
# ruff: noqa: F811 -- imported pytest fixtures
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.services import audit_logger, subtasks, task_activity
from backend.app.services import subtask_rewards as rewards
from backend.app.services import task_information as info
from backend.app.tickets.models import XpLedger
from backend.tests.test_subtask_rewards import activate, complete, create
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401
from backend.tests.test_task_tabs_review import harness as api_harness  # noqa: F401


def read(db, section, **kwargs):
    return info.read(db, task_id="task", who=db.get(m.User, "owner"), section=section, **kwargs)


@pytest.mark.parametrize("section", sorted(info.SECTIONS))
def test_http_contract_legacy_and_no_store(api_harness, section):
    client, engine, _ = api_harness
    with Session(engine) as db:
        before = db.get(m.Task, "main").updated_at
        points = db.get(m.User, "owner").points
        audit_count = db.scalar(select(func.count()).select_from(m.AuditEvent))
    response = client.get(f"/tasks/main/information?section={section}")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["section"] == section and data["task_id"] == "main"
    assert data["as_of"].endswith("Z") and data["created_at"].endswith("Z")
    if section == "points":
        assert data["points"]["main_earned"] is None
        assert data["points"]["total_net_earned"] is None
        assert data["points"]["verified_net_earned"] == 0
    if section == "subtasks":
        assert data["items"][0]["planned_start_date"] is None
        assert data["items"][0]["additional_base_value"] == 0
    with Session(engine) as db:
        assert db.get(m.Task, "main").updated_at == before
        assert db.get(m.User, "owner").points == points
        assert db.scalar(select(func.count()).select_from(m.AuditEvent)) == audit_count


@pytest.mark.parametrize("section", sorted(info.SECTIONS))
def test_every_section_enforces_live_tenant_and_task_role(api_harness, section):
    client, engine, identity = api_harness
    assert client.get(f"/tasks/foreign-task/information?section={section}").status_code == 404
    identity["id"] = "peer"
    assert client.get(f"/tasks/main/information?section={section}").status_code == 403
    with Session(engine) as db:
        task = db.get(m.Task, "main")
        task.followers.append(db.get(m.User, "peer"))
        db.commit()
    assert client.get(f"/tasks/main/information?section={section}").status_code == 200
    with Session(engine) as db:
        db.get(m.User, "peer").status = m.UserStatusEnum.DEACTIVATED
        db.commit()
    assert client.get(f"/tasks/main/information?section={section}").status_code == 403


def test_parameter_limits_child_parent_scope_and_unknown_task(api_harness):
    client, engine, _ = api_harness
    for suffix in ["section=wrong", "page=0", "page_size=101", "search=" + "x" * 201]:
        assert client.get("/tasks/main/information?" + suffix).status_code == 422
    with Session(engine) as db:
        db.add(m.Subtask(id="foreign-child", task_id="foreign-task", title="Private child"))
        db.commit()
    assert client.get("/tasks/main/information?section=timeline&subtask_id=foreign-child").status_code == 404
    assert client.get("/tasks/missing/information").status_code == 404


def test_real_legacy_status_logs_paginate_chronologically_without_fake_transitions(api_harness):
    client, engine, _ = api_harness
    at = datetime(2026, 11, 2, 12, tzinfo=UTC)
    with Session(engine) as db:
        for index, (old, new) in enumerate([("TODO", "IN_PROGRESS"), ("IN_PROGRESS", "ON_HOLD"), ("ON_HOLD", "IN_PROGRESS"), ("IN_PROGRESS", "DONE")]):
            db.add(m.AuditLog(id=f"log-{index}", actor_id="owner", action="TASK_UPDATED", category=m.AuditLogCategoryEnum.TASK,
                              entity_type="task", entity_id="main", before={"status": old}, after={"status": new},
                              created_at=at + timedelta(minutes=index), metadata_payload={"secret": "PRIVATE_CONFIG"}, ip_address="PRIVATE_ADDRESS"))
        db.commit()
    first = client.get("/tasks/main/information?section=timeline&page_size=2").json()
    second = client.get("/tasks/main/information?section=timeline&page_size=2&page=2").json()
    assert first["total"] == 4 and second["total"] == 4
    assert [r["new_status"] for r in first["items"] + second["items"]] == ["IN_PROGRESS", "ON_HOLD", "IN_PROGRESS", "DONE"]
    assert first["items"][1]["duration_seconds"] == 60  # next record is on another page
    assert second["items"][-1]["duration_seconds"] is None
    assert first["items"][0]["actor"]["name"] == "owner"
    assert "PRIVATE_" not in client.get("/tasks/main/information?section=activity").text


def test_empty_history_does_not_invent_created_transition(api_harness):
    client, _, _ = api_harness
    data = client.get("/tasks/dependency/information?section=timeline").json()
    assert data["created_at"] and data["items"] == [] and data["total"] == 0


def test_large_hierarchy_search_pages_and_bounded_query_count(api_harness):
    client, engine, _ = api_harness
    with Session(engine) as db:
        db.add_all(m.Subtask(id=f"child-{i:04}", task_id="main", title=f"Child {i:04}") for i in range(1000))
        db.add(m.Subtask(id="literal", task_id="main", title="100% _ready"))
        db.commit()
    statements = []
    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", count)
    try:
        data = client.get("/tasks/main/information?section=subtasks&page_size=100&page=5").json()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert data["total"] == 1002 and len(data["items"]) == 100
    assert len(statements) <= 16, len(statements)
    assert all(s.lstrip().upper().startswith(("SELECT", "PRAGMA")) for s in statements)
    literal = client.get("/tasks/main/information?section=subtasks&search=%25%20_").json()
    assert [r["id"] for r in literal["items"]] == ["literal"]
    ids = [r["id"] for r in data["items"]]
    assert ids == [r["id"] for r in client.get("/tasks/main/information?section=subtasks&page_size=100&page=5").json()["items"]]


@pytest.mark.parametrize("count", [1, 2, 3, 5, 100])
def test_authoritative_points_and_capacity_match_existing_engine(harness, count):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, count)
        db.commit()
        for row in reversed(rows):
            complete(db, row)
        db.commit()
        points = read(db, "points")["points"]
        assert points["main_base_value"] == 30
        assert points["subtask_base_capacity"] == max(0, count - 1) * 30
        assert points["subtask_available_base"] == 0
        assert points["components"]["BASE"] == max(0, count - 1) * 30
        assert points["components"]["BONUS"] == max(0, count - 1) * 15
        assert points["verified_net_earned"] == rewards.summary(db.get(m.Task, "task"))["earned"]
        assert points["verified_net_earned"] == sum(r["net"] for r in points["recipients"])
        assert points["main_earned"] is None and points["total_net_earned"] is None


def test_reversals_penalties_reassignment_and_deleted_history(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 3)
        complete(db, rows[1])
        complete(db, rows[2], end="2026-11-03T01:00:00Z")
        db.commit()
        before = read(db, "points")["points"]
        assert before["components"]["BASE"] == 60
        assert before["components"]["BONUS"] == 15 and before["components"]["PENALTY"] == -15
        assert before["verified_net_earned"] == 60
        subtasks.edit(db, actor_id="owner", task_id="task", subtask_id=rows[0].id,
                      data={"expected_version": rows[0].version, "deleted": True})
        db.commit()
        points = read(db, "points")["points"]
        assert points["components"]["REVERSAL"] == -45
        assert points["verified_net_earned"] == 15
        # Reassign using the canonical reward scope, just as parent mutation does.
        rewards.lock_scope(db, "task")
        db.get(m.Task, "task").assigned_to_id = "owner"
        rewards.reconcile(db, actor_id="owner", task_id="task")
        db.commit()
        points = read(db, "points")["points"]
        assert points["verified_net_earned"] == 15
        assert {r["id"]: r["net"] for r in points["recipients"]} == {"worker": 0, "owner": 15}
        children = read(db, "subtasks")["items"]
        assert next(c for c in children if c["id"] == rows[0].id)["deleted_at"]
        assert sum(c["earned"] or 0 for c in children) == 15
        feed = read(db, "activity", size=100)["items"]
        assert any(r["event_type"] == "points.reversal" for r in feed)
        # No reads add ledger entries or recalculate historic main-task rewards.
        ledger_count = db.scalar(select(func.count()).select_from(XpLedger))
        read(db, "points")
        assert db.scalar(select(func.count()).select_from(XpLedger)) == ledger_count


def test_child_priority_inherits_live_parent_and_audit_never_leaks_foreign(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        subtasks.edit(db, actor_id="owner", task_id="task", subtask_id=rows[1].id,
                      data={"expected_version": rows[1].version, "priority_override": "LOW"})
        db.get(m.Task, "task").priority = m.TaskPriorityEnum.URGENT
        db.add(m.AuditEvent(actor_id="foreign", event_type="task.updated", entity_type="task", entity_id="task", payload={"title": "FOREIGN_SECRET"}))
        db.commit()
        children = {r["id"]: r for r in read(db, "subtasks")["items"]}
        assert children[rows[0].id]["effective_priority"] == "URGENT"
        assert children[rows[1].id]["effective_priority"] == "LOW"
        assert children[rows[1].id]["additional_base_value"] == 45
        assert "FOREIGN_SECRET" not in str(read(db, "activity"))
        with pytest.raises(HTTPException) as error:
            info.read(db, task_id="other", who=db.get(m.User, "owner"), section="points")
        assert error.value.status_code == 404


def test_confirmed_productive_work_deduplicates_across_parent_scopes(harness, monkeypatch):
    engine, _, _ = harness
    at = datetime(2026, 11, 2, 10, tzinfo=UTC)
    with Session(engine) as db:
        db.add(m.Task(id="parallel", title="PRIVATE_OTHER_TASK", created_by_id="owner"))
        db.commit()
        for index, (task_id, start, end) in enumerate([("parallel", 0, 60), ("task", 30, 90)]):
            monkeypatch.setattr(m, "utc_now", lambda i=index: at + timedelta(seconds=i))
            # Existing low-level imported intervals may overlap. All readers must
            # retain Phase 4's global per-person allocation, even on this task tab.
            audit_logger.record_manual_work(db, actor_id="owner", task_id=task_id,
                data={"started_at": at + timedelta(minutes=start), "ended_at": at + timedelta(minutes=end),
                      "request_id": f"overlap-{index}", "note": "Confirmed note"})
        db.commit()
        data = read(db, "overview")["overview"]
        assert data["productive_seconds"] == 1800  # 30 minutes belongs to earlier other-task log
        assert "PRIVATE_OTHER_TASK" not in str(data)
        feed = read(db, "activity")["items"]
        assert any(r["after"] and r["after"].get("note") == "Confirmed note" for r in feed)


def test_personal_pause_resume_switch_history_and_elapsed_never_sets_actual_times(harness, monkeypatch):
    engine, _, _ = harness
    at = datetime(2026, 11, 2, 10, tzinfo=UTC)
    clock = [at]
    monkeypatch.setattr(m, "utc_now", lambda: clock[0])
    with Session(engine) as db:
        rows = create(db, 2)  # workflow managed; reward activation independent
        db.commit()
        clock[0] += timedelta(seconds=1)  # creation and Start are distinct instants
        task_activity.command(db, actor_id="owner", task_id="task", subtask_id=rows[0].id, action="START")
        clock[0] += timedelta(minutes=10)
        task_activity.command(db, actor_id="owner", task_id="task", subtask_id=rows[0].id, action="PAUSE")
        clock[0] += timedelta(minutes=5)
        task_activity.command(db, actor_id="owner", task_id="task", subtask_id=rows[0].id, action="RESUME")
        clock[0] += timedelta(minutes=2)
        task_activity.command(db, actor_id="owner", task_id="task", subtask_id=rows[1].id, action="START")
        clock[0] += timedelta(minutes=3)
        db.commit()
        parent_seconds, children = info.elapsed(db, db.get(m.Task, "task"), db.get(m.User, "owner").tenant_id, clock[0])
        assert parent_seconds == 900 and children[rows[0].id] == 720 and children[rows[1].id] == 180
        first = read(db, "timeline", child_id=rows[0].id)["items"]
        assert [row["event_type"] for row in first] == ["subtask.created", "work.started", "work.paused", "work.resumed", "work.switched"]
        assert all(db.get(m.Subtask, row.id).actual_start_at is None and db.get(m.Subtask, row.id).actual_end_at is None for row in rows)


def test_large_immutable_history_uses_bounded_queries_and_deterministic_ties(harness):
    engine, _, _ = harness
    at = datetime(2026, 11, 2, 10, tzinfo=UTC)
    with Session(engine) as db:
        tenant = db.get(m.User, "owner").tenant_id
        db.add_all(m.AuditEvent(
            id=f"event-{i:04}", audit_schema_version=2, tenant_id=tenant, task_id="task",
            actor_id="owner", entity_type="task", entity_id="task", event_type="task.updated",
            before={"status": "TODO"}, after={"status": "IN_PROGRESS"},
            payload={"private_configuration": "MUST_NOT_LEAVE_SERVER"}, created_at=at,
        ) for i in range(500))
        db.commit()
        statements = []
        def count(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", count)
        try:
            data = read(db, "timeline", page=4, size=100)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert data["total"] == 500 and len(data["items"]) == 100
        assert len(statements) <= 12
        assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
        assert data["items"][0]["id"] == "audit_event:event-0300"
        assert data["items"][-1]["id"] == "audit_event:event-0399"
        assert "MUST_NOT_LEAVE_SERVER" not in str(read(db, "activity", size=100))


def test_comments_and_legacy_audits_keep_their_own_record_permissions(api_harness):
    client, engine, identity = api_harness
    with Session(engine) as db:
        task = db.get(m.Task, "main")
        task.followers.append(db.get(m.User, "peer"))
        db.add(m.AuditLog(id="restricted-log", actor_id="owner", target_user_id="owner",
                         action="TASK_UPDATED", category=m.AuditLogCategoryEnum.TASK,
                         entity_type="task", entity_id="main", before={"status": "TODO"}, after={"status": "IN_PROGRESS"}))
        db.commit()
    owner = client.get("/tasks/main/information?section=activity").json()
    assert any(r["source"] == "comment" for r in owner["items"])
    assert any(r["id"] == "audit_log:restricted-log" for r in owner["items"])
    identity["id"] = "peer"
    watcher = client.get("/tasks/main/information?section=activity").json()
    assert not any(r["source"] in {"comment", "audit_log"} for r in watcher["items"])
    assert watcher["total"] == owner["total"] - 2
    assert client.get("/tasks/main/information?section=timeline").json()["total"] == 0
    with Session(engine) as db:
        db.get(m.Task, "main").assigned_to_id = "peer"
        db.commit()
    assigned = client.get("/tasks/main/information?section=activity").json()
    assert any(r["source"] == "comment" for r in assigned["items"])
    assert not any(r["source"] == "audit_log" for r in assigned["items"])


def test_shared_audit_does_not_disclose_another_users_private_work_note(harness):
    engine, _, _ = harness
    at = datetime(2026, 11, 2, 10, tzinfo=UTC)
    with Session(engine) as db:
        audit_logger.record_manual_work(db, actor_id="owner", task_id="task", data={
            "started_at": at, "ended_at": at + timedelta(hours=1),
            "request_id": "private-work-note", "note": "OWN_WORK_NOTE",
        })
        db.commit()
        assert "OWN_WORK_NOTE" in str(read(db, "activity"))
        watcher = info.read(db, task_id="task", who=db.get(m.User, "watcher"), section="activity")
        assert "OWN_WORK_NOTE" not in str(watcher)
        assert any(row["event_type"] == "task.manual_work_logged" for row in watcher["items"])


def test_legacy_foreign_assignee_references_are_redacted_without_losing_the_event(api_harness):
    client, engine, _ = api_harness
    with Session(engine) as db:
        db.add(m.AuditLog(id="old-assignment", actor_id="owner", action="TASK_UPDATED",
                         category=m.AuditLogCategoryEnum.TASK, entity_type="task", entity_id="main",
                         before={"assigned_to_id": "foreign", "follower_ids": ["foreign", "owner"]},
                         after={"assigned_to_id": "owner"}))
        db.commit()
    rows = client.get("/tasks/main/information?section=activity").json()["items"]
    row = next(r for r in rows if r["id"] == "audit_log:old-assignment")
    assert row["before"] == {"assigned_to_id": "[restricted user]", "follower_ids": ["[restricted user]", "owner"]}
    assert row["after"]["assigned_to_id"] == "owner"
