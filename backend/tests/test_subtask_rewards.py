"""Financial policy tests using owned disposable schemas and synthetic wallets."""

# ruff: noqa: F811 -- pytest imports disposable fixtures.
import importlib
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
from backend.app.services import subtask_rewards as rewards
from backend.app.services import subtasks
from backend.app.services.wallet import adjust
from backend.app.tickets.models import XpLedger
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401
from backend.tests.test_task_tabs_review import harness as api_harness  # noqa: F401

UTC = timezone.utc
PLAN = {
    "title": "Additional",
    "planned_start_date": "2026-11-02",
    "planned_end_date": "2026-11-02",
}


def activate(db):
    db.get(m.User, "owner").timezone = "UTC"
    db.get(m.Task, "task").priority = m.TaskPriorityEnum.HIGH
    result = rewards.configure(
        db, actor=db.get(m.User, "owner"), enabled=True, expected_version=0
    )
    db.commit()
    return result


def create(db, count):
    return [
        subtasks.create(
            db, actor_id="owner", task_id="task", data={**PLAN, "title": f"Child {i}"}
        )
        for i in range(count)
    ]


def complete(db, child, end="2026-11-02T12:00:00Z"):
    for data in [
        {"action": "START"},
        {
            "actual_start_at": "2026-11-02T00:00:00Z",
            "actual_end_at": end,
            "confirm_actual_times": True,
        },
        {"action": "COMPLETE"},
    ]:
        child = subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=child.id,
            data={"expected_version": child.version, **data},
        )
    return child


def ledger(db):
    return list(
        db.scalars(sa.select(XpLedger).where(XpLedger.ref_type == rewards.POLICY))
    )


@pytest.mark.parametrize("count", [1, 2, 3, 5, 100])
def test_counts_capacity_out_of_order_completion_and_first_zero(harness, count):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, count)
        db.commit()
        assert (
            rewards.summary(db.get(m.Task, "task"))["base_capacity"]
            == max(0, count - 1) * 30
        )
        for child in reversed(rows):
            complete(db, child)
        db.commit()
        result = rewards.summary(db.get(m.Task, "task"))
        assert (
            result["available_base"] == 0 and result["earned"] == max(0, count - 1) * 45
        )
        assert db.get(m.User, "worker").points == 100 + max(0, count - 1) * 45
        assert len(ledger(db)) == max(0, count - 1) * 2
        assert all(row.subtask_id != rows[0].id for row in ledger(db))
        assert db.get(m.Subtask, "legacy").point_policy_version == "legacy"
        assert db.get(m.User, "owner").points == 100


@pytest.mark.parametrize(
    "priority,base", [("LOW", 10), ("MEDIUM", 20), ("HIGH", 30), ("URGENT", 45)]
)
def test_existing_priority_values_and_display_override(harness, priority, base):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        db.get(m.Task, "task").priority = m.TaskPriorityEnum(priority)
        rows = create(db, 2)
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=rows[1].id,
            data={"expected_version": 1, "priority_override": "LOW"},
        )
        complete(db, rows[1])
        db.commit()
        assert (
            next(row.points for row in ledger(db) if row.component_type == "BASE")
            == base
        )
        assert rewards.summary(db.get(m.Task, "task"))["base_capacity"] == base


@pytest.mark.parametrize(
    "end,component,points",
    [
        ("2026-11-02T23:59:59.999998Z", "BONUS", 15),
        ("2026-11-02T23:59:59.999999Z", "BONUS", 15),
        ("2026-11-03T00:00:00Z", "PENALTY", -15),
    ],
)
def test_bonus_penalty_deadline_boundaries(harness, end, component, points):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1], end)
        db.commit()
        assert {(row.component_type, row.points) for row in ledger(db)} == {
            ("BASE", 30),
            (component, points),
        }
        assert all(
            row.calculation_inputs["algorithm"] == rewards.POLICY for row in ledger(db)
        )


