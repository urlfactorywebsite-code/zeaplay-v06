"""Reward accounting adversarial checks; only owned synthetic databases."""

# ruff: noqa: F811 -- pytest imports disposable fixtures.
import importlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.services import audit_logger, points_table, subtasks
from backend.app.services import subtask_rewards as rewards
from backend.app.tickets.models import XpLedger
from backend.tests.test_subtask_rewards import activate, complete, create, ledger
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401
from backend.tests.test_task_tabs_review import harness as api_harness  # noqa: F401


def assert_books(db, expected, *, opening=None):
    """Independent SQL sums, including every signed reversal, per scope/user."""
    totals = dict(
        db.execute(
            sa.select(XpLedger.user_id, sa.func.sum(XpLedger.points))
            .where(XpLedger.ref_type == rewards.POLICY, XpLedger.task_id == "task")
            .group_by(XpLedger.user_id)
        ).all()
    )
    assert {user: value for user, value in totals.items() if value} == {
        user: value for user, value in expected.items() if value
    }
    assert rewards.summary(db.get(m.Task, "task"))["earned"] == sum(expected.values())
    for user, initial in (opening or {"worker": 100, "watcher": 100}).items():
        db.refresh(db.get(m.User, user))
        assert db.get(m.User, user).points == initial + expected.get(user, 0)


def test_config_read_does_not_commit_a_financial_transaction(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        db.get(m.Task, "task").title = "Must roll back"
        points_table.resolve_task_points(
            db, team="Other", priority=m.TaskPriorityEnum.HIGH
        )
        db.rollback()
    with Session(engine) as db:
        assert db.get(m.Task, "task").title == "Preserve"
        assert db.get(m.PointsTableConfig, 1) is None


def test_generic_adjustment_cannot_bypass_reward_wallet(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        event = audit_logger.record_task_activity(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=rows[1].id,
            data={"event_type": "subtask.updated"},
        )
        with pytest.raises(HTTPException) as failure:
            audit_logger.append_point_adjustment(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=rows[1].id,
                data={
                    "user_id": "worker",
                    "component_type": "BONUS",
                    "points": 999,
                    "policy_version": rewards.POLICY,
                    "idempotency_key": "forged-policy-credit",
                    "activity_event_id": event.id,
                    "reason": "Must use the reward engine",
                },
            )
        assert failure.value.status_code == 409
        assert ledger(db) == []


def test_database_refuses_reversal_of_reversal_and_policy_alias(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1])
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=rows[1].id,
            data={"expected_version": rows[1].version, "action": "REOPEN"},
        )
        db.commit()
        reversal = next(row for row in ledger(db) if row.reversal_of_id)
        values = {
            c.name: getattr(reversal, c.name)
            for c in XpLedger.__table__.columns
            if c.name != "id"
        }
        for changes in (
            {"points": -reversal.points, "reversal_of_id": reversal.id},
            {
                "ref_type": None,
                "points": 999,
                "component_type": "ADJUSTMENT",
                "reversal_of_id": None,
            },
        ):
            with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
                db.add(
                    XpLedger(**{**values, **changes, "idempotency_key": str(changes)})
                )
                db.flush()
        assert_books(db, {})


@pytest.mark.parametrize("already_posted", [False, True])
def test_postgres_duplicate_workers_are_state_idempotent(harness, already_posted):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency required")
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        if already_posted:
            complete(db, rows[1])
        else:
            # Synthetic pending-worker state: valid managed completion and its
            # activity are committed, but no worker has posted this scope yet.
            row = rows[1]
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=row.id,
                data={"expected_version": row.version, "action": "START"},
            )
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=row.id,
                data={
                    "expected_version": row.version,
                    "actual_start_at": "2026-11-02T00:00:00Z",
                    "actual_end_at": "2026-11-02T12:00:00Z",
                    "confirm_actual_times": True,
                },
            )
            db.execute(
                sa.update(m.Subtask)
                .where(m.Subtask.id == row.id)
                .values(
                    workflow_status="COMPLETED", completed=True, version=row.version + 1
                )
            )
            audit_logger.record_task_activity(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=row.id,
                data={"event_type": "subtask.status_changed"},
            )
        db.commit()
    gate = Barrier(4)

    def worker():
        with Session(engine) as db:
            gate.wait(timeout=10)
            rewards.reconcile(db, actor_id="owner", task_id="task")
            db.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker) for _ in range(4)]
        for future in futures:
            future.result(timeout=30)
    with Session(engine) as db:
        assert len(ledger(db)) == 2
        assert_books(db, {"worker": 45})


