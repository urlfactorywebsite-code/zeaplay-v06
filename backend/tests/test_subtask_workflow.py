"""Real task routes and transactional workflow repositories on disposable schemas."""
# ruff: noqa: F811 -- imported disposable pytest fixtures.

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.services import audit_logger as audit
from backend.app.services import subtasks as service
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401
from backend.tests.test_task_tabs_review import harness as api_harness  # noqa: F401

PLAN = {
    "title": "Managed child",
    "planned_start_date": "2026-11-02",
    "planned_end_date": "2026-11-03",
}


def add(client):
    existing = client.get("/tasks/main").json()["subtasks"]
    response = client.patch(
        "/tasks/main",
        json={
            "subtasks": [
                *[
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "completed": row["completed"],
                    }
                    for row in existing
                ],
                PLAN,
            ]
        },
    )
    assert response.status_code == 200, response.text
    return next(
        row
        for row in response.json()["subtasks"]
        if row["id"] not in {item["id"] for item in existing}
    )


def change(client, row, **values):
    response = client.patch(
        f"/tasks/main/subtasks/{row['id']}",
        json={"expected_version": row["version"], **values},
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["subtasks"] if item["id"] == row["id"])


def test_creation_plan_required_order_and_legacy_response(api_harness):
    client, engine, _ = api_harness
    for values in [
        {"title": "Missing"},
        {**PLAN, "planned_end_date": "2026-11-01"},
        {**PLAN, "completed": True},
    ]:
        assert (
            client.post(
                "/tasks", json={"title": "Parent", "subtasks": [values]}
            ).status_code
            == 422
        )
    row = add(client)
    assert row["managed"] and row["status"] == "TODO" and not row["completed"]
    assert row["actual_start_at"] is row["actual_end_at"] is None
    assert row["point_policy_version"] == "legacy"
    assert {"id", "title", "completed"} <= row.keys()
    with Session(engine) as db:
        assert db.get(m.Subtask, "sub").planned_start_date is None
        assert db.get(m.Subtask, "sub").workflow_version == 0


def test_manual_actual_times_status_actions_and_parent_approval_unchanged(api_harness):
    client, engine, _ = api_harness
    with Session(engine) as db:
        task = db.get(m.Task, "main")
        task.approval_required = True
        task.approval_status = m.TaskApprovalStatusEnum.PENDING
        db.commit()
    row = add(client)
    for action, expected in [
        ("START", "IN_PROGRESS"),
        ("PAUSE", "PAUSED"),
        ("RESUME", "IN_PROGRESS"),
        ("SEND_TO_TESTING", "TESTING"),
    ]:
        row = change(client, row, action=action)
        assert row["status"] == expected
        assert row["actual_start_at"] is row["actual_end_at"] is None
    response = client.patch(
        f"/tasks/main/subtasks/{row['id']}",
        json={"expected_version": row["version"], "action": "COMPLETE"},
    )
    assert response.status_code == 422
    row = change(
        client,
        row,
        actual_start_at="2026-11-02T10:00:00+05:30",
        actual_end_at="2026-11-02T11:00:00+05:30",
        confirm_actual_times=True,
    )
    assert row["actual_start_at"].startswith("2026-11-02T04:30:00")
    times = (row["actual_start_at"], row["actual_end_at"])
    row = change(client, row, action="COMPLETE")
    assert row["completed"] and row["status"] == "COMPLETED"
    assert (row["actual_start_at"], row["actual_end_at"]) == times
    with Session(engine) as db:
        assert (
            db.get(m.Task, "main").approval_status == m.TaskApprovalStatusEnum.PENDING
        )
        events = list(
            db.scalars(
                sa.select(m.AuditEvent).where(m.AuditEvent.subtask_id == row["id"])
            )
        )
        assert all(
            event.actor_id == "owner" and event.created_at.utcoffset() == timedelta(0)
            for event in events
        )
        assert any(event.payload.get("actual_times_confirmed") for event in events)
    response = client.get("/tasks/main?include_subtask_activity=true")
    assert response.status_code == 200, response.text
    history = [
        event
        for event in response.json()["subtask_activity"]
        if event["subtask_id"] == row["id"]
    ]
    assert len(history) == len(events)
    assert any(
        event["before"].get("actual_start_at") is None
        and event["after"].get("actual_start_at", "").startswith("2026-11-02T04:30:00")
        for event in history
    )
    assert (
        client.get("/tasks/foreign-task?include_subtask_activity=true").status_code
        == 404
    )


@pytest.mark.parametrize(
    "values",
    [
        {"actual_start_at": "2026-11-02T10:00:00Z"},
        {"actual_start_at": "2026-11-02T10:00:00", "confirm_actual_times": True},
        {
            "actual_start_at": "2026-11-03T10:00:00Z",
            "actual_end_at": "2026-11-02T10:00:00Z",
            "confirm_actual_times": True,
        },
        {"action": "PAUSE"},
        {"status": "COMPLETED"},
        {"planned_start_date": None},
    ],
)
def test_invalid_fields_or_transitions_are_rejected_without_mutation(
    api_harness, values
):
    client, engine, _ = api_harness
    row = add(client)
    response = client.patch(
        f"/tasks/main/subtasks/{row['id']}",
        json={"expected_version": row["version"], **values},
    )
    assert response.status_code in (409, 422), response.text
    with Session(engine) as db:
        child = db.get(m.Subtask, row["id"])
        assert child.version == 1 and child.status == "TODO"
        assert (
            db.scalar(
                sa.select(sa.func.count())
                .select_from(m.AuditEvent)
                .where(m.AuditEvent.subtask_id == child.id)
            )
            == 1
        )