def test_unrepresentable_deadline_is_a_validation_error_without_partial_writes(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        with pytest.raises(HTTPException) as failure:
            subtasks.create(
                db,
                actor_id="owner",
                task_id="task",
                data={**PLAN, "planned_end_date": "9999-12-31"},
            )
        assert failure.value.status_code == 422
        db.commit()
        assert (
            db.scalar(
                sa.select(sa.func.count())
                .select_from(m.Subtask)
                .where(m.Subtask.point_policy_version == rewards.POLICY)
            )
            == 0
        )
        assert ledger(db) == [] and db.get(m.User, "worker").points == 100


def test_delete_first_restore_reopen_and_reassignment(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 3)
        for child in rows:
            complete(db, child)
        db.commit()
        first = subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=rows[0].id,
            data={"expected_version": rows[0].version, "deleted": True},
        )
        db.commit()
        assert db.get(m.User, "worker").points == 145
        assert len([row for row in ledger(db) if row.component_type == "REVERSAL"]) == 2
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=first.id,
            data={"expected_version": first.version, "deleted": False},
        )
        db.commit()
        assert db.get(m.User, "worker").points == 190
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=rows[1].id,
            data={"expected_version": rows[1].version, "action": "REOPEN"},
        )
        db.commit()
        assert db.get(m.User, "worker").points == 145
        rewards.lock_scope(db, "task")
        db.get(m.Task, "task").assigned_to_id = "watcher"
        rewards.reconcile(db, actor_id="owner", task_id="task")
        db.commit()
        assert db.get(m.User, "worker").points == 100
        assert db.get(m.User, "watcher").points == 145
        for row in ledger(db):
            if row.reversal_of_id:
                assert row.points == -db.get(XpLedger, row.reversal_of_id).points


def test_dates_priority_config_refresh_and_eligibility_reprice(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1])
        db.commit()
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=rows[1].id,
            data={
                "expected_version": rows[1].version,
                "planned_start_date": "2026-11-01",
                "planned_end_date": "2026-11-01",
            },
        )
        db.commit()
        assert db.get(m.User, "worker").points == 115
        rewards.lock_scope(db, "task")
        db.get(m.Task, "task").priority = m.TaskPriorityEnum.URGENT
        rewards.reconcile(db, actor_id="owner", task_id="task")
        db.commit()
        assert db.get(m.User, "worker").points == 125
        setting = rewards.policy(db, db.get(m.User, "owner").tenant_id)
        rewards.configure(
            db,
            actor=db.get(m.User, "owner"),
            enabled=True,
            expected_version=setting.version,
            penalty_enabled=False,
        )
        db.commit()
        assert db.get(m.User, "worker").points == 145
        # Existing policy snapshots do not adopt another tenant's global edit.
        db.add(
            m.PointsTableConfig(
                id=1,
                points_config={
                    "Other": {
                        "URGENT": {
                            "base": 60,
                            "beforeDueBonus": 20,
                            "overduePenalty": -20,
                        }
                    }
                },
            )
        )
        db.commit()
        rewards.reconcile(db, actor_id="owner", task_id="task")
        assert db.get(m.User, "worker").points == 145
        setting = rewards.policy(db, db.get(m.User, "owner").tenant_id)
        rewards.configure(
            db,
            actor=db.get(m.User, "owner"),
            enabled=True,
            expected_version=setting.version,
            penalty_enabled=False,
            refresh_rules=True,
        )
        db.commit()
        assert db.get(m.User, "worker").points == 160
        setting = rewards.policy(db, db.get(m.User, "owner").tenant_id)
        rewards.configure(
            db,
            actor=db.get(m.User, "owner"),
            enabled=False,
            expected_version=setting.version,
        )
        db.commit()
        assert (
            rewards.policy(db, db.get(m.User, "owner").tenant_id).reward_policy_data[
                "penalty_enabled"
            ]
            is False
        )
        subtasks.edit(
            db,
            actor_id="owner",
            task_id="task",
            subtask_id=rows[1].id,
            data={
                "expected_version": rows[1].version,
                "planned_end_date": "2026-11-02",
            },
        )
        db.commit()
        assert db.get(m.User, "worker").points == 180
        setting = rewards.policy(db, db.get(m.User, "owner").tenant_id)
        rewards.configure(
            db,
            actor=db.get(m.User, "owner"),
            enabled=True,
            expected_version=setting.version,
            bonus_enabled=False,
            penalty_enabled=False,
        )
        db.commit()
        assert db.get(m.User, "worker").points == 160


def test_failed_wallet_rolls_back_completion_audit_and_ledger(harness, monkeypatch):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
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
        db.commit()
        version = row.version

        def fail(*args, **kwargs):
            raise RuntimeError("Synthetic wallet failure")

        monkeypatch.setattr(rewards, "adjust_wallet", fail)
        with pytest.raises(RuntimeError, match="Synthetic wallet"):
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=row.id,
                data={"expected_version": version, "action": "COMPLETE"},
            )
        db.commit()
        db.expire_all()
        assert (
            db.get(m.Subtask, row.id).version == version
            and not db.get(m.Subtask, row.id).completed
        )
        assert ledger(db) == [] and db.get(m.User, "worker").points == 100