def test_lifecycle_signed_totals_and_negative_wallet(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 3)
        complete(db, rows[2], "2026-11-03T00:00:00Z")
        complete(db, rows[1])
        complete(db, rows[0])
        db.commit()
        assert_books(db, {"worker": 60})  # base60 + bonus15 - penalty15

        def edit(row, **changes):
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=row.id,
                data={"expected_version": row.version, **changes},
            )
            db.commit()

        edit(rows[0], deleted=True)
        assert_books(db, {"worker": 15})
        edit(rows[0], deleted=False)
        assert_books(db, {"worker": 60})
        edit(rows[2], deleted=True)
        assert_books(db, {"worker": 45})
        edit(rows[2], deleted=False)
        assert_books(db, {"worker": 60})
        edit(rows[2], action="REOPEN")
        assert_books(db, {"worker": 45})
        # Prior legitimate spending can leave a negative wallet on reversal.
        from backend.app.services.wallet import adjust

        adjust(db, db.get(m.User, "worker"), -140)
        db.commit()
        edit(rows[1], action="REOPEN")
        assert_books(db, {}, opening={"worker": -40, "watcher": 100})
        assert db.get(m.User, "worker").points == -40
        for _ in range(3):
            rewards.reconcile(db, actor_id="owner", task_id="task")
        db.commit()
        assert_books(db, {}, opening={"worker": -40, "watcher": 100})


@pytest.mark.parametrize(
    "failure_stage", ["before_wallet", "after_wallet", "second_recipient"]
)
def test_interrupted_parent_reprice_rolls_back_even_when_caller_catches(
    harness, monkeypatch, failure_stage
):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1])
        db.commit()
        before = [(row.id, row.points) for row in ledger(db)]
        original_adjust = rewards.adjust_wallet
        calls = []

        def interrupt(db, user, delta):
            calls.append(user.id)
            if failure_stage == "before_wallet":
                raise RuntimeError("Interrupted payout")
            result = original_adjust(db, user, delta)
            if failure_stage == "after_wallet" or len(calls) == 2:
                raise RuntimeError("Interrupted payout")
            return result

        monkeypatch.setattr(rewards, "adjust_wallet", interrupt)
        rewards.lock_scope(db, "task")
        task = db.get(m.Task, "task")
        task.priority = m.TaskPriorityEnum.URGENT
        task.assigned_to_id = "watcher"
        with pytest.raises(RuntimeError, match="Interrupted payout"):
            rewards.reconcile(db, actor_id="owner", task_id="task")
        db.commit()
        db.expire_all()
        assert (
            task.priority == m.TaskPriorityEnum.HIGH and task.assigned_to_id == "worker"
        )
        assert [(row.id, row.points) for row in ledger(db)] == before
        assert_books(db, {"worker": 45})


def test_duplicate_same_subtask_completion_with_current_version(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        row = create(db, 2)[1]
        complete(db, row)
        db.commit()
        for _ in range(2):
            with pytest.raises(HTTPException) as error:
                subtasks.edit(
                    db,
                    actor_id="owner",
                    task_id="task",
                    subtask_id=row.id,
                    data={"expected_version": row.version, "action": "COMPLETE"},
                )
            assert error.value.status_code == 409
        rewards.reconcile(db, actor_id="owner", task_id="task")
        db.commit()
        assert len(ledger(db)) == 2
        assert_books(db, {"worker": 45})


def test_postgres_same_subtask_simultaneous_completion(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency required")
    with Session(engine) as db:
        activate(db)
        row = create(db, 2)[1]
        complete(db, row)
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=row.id,
            data={"expected_version": row.version, "action": "REOPEN"},
        )
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=row.id,
            data={"expected_version": row.version, "action": "START"},
        )
        db.commit()
        key, version = row.id, row.version
    gate = Barrier(2)

    def finish():
        with Session(engine) as db:
            # Preload stale ORM state before the competing request commits.
            db.get(m.Subtask, key)
            gate.wait(timeout=10)
            try:
                subtasks.edit(
                    db,
                    actor_id="owner",
                    task_id="task",
                    subtask_id=key,
                    data={"expected_version": version, "action": "COMPLETE"},
                )
                db.commit()
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(finish) for _ in range(2)]
        assert sorted(f.result(timeout=30) for f in futures) == [200, 409]
    with Session(engine) as db:
        assert len(ledger(db)) == 6  # initial2 + reversal2 + exactly one new pair
        assert_books(db, {"worker": 45})