def test_priority_inheritance_override_and_parent_priority_for_rewards(api_harness):
    client, _, _ = api_harness
    row = add(client)
    initial = client.get("/tasks/main").json()["priority"]
    assert row["priority_override"] is None and row["effective_priority"] == initial
    assert client.patch("/tasks/main", json={"priority": "URGENT"}).status_code == 200
    row = next(
        item
        for item in client.get("/tasks/main").json()["subtasks"]
        if item["id"] == row["id"]
    )
    assert row["effective_priority"] == "URGENT"
    row = change(client, row, priority_override="LOW")
    assert row["effective_priority"] == "LOW"
    assert client.get("/tasks/main").json()["priority"] == "URGENT"
    row = change(client, row, priority_override=None)
    assert row["effective_priority"] == "URGENT"


def test_permissions_follower_tenant_and_stale_bulk_edits(api_harness):
    client, engine, identity = api_harness
    row = add(client)
    with Session(engine) as db:
        db.get(m.Task, "main").followers = [db.get(m.User, "peer")]
        db.commit()
    for actor, expected in [("peer", 403), ("foreign", 404)]:
        identity["id"] = actor
        for change_fields in (
            {"title": "Denied"},
            {"action": "SEND_TO_TESTING"},
            {"action": "COMPLETE"},
            {"priority_override": "LOW"},
        ):
            response = client.patch(
                f"/tasks/main/subtasks/{row['id']}",
                json={**change_fields, "expected_version": 1},
            )
            assert response.status_code == expected, response.text
    identity["id"] = "owner"
    changed = change(client, row, title="Changed")
    assert (
        client.patch(
            f"/tasks/main/subtasks/{row['id']}",
            json={"title": "Stale", "expected_version": 1},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/tasks/main/subtasks/{row['id']}", json={"title": "No version"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/tasks/main",
            json={
                "subtasks": [{"id": row["id"], "title": "Bypass", "completed": True}]
            },
        ).status_code
        == 422
    )
    assert changed["version"] == 2


def test_historic_completed_without_actual_times_remains_readable(api_harness):
    client, engine, _ = api_harness
    with Session(engine) as db:
        db.get(m.Subtask, "sub").completed = True
        db.commit()
    row = client.get("/tasks/main").json()["subtasks"][0]
    assert row["completed"] and row["status"] == "COMPLETED" and not row["managed"]
    updated = change(client, row, title="Historic title")
    assert (
        updated["completed"]
        and updated["actual_start_at"] is None
        and updated["actual_end_at"] is None
    )
    row = change(client, updated, completed=False)
    row = change(
        client,
        row,
        manage=True,
        planned_start_date=PLAN["planned_start_date"],
        planned_end_date=PLAN["planned_end_date"],
    )
    assert row["managed"] and row["point_policy_version"] == "legacy"


def test_field_write_and_event_are_atomic_and_wallet_unchanged(harness, monkeypatch):
    engine, _, _ = harness
    with Session(engine) as db:
        row = service.create(db, actor_id="owner", task_id="task", data=PLAN)
        key = row.id
        db.commit()

        def fail(*args, **kwargs):
            raise RuntimeError("Synthetic audit failure")

        monkeypatch.setattr(audit, "record_task_activity", fail)
        with pytest.raises(RuntimeError, match="Synthetic audit failure"):
            service.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=key,
                data={"expected_version": 1, "title": "Rolled back"},
            )
        db.commit()
        db.expire_all()
        assert (
            db.get(m.Subtask, key).title == PLAN["title"]
            and db.get(m.Subtask, key).version == 1
        )
        assert (
            db.get(m.User, "owner").points == 100
            and db.get(m.User, "worker").points == 100
        )