def test_idempotency_immutability_original_order_and_legacy(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        pre = subtasks.create(db, actor_id="owner", task_id="task", data=PLAN)
        db.commit()
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1])
        db.commit()
        for _ in range(3):
            rewards.reconcile(db, actor_id="owner", task_id="task")
        db.commit()
        assert len(ledger(db)) == 2 and pre.point_policy_version == "legacy"
        for query in [
            sa.update(m.Subtask)
            .where(m.Subtask.id == rows[0].id)
            .values(created_at=m.utc_now()),
            sa.delete(XpLedger).where(XpLedger.ref_type == rewards.POLICY),
            sa.delete(m.Subtask).where(m.Subtask.id == rows[0].id),
        ]:
            with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
                db.execute(query)
        with pytest.raises(HTTPException) as failure:
            rewards.reconcile(db, actor_id="foreign", task_id="task")
        assert failure.value.status_code == 404


def test_http_contract_parent_repricing_policy_rbac_and_tenant(api_harness):
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
    first, second = add(client), add(client)
    second = change(client, second, action="START")
    second = change(
        client,
        second,
        actual_start_at="2026-11-02T00:00:00Z",
        actual_end_at="2026-11-02T12:00:00Z",
        confirm_actual_times=True,
    )
    second = change(client, second, action="COMPLETE")
    response = client.patch(
        "/tasks/main",
        json={"priority": "HIGH", "team": "IT Support", "assigned_to_id": "peer"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["subtask_rewards"]["earned"] == 45
    assert (
        client.patch(
            f"/tasks/main/subtasks/{second['id']}",
            json={"expected_version": second["version"] - 1, "action": "COMPLETE"},
        ).status_code
        == 409
    )
    identity["id"] = "foreign"
    assert (
        client.patch(
            f"/tasks/main/subtasks/{first['id']}",
            json={"expected_version": first["version"], "deleted": True},
        ).status_code
        == 404
    )
    identity["id"] = "peer"
    assert (
        client.patch(
            "/config/subtask-rewards", json={"enabled": True, "expected_version": 0}
        ).status_code
        == 403
    )


def test_postgres_concurrent_completion_and_wallet_delta(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency required")
    with Session(engine) as db:
        activate(db)
        rows = create(db, 3)
        for row in rows[1:]:
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=row.id,
                data={"expected_version": 1, "action": "START"},
            )
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=row.id,
                data={
                    "expected_version": 2,
                    "actual_start_at": "2026-11-02T00:00:00Z",
                    "actual_end_at": "2026-11-02T12:00:00Z",
                    "confirm_actual_times": True,
                },
            )
        db.commit()
        keys = [row.id for row in rows[1:]]
    gate = Barrier(3)

    def finish(key):
        with Session(engine) as db:
            gate.wait(timeout=10)
            subtasks.edit(
                db,
                actor_id="owner",
                task_id="task",
                subtask_id=key,
                data={"expected_version": 3, "action": "COMPLETE"},
            )
            db.commit()

    def independent_delta():
        with Session(engine) as db:
            user = db.get(m.User, "worker")
            gate.wait(timeout=10)
            adjust(db, user, 7)
            db.commit()

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(finish, key) for key in keys] + [
            pool.submit(independent_delta)
        ]
        for future in futures:
            future.result(timeout=30)
    with Session(engine) as db:
        assert db.get(m.User, "worker").points == 197 and len(ledger(db)) == 4


def test_postgres_concurrent_creation_order_has_one_zero_base(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency required")
    with Session(engine) as db:
        activate(db)
    gate = Barrier(2)

    def worker():
        with Session(engine) as db:
            # Populate a stale collection before competing for the reward lock.
            _initial_children = list(db.get(m.Task, "task").subtasks)
            gate.wait(timeout=10)
            child = create(db, 1)[0]
            complete(db, child)
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)
    with Session(engine) as db:
        result = rewards.summary(db.get(m.Task, "task"))
        assert result["eligible_count"] == 2 and result["earned"] == 45
        assert db.get(m.User, "worker").points == 145 and len(ledger(db)) == 2