def test_forward_migration_preserves_all_rows_and_refuses_destructive_rollback(
    harness, monkeypatch
):
    engine, _, _ = harness
    module = importlib.import_module(
        "backend.alembic.versions.h8d0f2a4c6e8_reward_accounting_guards"
    )
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1])
        db.commit()
    with engine.begin() as connection:
        from backend.app.services.subtask_reward_guards_v4 import guard_specs
        # Rehearse the actual v3 -> v4 transition, not just adoption over a fresh
        # model install that already has v4 guards. v1-v3 remain installed.
        for suffix, table, _, _ in guard_specs():
            on_table = f" ON {table}" if engine.dialect.name == "postgresql" else ""
            connection.exec_driver_sql("DROP TRIGGER zea_v4_" + suffix + on_table)
        tables = [
            m.User.__table__,
            m.Task.__table__,
            m.Subtask.__table__,
            m.AuditEvent.__table__,
            XpLedger.__table__,
        ]
        before = {t.name: connection.execute(sa.select(t)).all() for t in tables}
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        module.upgrade()
        module.upgrade()
        assert {
            t.name: connection.execute(sa.select(t)).all() for t in tables
        } == before
        with pytest.raises(RuntimeError, match="Retain"):
            module.downgrade()


def test_migration_refuses_existing_alias_without_rewriting_history(
    harness, monkeypatch
):
    engine, _, _ = harness
    module = importlib.import_module(
        "backend.alembic.versions.h8d0f2a4c6e8_reward_accounting_guards"
    )
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1])
        db.commit()
        original = ledger(db)[0]
        values = {
            c.name: getattr(original, c.name)
            for c in XpLedger.__table__.columns
            if c.name != "id"
        }
    with engine.begin() as connection:
        suffix = " ON xp_ledger" if engine.dialect.name == "postgresql" else ""
        connection.exec_driver_sql("DROP TRIGGER zea_v4_ledger_accounting" + suffix)
        connection.execute(
            XpLedger.__table__.insert().values(
                **{**values, "ref_type": None, "idempotency_key": "old-unsafe-alias"}
            )
        )
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        with pytest.raises(RuntimeError, match="manual review"):
            module.upgrade()
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(XpLedger)
            ).scalar_one()
            == 3
        )
        assert (
            connection.execute(
                sa.select(m.User.points).where(m.User.id == "worker")
            ).scalar_one()
            == 145
        )


