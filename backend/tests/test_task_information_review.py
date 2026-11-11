"""Read-model review regressions; synthetic data and disposable schemas only."""
# ruff: noqa: F811 -- pytest fixture imports
from datetime import UTC, datetime, timedelta

from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.services import audit_logger, subtasks, task_activity
from backend.app.services import task_information as info
from backend.tests.test_subtask_rewards import activate, complete, create
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401
from backend.tests.test_task_information import read
from backend.tests.test_task_tabs_review import harness as api_harness  # noqa: F401


def test_real_managed_status_history_uses_recorded_workflow_fields(harness, monkeypatch):
    engine, _, _ = harness
    now = [datetime(2026, 11, 2, 10, tzinfo=UTC)]
    monkeypatch.setattr(m, "utc_now", lambda: now[0])
    with Session(engine) as db:
        child = create(db, 1)[0]
        for changes in [
            {"action": "START"}, {"action": "PAUSE"}, {"action": "RESUME"},
            {"actual_start_at": "2026-11-02T10:00:00Z", "actual_end_at": "2026-11-02T11:00:00Z", "confirm_actual_times": True},
            {"action": "SEND_TO_TESTING"}, {"action": "COMPLETE"}, {"action": "REOPEN"},
        ]:
            now[0] += timedelta(minutes=1)
            child = subtasks.edit(db, actor_id="owner", task_id="task", subtask_id=child.id,
                                  data={"expected_version": child.version, **changes})
        db.commit()
        rows = read(db, "timeline", child_id=child.id, size=100)["items"]
        workflow = [r for r in rows if r["channel"] == "workflow"]
        assert [r["new_status"] for r in workflow] == ["TODO", "IN_PROGRESS", "PAUSED", "IN_PROGRESS", "TESTING", "COMPLETED", "TODO"]
        assert [r["previous_status"] for r in workflow[1:]] == ["TODO", "IN_PROGRESS", "PAUSED", "IN_PROGRESS", "TESTING", "COMPLETED"]
        assert all(r["actor"]["id"] == "owner" for r in workflow)
        assert workflow[3]["duration_seconds"] == 120  # date edit is not a status change


def test_personal_switch_keeps_one_versioned_stream_and_closes_previous_child(harness, monkeypatch):
    engine, _, _ = harness
    now = [datetime(2026, 11, 2, 10, tzinfo=UTC)]
    monkeypatch.setattr(m, "utc_now", lambda: now[0])
    with Session(engine) as db:
        a, b = create(db, 2)
        now[0] += timedelta(seconds=1)
        for child, action, seconds in [(a, "START", 60), (b, "START", 120), (b, "PAUSE", 0)]:
            task_activity.command(db, actor_id="owner", task_id="task", subtask_id=child.id, action=action)
            now[0] += timedelta(seconds=seconds)
        db.commit()
        parent = [r for r in read(db, "timeline", size=100)["items"] if r["channel"] == "personal activity"]
        assert [r["duration_seconds"] for r in parent] == [60, 120, None]
        first = [r for r in read(db, "timeline", child_id=a.id)["items"] if r["channel"] == "personal activity"]
        assert [r["duration_seconds"] for r in first] == [60, None]


def test_same_instant_personal_events_order_by_recorded_version(harness, monkeypatch):
    engine, _, _ = harness
    monkeypatch.setattr(m, "utc_now", lambda: datetime(2026, 11, 2, 10, tzinfo=UTC))
    with Session(engine) as db:
        for action in ["START", "PAUSE", "RESUME", "PAUSE", "RESUME", "STOP"]:
            task_activity.command(db, actor_id="owner", task_id="task", action=action)
        db.commit()
        rows = read(db, "timeline", size=100)["items"]
        assert [r["after"]["version"] for r in rows] == [1, 2, 3, 4, 5, 6]


def test_ledger_event_resolves_its_existing_actor_and_preserves_signed_totals(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1])
        db.commit()
        ledger = [r for r in read(db, "activity", size=100)["items"] if r["source"] == "ledger"]
        assert len(ledger) == 2
        assert all(r["actor"] and r["actor"]["id"] == "owner" for r in ledger)
        assert sum(r["details"]["delta"] for r in ledger) == 45