def test_postgres_different_parents_shared_wallet_complete_without_deadlock(harness):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency required")
    with Session(engine) as db:
        activate(db)
        db.add(
            m.Task(
                id="task-two",
                title="Second parent",
                created_by_id="owner",
                assigned_to_id="worker",
                priority=m.TaskPriorityEnum.HIGH,
            )
        )
        db.commit()
        keys = []
        for task_id in ("task", "task-two"):
            children = [
                subtasks.create(db, actor_id="owner", task_id=task_id, data=PLAN)
                for _ in range(2)
            ]
            row = children[1]
            for data in (
                {"action": "START"},
                {
                    "actual_start_at": "2026-11-02T00:00:00Z",
                    "actual_end_at": "2026-11-02T12:00:00Z",
                    "confirm_actual_times": True,
                },
            ):
                subtasks.edit(
                    db,
                    actor_id="owner",
                    task_id=task_id,
                    subtask_id=row.id,
                    data={"expected_version": row.version, **data},
                )
            keys.append((task_id, row.id, row.version))
        db.commit()
    gate = Barrier(2)

    def finish(values):
        task_id, child_id, version = values
        with Session(engine) as db:
            gate.wait(timeout=10)
            subtasks.edit(
                db,
                actor_id="owner",
                task_id=task_id,
                subtask_id=child_id,
                data={"expected_version": version, "action": "COMPLETE"},
            )
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(finish, values) for values in keys]
        for future in futures:
            future.result(timeout=30)
    with Session(engine) as db:
        assert db.get(m.User, "worker").points == 190 and len(ledger(db)) == 4


def test_phase3_migration_repeat_and_safe_downgrade(harness, monkeypatch):
    engine, _, _ = harness
    module = importlib.import_module(
        "backend.alembic.versions.g7c9e1f3a5d7_subtask_rewards"
    )
    with engine.begin() as connection:
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        module.upgrade()
        module.upgrade()
        assert (
            connection.execute(
                sa.text("SELECT points FROM users WHERE id='worker'")
            ).scalar_one()
            == 100
        )
        assert (
            connection.execute(sa.text("SELECT COUNT(*) FROM xp_ledger")).scalar_one()
            == 0
        )
        with pytest.raises(RuntimeError, match="Retain"):
            module.downgrade()


def test_actual_phase2_schema_upgrade_preserves_all_original_columns(
    engine, monkeypatch
):
    import uuid

    from backend.app.database import Base

    metadata = sa.MetaData()
    added = {
        "subtasks": {"deleted_at", "reward_timezone"},
        "xp_ledger": {"calculation_inputs"},
        "task_workflow_settings": {"reward_policy_data"},
    }
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    for name, names in added.items():
        table = metadata.tables[name]
        for index in list(table.indexes):
            if (
                any(col.name in names for col in index.columns)
                or index.name == "uq_xp_ledger_subtask_component_event"
            ):
                table.indexes.remove(index)
        for name in names:
            table._columns.remove(table.c[name])
    metadata.create_all(engine)
    module = importlib.import_module(
        "backend.alembic.versions.g7c9e1f3a5d7_subtask_rewards"
    )
    with engine.begin() as connection:
        m.install_task_audit_guards(connection)
        connection.execute(
            metadata.tables["users"]
            .insert()
            .values(
                id="old",
                tenant_id=uuid.uuid4(),
                name="Synthetic",
                email="old@example.com",
                hashed_password="fixture",
                role="OWNER",
                points=123,
            )
        )
        connection.execute(
            metadata.tables["tasks"]
            .insert()
            .values(id="old-task", title="Old", created_by_id="old")
        )
        connection.execute(
            metadata.tables["subtasks"]
            .insert()
            .values(
                id="old-child",
                task_id="old-task",
                title="Old",
                completed=True,
                created_at=None,
            )
        )
        before = {
            name: connection.execute(sa.select(metadata.tables[name])).all()
            for name in ("users", "tasks", "subtasks", "xp_ledger", "audit_events")
        }
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        module.upgrade()
        module.upgrade()
        for name, rows in before.items():
            assert connection.execute(sa.select(metadata.tables[name])).all() == rows
        assert connection.execute(
            sa.text("SELECT deleted_at,reward_timezone FROM subtasks")
        ).one() == (None, None)