def test_tenant_assignment_and_unauthorized_workers_fail_closed(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        create(db, 2)
        db.commit()
        with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
            db.execute(
                sa.update(m.Task)
                .where(m.Task.id == "task")
                .values(assigned_to_id="foreign")
            )
        # A still-unpaid assignee has no ledger references yet; policy ownership
        # must nevertheless prevent moving that recipient into another tenant.
        with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
            db.execute(
                sa.update(m.User)
                .where(m.User.id == "worker")
                .values(tenant_id=db.get(m.User, "foreign").tenant_id)
            )
        for actor, status in [("foreign", 404), ("watcher", 403)]:
            with pytest.raises(HTTPException) as error:
                rewards.reconcile(db, actor_id=actor, task_id="task")
            assert error.value.status_code == status
        db.get(m.User, "owner").status = m.UserStatusEnum.DEACTIVATED
        db.commit()
        with pytest.raises(HTTPException) as error:
            rewards.reconcile(db, actor_id="owner", task_id="task")
        assert error.value.status_code == 403
        assert ledger(db) == []


def test_claim_reads_and_refunds_are_tenant_and_role_scoped(harness, monkeypatch):
    from backend.app.services import rewards as claims

    engine, _, _ = harness
    monkeypatch.setattr(
        claims.notification_service, "create_notification", lambda *a, **kw: None
    )
    with Session(engine) as db:
        db.add(
            m.Reward(
                id="reward",
                title="Fixture",
                description="Fixture",
                xp_required=40,
                auto_redeem=False,
            )
        )
        db.commit()
        claim = claims.claim_reward(
            db, reward_id="reward", user=db.get(m.User, "worker")
        )
        assert claims.list_claims(db, actor=db.get(m.User, "foreign")).total == 0
        assert claims.list_claims(db, actor=db.get(m.User, "owner")).total == 1
        assert claims.list_logs(db, actor=db.get(m.User, "foreign")).total == 0
        assert claims.list_logs(db, actor=db.get(m.User, "owner")).total == 1
        for actor, status in [("foreign", 404), ("watcher", 403)]:
            for resolve in (claims.approve_claim, claims.reject_claim):
                with pytest.raises(HTTPException) as error:
                    resolve(db, claim_id=claim.id, actor=db.get(m.User, actor))
                assert error.value.status_code == status
        assert db.get(m.User, "worker").points == 60
        claims.reject_claim(db, claim_id=claim.id, actor=db.get(m.User, "owner"))
        assert db.get(m.User, "worker").points == 100


def test_postgres_claim_and_refund_each_happen_once(harness, monkeypatch):
    from backend.app.services import rewards as claims

    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency required")
    monkeypatch.setattr(
        claims.notification_service, "create_notification", lambda *a, **kw: None
    )
    with Session(engine) as db:
        db.add(
            m.Reward(
                id="reward",
                title="Fixture",
                description="Fixture",
                xp_required=40,
                auto_redeem=False,
            )
        )
        db.commit()
    gate = Barrier(2)

    def run(kind, claim_id=None):
        with Session(engine) as db:
            actor = db.get(m.User, "worker" if kind == "claim" else "owner")
            gate.wait(timeout=10)
            try:
                if kind == "claim":
                    result = claims.claim_reward(db, reward_id="reward", user=actor)
                    return (200, result.id)
                claims.reject_claim(db, claim_id=claim_id, actor=actor)
                return (200, claim_id)
            except HTTPException as error:
                db.rollback()
                return (error.status_code, claim_id)

    def pair(kind, claim_id=None):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, kind, claim_id) for _ in range(2)]
            return [f.result(timeout=30) for f in futures]

    outcomes = pair("claim")
    assert sorted(status for status, _ in outcomes) == [200, 409]
    claim_id = next(key for status, key in outcomes if status == 200)
    with Session(engine) as db:
        assert db.get(m.User, "worker").points == 60
        assert db.scalar(sa.select(sa.func.count()).select_from(m.RewardClaim)) == 1
    assert sorted(status for status, _ in pair("reject", claim_id)) == [200, 400]
    with Session(engine) as db:
        assert db.get(m.User, "worker").points == 100


def test_postgres_priority_race_and_disconnected_payout(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency required")
    with Session(engine) as db:
        activate(db)
        row = create(db, 2)[1]
        complete(db, row)
        db.commit()
        key = row.id
    gate = Barrier(2)

    def worker(reprice):
        with Session(engine) as db:
            _ = db.get(m.Task, "task").priority
            gate.wait(timeout=10)
            if reprice:
                rewards.lock_scope(db, "task")
                db.get(m.Task, "task").priority = m.TaskPriorityEnum.URGENT
            rewards.reconcile(db, actor_id="owner", task_id="task")
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, v) for v in (True, False)]
        for f in futures:
            f.result(timeout=30)
    with Session(engine) as db:
        assert_books(db, {"worker": 65})
        rows_before = len(ledger(db))
        row = db.get(m.Subtask, key)
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=key,
            data={"expected_version": row.version, "action": "REOPEN"},
        )
        # Drop the actual PostgreSQL connection before COMMIT, simulating a
        # worker disconnect after ledger and wallet writes have both executed.
        db.connection().invalidate()
        db.rollback()
    with Session(engine) as db:
        assert db.get(m.Subtask, key).completed
        assert len(ledger(db)) == rows_before
        assert_books(db, {"worker": 65})
        rewards.reconcile(db, actor_id="owner", task_id="task")
        db.commit()
        assert len(ledger(db)) == rows_before  # retry after a lost response