def test_overview_skips_child_event_aggregation_and_empty_search_skips_work(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        child = create(db, 1)[0]
        task_activity.command(db, actor_id="owner", task_id="task", subtask_id=child.id, action="START")
        db.commit()
        statements = []
        def track(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.lower())
        event.listen(engine, "before_cursor_execute", track)
        try:
            read(db, "overview")
            assert not any("audit_events" in s for s in statements)
            statements.clear()
            result = read(db, "subtasks", search="does not exist")
            assert result["total"] == 0
            assert not any("task_work_intervals" in s or "task_activity_contexts" in s for s in statements)
        finally:
            event.remove(engine, "before_cursor_execute", track)


def test_legacy_non_object_json_keeps_the_event_without_crashing_or_serializing_it(api_harness):
    client, engine, _ = api_harness
    with Session(engine) as db:
        db.add(m.AuditEvent(actor_id="owner", event_type="task.updated", entity_type="task", entity_id="main", payload=["OLD_PRIVATE_PAYLOAD"]))
        db.commit()
    response = client.get("/tasks/main/information?section=activity")
    assert response.status_code == 200
    assert "OLD_PRIVATE_PAYLOAD" not in response.text


def test_cross_tenant_and_restricted_comment_projection_remain_forbidden(api_harness):
    client, engine, identity = api_harness
    with Session(engine) as db:
        task = db.get(m.Task, "main")
        task.followers.append(db.get(m.User, "peer"))
        db.commit()
    identity["id"] = "peer"
    assert client.get("/tasks/foreign-task/information?section=activity").status_code == 404
    rows = client.get("/tasks/main/information?section=activity").json()["items"]
    assert not any(r["source"] == "comment" for r in rows)


def test_main_adjustments_and_subtask_rewards_remain_distinct_per_recipient(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        children = create(db, 2)
        complete(db, children[1])
        audit = audit_logger.record_task_activity(db, actor_id="owner", task_id="task", data={"event_type": "task.points_adjusted"})
        audit_logger.append_point_adjustment(db, actor_id="owner", task_id="task", data={
            "user_id": "owner", "component_type": "ADJUSTMENT", "points": -7,
            "policy_version": "fixture-manual-v1", "idempotency_key": "fixture-main-adjustment",
            "activity_event_id": audit.id, "reason": "Synthetic main-only adjustment",
        })
        db.commit()
        points = read(db, "points")["points"]
        assert points["main_earned"] is None and points["total_net_earned"] is None
        assert points["main_recorded_net"] == -7 and points["subtask_earned"] == 45
        assert points["verified_net_earned"] == 38
        assert points["main_recorded_components"]["ADJUSTMENT"] == -7
        assert points["subtask_components"]["ADJUSTMENT"] == 0
        recipients = {r["id"]: r for r in points["recipients"]}
        assert recipients["owner"]["main_net"] == -7 and recipients["owner"]["subtask_net"] == 0
        assert recipients["worker"]["main_net"] == 0 and recipients["worker"]["subtask_net"] == 45


def test_restricted_legacy_history_does_not_infer_time_across_hidden_statuses(api_harness):
    client, engine, identity = api_harness
    at = datetime(2026, 11, 2, 10, tzinfo=UTC)
    with Session(engine) as db:
        task = db.get(m.Task, "main")
        task.assigned_to_id = "peer"
        for i, (old, new, target) in enumerate([
            ("TODO", "IN_PROGRESS", "peer"), ("IN_PROGRESS", "ON_HOLD", "owner"),
            ("ON_HOLD", "IN_PROGRESS", "owner"), ("IN_PROGRESS", "DONE", "peer"),
        ]):
            db.add(m.AuditLog(id=f"partial-{i}", actor_id="owner", target_user_id=target,
                              action="TASK_UPDATED", category=m.AuditLogCategoryEnum.TASK,
                              entity_type="task", entity_id="main", before={"status": old}, after={"status": new},
                              created_at=at + timedelta(minutes=i)))
        db.commit()
    identity["id"] = "peer"
    rows = client.get("/tasks/main/information?section=timeline").json()["items"]
    assert len(rows) == 2 and all(r["duration_seconds"] is None for r in rows)


def test_unknown_legacy_completed_value_is_not_cast_to_boolean_or_invented_as_status(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        audit_logger.record_task_activity(db, actor_id="owner", task_id="task", data={
            "event_type": "task.updated", "after": {"completed": "unrecognized legacy value"},
        })
        db.commit()
        assert read(db, "timeline")["items"] == []


def test_capacity_and_effective_priority_use_the_database_snapshot_not_a_cached_parent(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        children = create(db, 2)
        db.commit()
        parent = db.get(m.Task, "task")
        assert parent.priority == m.TaskPriorityEnum.HIGH
        with Session(engine) as writer:
            writer.get(m.Task, "task").priority = m.TaskPriorityEnum.URGENT
            writer.commit()
        summary = info.point_summary(db, parent, db.get(m.User, "owner").tenant_id)
        assert summary["main_base_value"] == 45 and summary["subtask_available_base"] == 45
        rows = read(db, "subtasks")["items"]
        selected = next(row for row in rows if row["id"] == children[1].id)
        assert selected["effective_priority"] == "URGENT" and selected["additional_base_value"] == 45
