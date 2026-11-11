"""Full model-derived legacy schema and synthetic data; never reads live data."""
# ruff: noqa: F811 -- imported disposable pytest fixtures.

import hashlib
import importlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.backups import models as backup_models  # noqa: F401
from backend.app.database import Base
from backend.app.services import audit_logger as audit
from backend.app.tickets.models import XpLedger
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401

UTC = timezone.utc
PHASE1_COLUMNS = {
    "subtasks": {
        "planned_start_date",
        "planned_end_date",
        "actual_start_at",
        "actual_end_at",
        "priority_override",
        "point_policy_version",
        "version",
        "created_at",
        "workflow_version",
        "workflow_status",
    },
    "audit_events": {
        "audit_schema_version",
        "tenant_id",
        "task_id",
        "subtask_id",
        "before",
        "after",
        "correlation_id",
    },
    "xp_ledger": {
        "record_version",
        "task_id",
        "subtask_id",
        "component_type",
        "policy_version",
        "idempotency_key",
        "activity_event_id",
        "reason",
        "reversal_of_id",
    },
}


def old_schema():
    """Clone every real ORM table, excluding only Phase 1/2 additions."""
    metadata = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name not in {
            "task_workflow_settings", "task_work_intervals",
            "task_activity_contexts", "task_work_corrections",
        }:
            table.to_metadata(metadata)
    for name, names in PHASE1_COLUMNS.items():
        table = metadata.tables[name]
        for index in list(table.indexes):
            if any(column.name in names for column in index.columns):
                table.indexes.remove(index)
        for constraint in list(table.constraints):
            if any(column.name in names for column in constraint.columns) or (
                isinstance(constraint, sa.CheckConstraint)
                and any(field in str(constraint.sqltext) for field in names)
            ):
                table.constraints.remove(constraint)
        for fk in list(table.foreign_keys):
            if fk.parent.name in names:
                table.foreign_keys.remove(fk)
        for column in list(table.columns):
            if column.name in names:
                table._columns.remove(column)
    for index in list(metadata.tables["tasks"].indexes):
        if index.name in {
            "ix_tasks_assignee_status_updated",
            "ix_tasks_creator_status",
        }:
            metadata.tables["tasks"].indexes.remove(index)
    # The actor-only lookup refers to the new schema marker in its predicate.
    for table in metadata.tables.values():
        for index in list(table.indexes):
            if index.name and (
                index.name.endswith("_v2") or index.name.endswith("_ref")
            ):
                table.indexes.remove(index)
    return metadata


def migrate(connection, monkeypatch):
    for name in ("e5a7c9d1f3b5_task_audit_foundation", "f6b8d0e2a4c6_subtask_workflow"):
        module = importlib.import_module("backend.alembic.versions." + name)
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        module.upgrade()


def fingerprint(connection, table):
    # Explicit original columns: added defaults are checked separately.
    rows = (
        connection.execute(sa.select(*table.c).order_by(*table.primary_key.columns))
        .mappings()
        .all()
    )
    return hashlib.sha256(
        json.dumps([dict(row) for row in rows], sort_keys=True, default=str).encode()
    ).hexdigest()