def test_task_creation_and_template_assignment_use_the_same_managed_contract(
    api_harness,
):
    client, engine, _ = api_harness
    from typing import Annotated

    from fastapi import Depends

    from backend.app.database import get_db
    from backend.app.dependencies import get_current_active_user

    def live_actor(db: Annotated[Session, Depends(get_db)]):
        return db.get(m.User, "owner")

    client.app.dependency_overrides[get_current_active_user] = live_actor
    response = client.post(
        "/tasks",
        json={"title": "New parent", "assigned_to_ids": ["peer"], "subtasks": [PLAN]},
    )
    assert response.status_code == 201, response.text
    assert response.json()[0]["subtasks"][0]["managed"]
    with Session(engine) as db:
        db.add_all(
            [
                m.TaskTemplate(
                    id="own-template",
                    title="Own",
                    description="Fixture",
                    created_by_id="owner",
                    subtasks=["Template child"],
                ),
                m.TaskTemplate(
                    id="foreign-template",
                    title="Foreign",
                    description="Fixture",
                    created_by_id="foreign",
                    subtasks=["Private child"],
                ),
            ]
        )
        db.commit()
    payload = {"assignmentType": "single", "userIds": ["peer"]}
    assert (
        client.post(
            "/tasks/task-templates/own-template/assign", json=payload
        ).status_code
        == 422
    )
    payload.update(
        plannedStartDate=PLAN["planned_start_date"],
        plannedEndDate=PLAN["planned_end_date"],
    )
    assert (
        client.post(
            "/tasks/task-templates/foreign-template/assign", json=payload
        ).status_code
        == 404
    )
    response = client.post(
        "/tasks/task-templates/own-template/assign",
        json={**payload, "userIds": ["foreign"]},
    )
    assert response.status_code == 404, response.text
    response = client.post("/tasks/task-templates/own-template/assign", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()[0]["subtasks"][0]["managed"]


def test_history_cannot_be_lost_through_task_delete_or_bulk_replacement(api_harness):
    client, engine, _ = api_harness
    row = add(client)
    assert client.delete("/tasks/main").status_code == 409
    assert client.patch("/tasks/main", json={"subtasks": []}).status_code == 409
    with Session(engine) as db:
        assert db.get(m.Subtask, row["id"]) is not None


def test_legacy_edits_need_no_plan_and_explicit_bulk_enrollment_is_audited(api_harness):
    client, engine, _ = api_harness
    row = client.get("/tasks/main").json()["subtasks"][0]
    row = change(client, row, title="Legacy preserved")
    assert not row["managed"] and row["planned_start_date"] is None
    row = change(
        client,
        row,
        planned_start_date=PLAN["planned_start_date"],
        planned_end_date=PLAN["planned_end_date"],
    )
    response = client.patch(
        "/tasks/main",
        json={
            "subtasks": [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "manage": True,
                    "expected_version": row["version"],
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["subtasks"][0]["managed"]
    with Session(engine) as db:
        events = list(
            db.scalars(
                sa.select(m.AuditEvent).where(m.AuditEvent.subtask_id == row["id"])
            )
        )
        assert any(
            event.before.get("title") == "Existing"
            or event.after.get("title") == "Legacy preserved"
            for event in events
        )
        assert any(
            event.before.get("workflow_version") == 0
            and event.after.get("workflow_version") == 2
            for event in events
        )


def test_noop_and_stale_retry_do_not_repeat_side_effects(api_harness, monkeypatch):
    from backend.app.routers import tasks

    client, engine, _ = api_harness
    row = add(client)
    calls = []
    monkeypatch.setattr(
        tasks, "process_badge_event", lambda *args, **kwargs: calls.append("badge")
    )
    monkeypatch.setattr(
        tasks, "trigger_n8n_event", lambda *args, **kwargs: calls.append("external")
    )
    unchanged = change(client, row, title=row["title"])
    assert unchanged["version"] == row["version"] and calls == []
    updated = change(client, row, title="Once")
    previous_calls = list(calls)
    assert (
        client.patch(
            f"/tasks/main/subtasks/{row['id']}",
            json={
                "expected_version": row["version"],
                "title": "Once",
            },
        ).status_code
        == 409
    )
    assert calls == previous_calls and updated["version"] == 2
    with Session(engine) as db:
        assert (
            db.scalar(
                sa.select(sa.func.count())
                .select_from(m.AuditEvent)
                .where(m.AuditEvent.subtask_id == row["id"])
            )
            == 2
        )


def test_phase1_schedule_writer_cannot_bypass_manual_confirmation(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        row = service.create(db, actor_id="owner", task_id="task", data=PLAN)
        with pytest.raises(HTTPException) as exc:
            audit.update_subtask_schedule(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=row.id,
                data={"expected_version": 1, "actual_start_at": "2026-11-02T10:00:00Z"},
            )
        assert exc.value.status_code == 422
        assert row.actual_start_at is None and row.version == 1


def test_postgres_concurrent_edits_have_one_winner_and_one_audit(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL concurrent writers")
    with Session(engine) as db:
        key = service.create(db, actor_id="owner", task_id="task", data=PLAN).id
        db.commit()
    barrier = Barrier(2)

    def worker(title):
        with Session(engine) as db:
            db.get(m.Subtask, key)
            barrier.wait(timeout=10)
            try:
                service.edit(
                    db,
                    actor_id="owner",
                    task_id="task",
                    subtask_id=key,
                    data={"expected_version": 1, "title": title},
                )
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(worker, title) for title in ("First edit", "Second edit")
        ]
        assert sorted(f.result(timeout=20) for f in futures) == [200, 409]
    with Session(engine) as db:
        assert db.get(m.Subtask, key).version == 2
        assert (
            db.scalar(
                sa.select(sa.func.count())
                .select_from(m.AuditEvent)
                .where(m.AuditEvent.subtask_id == key)
            )
            == 2
        )