def test_migration_refuses_malformed_reserved_policy_without_repair(
    harness, monkeypatch
):
    engine, tenant, _ = harness
    module = importlib.import_module(
        "backend.alembic.versions.g7c9e1f3a5d7_subtask_rewards"
    )
    with engine.begin() as connection:
        suffix = (
            " ON task_workflow_settings"
            if connection.dialect.name == "postgresql"
            else ""
        )
        connection.exec_driver_sql("DROP TRIGGER zea_v3_policy_insert" + suffix)
        connection.execute(
            m.TaskWorkflowSettings.__table__.insert().values(
                tenant_id=tenant,
                point_policy_version=rewards.POLICY,
                enabled=False,
                version=1,
            )
        )
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        with pytest.raises(RuntimeError, match="reward state"):
            module.upgrade()
        assert (
            connection.execute(
                sa.text("SELECT points FROM users WHERE id='worker'")
            ).scalar_one()
            == 100
        )


def test_original_tie_order_timezone_snapshot_and_duplicate_constraint(harness):
    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        db.get(m.User, "owner").timezone = "Asia/Kolkata"
        row = create(db, 1)[0]
        second = create(db, 1)[0]
        db.commit()
        db.get(m.User, "owner").timezone = "UTC"
        complete(db, second, "2026-11-02T18:29:59.999999Z")
        db.commit()
        assert second.reward_timezone == "Asia/Kolkata"
        assert (
            next(
                entry.points for entry in ledger(db) if entry.component_type == "BONUS"
            )
            == 15
        )
        original = ledger(db)[0]
        values = {
            column.name: getattr(original, column.name)
            for column in XpLedger.__table__.columns
            if column.name != "id"
        }
        with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
            db.add(XpLedger(**values))
            db.flush()
        # Identical original instants use the unique identifier, never completion order.
        instant = m.utc_now()
        for key in ("tie-z", "tie-a"):
            db.add(
                m.Subtask(
                    id=key,
                    task_id="task",
                    title=key,
                    created_at=instant,
                    point_policy_version=rewards.POLICY,
                    reward_timezone="UTC",
                    workflow_version=2,
                    workflow_status="TODO",
                    planned_start_date=row.planned_start_date,
                    planned_end_date=row.planned_end_date,
                )
            )
        db.flush()
        children = list(
            db.scalars(
                sa.select(m.Subtask).where(
                    m.Subtask.point_policy_version == rewards.POLICY
                )
            )
        )
        _, _, ordinal, _ = rewards.calculation(
            db,
            db.get(m.Task, "task"),
            children,
            rewards.policy(db, db.get(m.User, "owner").tenant_id),
        )
        assert ordinal["tie-a"] < ordinal["tie-z"]


def test_existing_main_reward_formula_remains_separate_and_atomic(harness, monkeypatch):
    from backend.app.services import gamification

    engine, _, _ = harness
    with Session(engine) as db:
        activate(db)
        rows = create(db, 2)
        complete(db, rows[1])
        db.commit()
        db.add(m.PointsTableConfig(id=1))
        db.commit()
        task = db.get(m.Task, "task")
        task.completed_at = task.due_at = datetime(2026, 11, 2, 12, tzinfo=UTC).replace(
            tzinfo=None
        )
        monkeypatch.setattr(
            gamification, "create_notification", lambda *args, **kwargs: None
        )
        gamification.award_task_completion_points(db, task)
        db.commit()
        assert db.get(m.User, "worker").points == 190
        assert db.get(m.User, "worker").tasks_completed == 1
        assert len(ledger(db)) == 2
        from backend.app.services import rewards as claims

        monkeypatch.setattr(
            claims.notification_service,
            "create_notification",
            lambda *args, **kwargs: None,
        )
        db.add(
            m.Reward(
                id="fixture-reward",
                title="Synthetic reward",
                description="Fixture only",
                xp_required=40,
                auto_redeem=False,
            )
        )
        db.commit()
        claim = claims.claim_reward(
            db, reward_id="fixture-reward", user=db.get(m.User, "worker")
        )
        assert db.get(m.User, "worker").points == 150
        claims.reject_claim(db, claim_id=claim.id, actor=db.get(m.User, "owner"))
        assert db.get(m.User, "worker").points == 190 and len(ledger(db)) == 2
        with pytest.raises(HTTPException):
            claims.reject_claim(db, claim_id=claim.id, actor=db.get(m.User, "owner"))
        assert db.get(m.User, "worker").points == 190