def test_sanitized_full_schema_migration_preserves_data_and_explains_indexes(
    engine, monkeypatch, record_property
):
    old = old_schema()
    tenants = [
        uuid.uuid5(uuid.NAMESPACE_OID, f"sanitized-tenant-{i}") for i in range(4)
    ]
    instant = datetime(2024, 2, 29, 10, 30, tzinfo=UTC)
    with engine.begin() as connection:
        old.create_all(connection)
        connection.execute(
            old.tables["users"].insert(),
            [
                {
                    "id": f"{role}-{i}",
                    "tenant_id": tenants[i],
                    "name": f"Synthetic {role} {i}",
                    "email": f"{role}-{i}@example.invalid",
                    "hashed_password": "sanitized-noncredential",
                    "role": m.RoleEnum.OWNER if role == "owner" else m.RoleEnum.USER,
                    "points": 1000 + i,
                }
                for i in range(4)
                for role in ("owner", "worker")
            ],
        )
        connection.execute(
            old.tables["tasks"].insert(),
            [
                {
                    "id": f"task-{i}",
                    "title": f"Synthetic task {i}",
                    "created_by_id": f"owner-{i % 4}",
                    "assigned_to_id": f"worker-{i % 4}",
                    "status": list(m.TaskStatusEnum)[i % len(m.TaskStatusEnum)],
                    "priority": list(m.TaskPriorityEnum)[i % 4],
                    "created_at": instant,
                    "updated_at": instant,
                    "due_at": instant + timedelta(days=3),
                }
                for i in range(1500)
            ],
        )
        connection.execute(
            old.tables["subtasks"].insert(),
            [
                {
                    "id": f"old-child-{i}",
                    "task_id": f"task-{i % 1500}",
                    "title": f"Historical child {i}",
                    "completed": i % 3 == 0,
                }
                for i in range(7500)
            ],
        )
        connection.execute(
            old.tables["audit_events"].insert(),
            [
                {
                    "id": f"old-event-{i}",
                    "actor_id": f"owner-{i % 4}",
                    "event_type": "task.updated",
                    "entity_type": "task",
                    "entity_id": f"task-{i % 1500}",
                    "created_at": instant,
                    "payload": {"fixture": "synthetic"},
                }
                for i in range(3000)
            ],
        )
        connection.execute(
            old.tables["xp_ledger"].insert(),
            [
                {
                    "id": uuid.uuid5(uuid.NAMESPACE_OID, f"old-ledger-{i}"),
                    "tenant_id": tenants[i % 4],
                    "user_id": f"worker-{i % 4}",
                    "event_type": "legacy",
                    "points": i % 17 - 5,
                    "created_at": instant,
                    "deleted_at": instant if i % 19 == 0 else None,
                }
                for i in range(1500)
            ],
        )
        connection.execute(
            old.tables["rewards"].insert(),
            {
                "id": "reward",
                "title": "Synthetic reward",
                "description": "Sanitized fixture",
                "image_ref": "fixture",
                "xp_required": 25,
            },
        )
        connection.execute(
            old.tables["reward_claims"].insert(),
            {
                "id": "claim",
                "reward_id": "reward",
                "user_id": "worker-0",
                "xp_spent": 25,
            },
        )
        names = (
            "users",
            "tasks",
            "subtasks",
            "audit_events",
            "xp_ledger",
            "rewards",
            "reward_claims",
        )
        before = {name: fingerprint(connection, old.tables[name]) for name in names}
        migrate(connection, monkeypatch)
        migrate(connection, monkeypatch)
        after = {name: fingerprint(connection, old.tables[name]) for name in names}
        assert before == after
        assert (
            connection.execute(
                sa.text(
                    "SELECT COUNT(*) FROM subtasks WHERE point_policy_version='legacy' AND workflow_version=0 AND created_at IS NULL AND actual_start_at IS NULL AND actual_end_at IS NULL AND workflow_status IS NULL"
                )
            ).scalar_one()
            == 7500
        )
        assert (
            connection.execute(
                sa.text(
                    "SELECT COUNT(*) FROM audit_events WHERE audit_schema_version=2"
                )
            ).scalar_one()
            == 0
        )
        record_property("legacy_fingerprints", json.dumps(before, sort_keys=True))
        record_property(
            "fixture_counts",
            json.dumps(
                {
                    "schema_tables": len(old.tables),
                    "tenants": 4,
                    "users": 8,
                    "tasks": 1500,
                    "subtasks": 7500,
                    "legacy_events": 3000,
                    "legacy_ledger": 1500,
                    "rewards": 1,
                    "claims": 1,
                }
            ),
        )
        if engine.dialect.name != "postgresql":
            return
        events = [
            {
                "id": f"new-event-{i}",
                "actor_id": f"owner-{i % 4}",
                "tenant_id": tenants[i % 4],
                "task_id": f"task-{i % 100}",
                "audit_schema_version": 2,
                "event_type": "task.synthetic_change",
                "entity_type": "task",
                "entity_id": f"task-{i % 100}",
                "created_at": instant + timedelta(seconds=i),
            }
            for i in range(6000)
        ]
        connection.execute(m.AuditEvent.__table__.insert(), events)
        connection.execute(
            XpLedger.__table__.insert(),
            [
                {
                    "id": uuid.uuid5(uuid.NAMESPACE_OID, f"new-ledger-{i}"),
                    "tenant_id": tenants[i % 4],
                    "task_id": f"task-{i % 100}",
                    "user_id": f"worker-{i % 4}",
                    "record_version": 2,
                    "event_type": "task.synthetic_change",
                    "component_type": "ADJUSTMENT",
                    "points": i % 9 - 4,
                    "policy_version": "synthetic-v2",
                    "idempotency_key": f"synthetic-{i}",
                    "activity_event_id": f"new-event-{i}",
                    "reason": "Sanitized schema rehearsal",
                    "created_at": instant,
                }
                for i in range(3000)
            ],
        )
        for table in ("audit_events", "xp_ledger", "tasks"):
            connection.exec_driver_sql(f"ANALYZE {table}")
        queries = {
            "event_chronology": sa.select(m.AuditEvent.id)
            .where(
                m.AuditEvent.tenant_id == tenants[0], m.AuditEvent.task_id == "task-0"
            )
            .order_by(m.AuditEvent.created_at, m.AuditEvent.id)
            .limit(50),
            "actor_guard": sa.select(m.AuditEvent.id)
            .where(
                m.AuditEvent.audit_schema_version == 2,
                m.AuditEvent.actor_id == "worker-0",
            )
            .limit(1),
            "event_task_fk": sa.select(m.AuditEvent.id).where(
                m.AuditEvent.task_id == "task-1499"
            ),
            "ledger_idempotency": sa.select(XpLedger.id).where(
                XpLedger.tenant_id == tenants[0],
                XpLedger.idempotency_key == "synthetic-200",
            ),
            "ledger_recipient_guard": sa.select(XpLedger.id)
            .where(XpLedger.record_version == 2, XpLedger.user_id == "owner-0")
            .limit(1),
        }
        plans = {}
        for name, query in queries.items():
            sql = str(query.compile(connection, compile_kwargs={"literal_binds": True}))
            plan = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql
            ).scalar_one()[0]

            def indexes(node):
                return ([node["Index Name"]] if "Index Name" in node else []) + [
                    item for child in node.get("Plans", []) for item in indexes(child)
                ]

            used = indexes(plan["Plan"])
            assert used, (name, plan)
            plans[name] = {
                "indexes": used,
                "execution_ms": plan["Execution Time"],
                "rows": plan["Plan"]["Actual Rows"],
            }
        record_property("postgres_query_plans", json.dumps(plans, sort_keys=True))
        assert fingerprint(connection, old.tables["users"]) == before["users"]
        assert fingerprint(connection, old.tables["rewards"]) == before["rewards"]
        assert (
            fingerprint(connection, old.tables["reward_claims"])
            == before["reward_claims"]
        )