def test_http_reward_fields_cannot_be_forged_or_read_across_tenants(api_harness):
    from backend.app.dependencies import get_current_owner
    from backend.app.routers import config
    from backend.tests.test_subtask_workflow import add, change

    client, engine, identity = api_harness
    client.app.include_router(config.router)

    def owner():
        with Session(engine) as db:
            return db.get(m.User, identity["id"])

    client.app.dependency_overrides[get_current_owner] = owner
    assert (
        client.patch(
            "/config/subtask-rewards", json={"enabled": True, "expected_version": 0}
        ).status_code
        == 200
    )
    add(client)
    row = add(client)
    for field, value in [
        ("points", 999),
        ("point_policy_version", "legacy"),
        ("reward_timezone", "UTC"),
    ]:
        response = client.patch(
            f"/tasks/main/subtasks/{row['id']}",
            json={"expected_version": row["version"], field: value},
        )
        assert response.status_code == 422
    row = change(client, row, action="START")
    row = change(
        client,
        row,
        actual_start_at="2026-11-02T00:00:00Z",
        actual_end_at="2026-11-02T12:00:00Z",
        confirm_actual_times=True,
    )
    change(client, row, action="COMPLETE")
    identity["id"] = "foreign"
    assert client.get("/tasks/main?include_subtask_activity=true").status_code == 404
    assert client.get("/tasks/main/group").status_code == 404
    assert "main" not in {item["id"] for item in client.get("/tasks").json()}


def test_policy_authority_is_revalidated_from_current_user(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        stale_actor = db.get(m.User, "owner")
    with Session(engine) as db:
        db.get(m.User, "owner").role = m.RoleEnum.USER
        db.commit()
        with pytest.raises(HTTPException) as error:
            rewards.configure(db, actor=stale_actor, enabled=True, expected_version=0)
        assert error.value.status_code == 403
        assert rewards.policy(db, stale_actor.tenant_id) is None


def test_summary_does_not_mix_stale_children_with_fresh_ledger(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        key = create(db, 2)[1].id
        db.commit()
    with Session(engine) as reader:
        task = reader.get(m.Task, "task")
        _ = list(task.subtasks)  # ORM snapshot predates another request's payout.
        with Session(engine) as writer:
            rewards.lock_scope(writer, "task")
            writer.get(m.Task, "task").priority = m.TaskPriorityEnum.URGENT
            complete(writer, writer.get(m.Subtask, key))
            writer.commit()
        result = rewards.summary(task)
        assert result["earned"] == 65
        assert result["available_base"] == 0
        assert result["base_capacity"] == 45


def test_main_additional_bonus_penalty_and_final_balance_example(
    harness, monkeypatch, record_property
):
    from backend.app.services import gamification

    engine, _, _ = harness
    monkeypatch.setattr(gamification, "create_notification", lambda *a, **kw: None)
    with Session(engine) as db:
        activate(db)
        rows = create(db, 3)
        complete(db, rows[2], "2026-11-03T00:00:00Z")
        complete(db, rows[1])
        complete(db, rows[0])
        task = db.get(m.Task, "task")
        task.status = m.TaskStatusEnum.DONE
        task.completed_at = task.due_at = datetime(
            2026, 11, 2, 12, tzinfo=timezone.utc
        ).replace(tzinfo=None)
        gamification.award_task_completion_points(db, task)
        db.commit()
        entries = ledger(db)
        components = {
            kind: sum(row.points for row in entries if row.component_type == kind)
            for kind in ("BASE", "BONUS", "PENALTY", "REVERSAL")
        }
        assert components == {"BASE": 60, "BONUS": 15, "PENALTY": -15, "REVERSAL": 0}
        assert_books(db, {"worker": 60}, opening={"worker": 145, "watcher": 100})
        assert db.get(m.User, "worker").points == 205
        example = {
            "opening_wallet": 100,
            "main_task_base": 30,
            "main_task_bonus": 15,
            "main_task_penalty": 0,
            "additional_subtask_base": 60,
            "additional_subtask_bonus": 15,
            "additional_subtask_penalty": -15,
            "new_policy_earned": 60,
            "total_earned_this_example": 105,
            "closing_wallet": 205,
        }
        before = len(entries)
        rewards.reconcile(db, actor_id="owner", task_id="task")
        db.commit()
        assert len(ledger(db)) == before
        row = rows[1]
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=row.id,
            data={"expected_version": row.version, "action": "REOPEN"},
        )
        db.commit()
        assert_books(db, {"worker": 15}, opening={"worker": 145, "watcher": 100})
        example["after_reopen"] = {
            "main_earned": 45,
            "additional_base": 30,
            "additional_bonus": 0,
            "additional_penalty": -15,
            "new_policy_earned": 15,
            "wallet": 160,
            "compensating_entries": [-30, -15],
        }
        record_property("financial_example", json.dumps(example, sort_keys=True))


def test_postgres_scoped_lookup_query_plans(harness, record_property):
    engine, tenant, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL query plans required")
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1])
        db.commit()
        # Synthetic unrelated history tests selectivity without touching or
        # recalculating any historical rewards or using production data.
        db.execute(
            XpLedger.__table__.insert(),
            [
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant,
                    "user_id": "worker",
                    "event_type": "fixture.historical",
                    "points": 0,
                    "record_version": 1,
                    "ref_type": "fixture",
                }
                for _ in range(10000)
            ],
        )
        db.execute(
            m.Subtask.__table__.insert(),
            [
                {
                    "id": f"historical-{i}",
                    "task_id": "other",
                    "title": "Historical fixture",
                    "completed": False,
                }
                for i in range(10000)
            ],
        )
        db.commit()
        db.execute(sa.text("ANALYZE xp_ledger"))
        db.execute(sa.text("ANALYZE subtasks"))
        plans = {}
        for name, sql in {
            "ledger": "SELECT user_id,SUM(points) FROM xp_ledger WHERE tenant_id=:tenant AND task_id='task' AND record_version=2 AND ref_type=:policy GROUP BY user_id",
            "ordinal": "SELECT id FROM subtasks WHERE task_id='task' AND point_policy_version=:policy AND deleted_at IS NULL ORDER BY created_at,id",
        }.items():
            plans[name] = "\n".join(
                db.scalars(
                    sa.text("EXPLAIN (ANALYZE, BUFFERS) " + sql),
                    {"tenant": tenant, "policy": rewards.POLICY},
                )
            )
            assert "Index" in plans[name]
        record_property("query_plans", json.dumps(plans, sort_keys=True))