def test_restrictive_references_and_append_only_history(harness):
    engine, tenant, _ = harness
    with Session(engine) as db:
        event = audit.record_task_activity(
            db,
            actor_id="owner",
            task_id="task",
            data={"event_type": "task.points_changed"},
        )
        # A recipient who is not a task assignee/actor still cannot lose its ID.
        row = audit.append_point_adjustment(
            db,
            actor_id="owner",
            task_id="task",
            data={
                "user_id": "watcher",
                "component_type": "BONUS",
                "points": 5,
                "policy_version": "v2",
                "idempotency_key": "immutable",
                "activity_event_id": event.id,
                "reason": "Fixture",
            },
        )
        db.commit()
        for statement in [
            sa.update(m.User).where(m.User.id == "watcher").values(id="moved"),
            sa.update(XpLedger)
            .where(XpLedger.id == row.id)
            .values(deleted_at=m.utc_now()),
        ]:
            with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
                db.execute(statement)
        if engine.dialect.name == "postgresql":
            with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
                db.execute(sa.text("TRUNCATE audit_events CASCADE"))
        assert db.get(XpLedger, row.id).points == 5
        assert db.get(m.User, "watcher").tenant_id == tenant


def test_policy_ownership_is_frozen_even_without_historical_events(harness):
    engine, tenant, other = harness
    with Session(engine) as db:
        db.add(
            m.TaskWorkflowSettings(
                tenant_id=tenant,
                enabled=True,
                point_policy_version="v2",
                activated_at=m.utc_now() - timedelta(days=1),
            )
        )
        db.commit()
        db.add(
            m.Subtask(
                id="restored-policy",
                task_id="task",
                title="Restored",
                point_policy_version="v2",
                created_at=m.utc_now(),
            )
        )
        db.commit()
        assert db.scalar(sa.select(sa.func.count()).select_from(m.AuditEvent)) == 0
        for statement in (
            sa.update(m.Task)
            .where(m.Task.id == "task")
            .values(created_by_id="foreign"),
            sa.update(m.User).where(m.User.id == "owner").values(tenant_id=other),
        ):
            with pytest.raises(sa.exc.IntegrityError), db.begin_nested():
                db.execute(statement)


@pytest.mark.parametrize(
    "defect",
    ["utc", "foreign_key", "idempotency", "workflow_default", "status_capacity"],
)
def test_migration_refuses_unsafe_adopted_schema_without_changing_data(
    harness, monkeypatch, defect
):
    engine, _, _ = harness
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL schema drift rehearsal")
    module = importlib.import_module(
        "backend.alembic.versions.f6b8d0e2a4c6_subtask_workflow"
    )
    with engine.begin() as connection:
        if defect == "utc":
            connection.exec_driver_sql(
                "ALTER TABLE subtasks ALTER COLUMN actual_start_at TYPE timestamp without time zone USING actual_start_at AT TIME ZONE 'UTC'"
            )
        elif defect == "foreign_key":
            name = next(
                fk["name"]
                for fk in sa.inspect(connection).get_foreign_keys("audit_events")
                if fk["constrained_columns"] == ["task_id"]
            )
            quoted = connection.dialect.identifier_preparer.quote(name)
            connection.exec_driver_sql(
                f"ALTER TABLE audit_events DROP CONSTRAINT {quoted}"
            )
            connection.exec_driver_sql(
                f"ALTER TABLE audit_events ADD CONSTRAINT {quoted} FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL"
            )
        elif defect == "workflow_default":
            connection.exec_driver_sql(
                "ALTER TABLE subtasks ALTER COLUMN workflow_version SET DEFAULT 2"
            )
        elif defect == "status_capacity":
            connection.exec_driver_sql(
                "ALTER TABLE subtasks ALTER COLUMN workflow_status TYPE varchar(3)"
            )
        else:
            connection.exec_driver_sql(
                "ALTER TABLE xp_ledger DROP CONSTRAINT uq_xp_ledger_tenant_idempotency"
            )
            connection.exec_driver_sql(
                "CREATE INDEX uq_xp_ledger_tenant_idempotency ON xp_ledger(tenant_id,idempotency_key)"
            )
        monkeypatch.setattr(
            module, "op", Operations(MigrationContext.configure(connection))
        )
        monkeypatch.setattr(module.context, "is_offline_mode", lambda: False)
        with pytest.raises(RuntimeError, match="Reconcile"):
            module.upgrade()
        assert (
            connection.execute(
                sa.text("SELECT points FROM users WHERE id='owner'")
            ).scalar_one()
            == 100
        )
        assert (
            connection.execute(
                sa.text("SELECT COUNT(*) FROM audit_events")
            ).scalar_one()
            == 0
        )


def test_legacy_version_cannot_be_used_to_create_mutable_new_history(harness):
    engine, tenant, _ = harness
    with engine.begin() as connection:
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(
                m.AuditEvent.__table__.insert(),
                {
                    "id": "mutable",
                    "actor_id": "owner",
                    "tenant_id": tenant,
                    "task_id": "task",
                    "audit_schema_version": 1,
                    "event_type": "task.changed",
                    "entity_type": "task",
                    "entity_id": "task",
                },
            )
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(
                XpLedger.__table__.insert(),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant,
                    "user_id": "worker",
                    "task_id": "task",
                    "record_version": 1,
                    "event_type": "legacy",
                    "points": 7,
                },
            )