def test_configured_penalty_exceeding_base_is_not_capped(harness):
    from backend.app.services.wallet import adjust

    engine, _, _ = harness
    with Session(engine) as db:
        db.add(
            m.PointsTableConfig(
                id=1,
                points_config={
                    "Other": {
                        "HIGH": {
                            "base": 30,
                            "beforeDueBonus": 15,
                            "overduePenalty": -100,
                        }
                    }
                },
            )
        )
        adjust(db, db.get(m.User, "worker"), -100)
        db.commit()
        activate(db)
        row = create(db, 2)[1]
        complete(db, row, "2026-11-03T00:00:00Z")
        db.commit()
        assert_books(db, {"worker": -70}, opening={"worker": 0, "watcher": 100})
        assert {(entry.component_type, entry.points) for entry in ledger(db)} == {
            ("BASE", 30),
            ("PENALTY", -100),
        }
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=row.id,
            data={"expected_version": row.version, "action": "REOPEN"},
        )
        db.commit()
        assert_books(db, {}, opening={"worker": 0, "watcher": 100})
        assert sorted(entry.points for entry in ledger(db) if entry.reversal_of_id) == [
            -30,
            100,
        ]


def test_postgres_first_unpaid_child_races_assignee_tenant_move(harness):
    engine, _, other_tenant = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency required")
    with Session(engine) as db:
        activate(db)
    gate = Barrier(2)

    def run(creating):
        with Session(engine) as db:
            gate.wait(timeout=10)
            try:
                if creating:
                    create(db, 1)
                else:
                    db.execute(
                        sa.update(m.User)
                        .where(m.User.id == "worker")
                        .values(tenant_id=other_tenant)
                    )
                db.commit()
                return True
            except (sa.exc.IntegrityError, HTTPException):
                db.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, v) for v in (True, False)]
        created, moved = [f.result(timeout=30) for f in futures]
    assert created != moved  # at most one ownership-incompatible state commits
    with Session(engine) as db:
        assert ledger(db) == [] and db.get(m.User, "worker").points == 100
        if created:
            assert db.get(m.User, "worker").tenant_id != other_tenant
        else:
            assert not db.scalar(
                sa.select(m.Subtask.id).where(
                    m.Subtask.point_policy_version == rewards.POLICY
                )
            )
