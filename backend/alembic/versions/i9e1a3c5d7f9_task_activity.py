"""Personal activity slots and immutable work corrections; no historical backfill."""

import importlib
import re
import sys

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects.postgresql import UUID

revision = "i9e1a3c5d7f9"
down_revision = "h8d0f2a4c6e8"
branch_labels = None
depends_on = None


def upgrade():
    if context.is_offline_mode():
        raise RuntimeError("Task activity requires online schema verification")
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError("Unsupported activity database")
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("SET LOCAL lock_timeout='5s'")
        bind.exec_driver_sql("SET LOCAL statement_timeout='120s'")
        bind.exec_driver_sql("LOCK TABLE audit_events IN SHARE ROW EXCLUSIVE MODE")
    elif not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    models = sys.modules.get("app.models") or sys.modules.get("backend.app.models")
    ddl = importlib.import_module(models.__package__ + ".services.task_activity_schema")
    if "calculation_inputs" not in {
        c["name"] for c in sa.inspect(bind).get_columns("xp_ledger")
    }:
        raise RuntimeError("Apply Phase 3 before activity infrastructure")
    with bind.begin_nested():
        # Table definitions are copied here so later ORM changes cannot mutate
        # this revision's contract. Existing Phase 1-3 tables are not recreated.
        uuid_type = UUID(as_uuid=True)
        for name, extra in (
            (
                "task_activity_contexts",
                [
                    sa.Column(
                        "task_id",
                        sa.String(36),
                        sa.ForeignKey("tasks.id", ondelete="RESTRICT"),
                        nullable=False,
                    ),
                    sa.Column(
                        "subtask_id",
                        sa.String(36),
                        sa.ForeignKey("subtasks.id", ondelete="RESTRICT"),
                    ),
                    sa.Column("status", sa.String(16), nullable=False),
                    sa.Column("slot", sa.Integer()),
                    sa.Column(
                        "elapsed_ms",
                        sa.BigInteger(),
                        nullable=False,
                        server_default="0",
                    ),
                    sa.Column("resumed_at", sa.DateTime(timezone=True)),
                    sa.Column(
                        "version", sa.Integer(), nullable=False, server_default="1"
                    ),
                    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint(
                        "tenant_id",
                        "user_id",
                        "task_id",
                        name="uq_activity_user_parent",
                    ),
                    sa.UniqueConstraint(
                        "tenant_id", "user_id", "slot", name="uq_activity_user_slot"
                    ),
                    sa.CheckConstraint(
                        "status IN ('RUNNING','PAUSED','STOPPED','COMPLETED')",
                        name="ck_activity_status",
                    ),
                    sa.CheckConstraint(
                        "elapsed_ms>=0 AND version>=1", name="ck_activity_counters"
                    ),
                    sa.CheckConstraint(
                        "(status='RUNNING' AND slot BETWEEN 1 AND 5 AND slot IS NOT NULL AND resumed_at IS NOT NULL) OR (status<>'RUNNING' AND slot IS NULL AND resumed_at IS NULL)",
                        name="ck_activity_five_slots",
                    ),
                ],
            ),
            (
                "task_work_corrections",
                [
                    sa.Column(
                        "original_interval_id",
                        sa.String(36),
                        sa.ForeignKey("task_work_intervals.id", ondelete="RESTRICT"),
                        nullable=False,
                    ),
                    sa.Column(
                        "replacement_interval_id",
                        sa.String(36),
                        sa.ForeignKey("task_work_intervals.id", ondelete="RESTRICT"),
                        nullable=False,
                    ),
                    sa.Column("request_id", sa.String(128), nullable=False),
                    sa.UniqueConstraint(
                        "original_interval_id", name="uq_work_correction_original"
                    ),
                    sa.UniqueConstraint(
                        "replacement_interval_id", name="uq_work_correction_replacement"
                    ),
                    sa.UniqueConstraint(
                        "tenant_id",
                        "user_id",
                        "request_id",
                        name="uq_work_correction_request",
                    ),
                    sa.CheckConstraint(
                        "original_interval_id<>replacement_interval_id",
                        name="ck_work_correction_distinct",
                    ),
                ],
            ),
        ):
            fields = [
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("tenant_id", uuid_type, nullable=False),
                sa.Column(
                    "user_id",
                    sa.String(36),
                    sa.ForeignKey("users.id", ondelete="RESTRICT"),
                    nullable=False,
                ),
                sa.Column(
                    "activity_event_id",
                    sa.String(36),
                    sa.ForeignKey("audit_events.id", ondelete="RESTRICT"),
                    nullable=False,
                ),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                *extra,
            ]
            if name not in sa.inspect(bind).get_table_names():
                expected = op.create_table(name, *fields)
            else:
                expected = sa.Table(name, sa.MetaData(), *fields)
            actual = {c["name"]: c for c in sa.inspect(bind).get_columns(name)}
            declared = (
                {
                    row[1]: row[2].upper()
                    for row in bind.exec_driver_sql(f'PRAGMA table_info("{name}")')
                }
                if bind.dialect.name == "sqlite"
                else {}
            )
            if set(actual) != set(expected.c.keys()):
                raise RuntimeError(f"Incompatible activity table: {name}")
            for col in expected.c:
                found = actual[col.name]
                compatible_uuid = col.name == "tenant_id" and (
                    isinstance(found["type"], sa.Uuid)
                    or bind.dialect.name == "sqlite"
                    and declared.get(col.name) in {"UUID", "CHAR(32)"}
                )
                if (
                    found["nullable"] != col.nullable
                    or not compatible_uuid
                    and found["type"]._type_affinity != col.type._type_affinity
                    or (
                        bind.dialect.name == "postgresql"
                        and col.name.endswith("_at")
                        and not getattr(found["type"], "timezone", False)
                    )
                ):
                    raise RuntimeError(
                        f"Incompatible activity column: {name}.{col.name}"
                    )
                if (
                    isinstance(col.type, sa.String)
                    and found["type"].length != col.type.length
                ):
                    raise RuntimeError(
                        f"Incompatible activity length: {name}.{col.name}"
                    )
            if sa.inspect(bind).get_pk_constraint(name)["constrained_columns"] != [
                "id"
            ]:
                raise RuntimeError(f"Incompatible activity primary key: {name}")
            # Constraints are created with new tables; refuse incomplete adopted
            # tables rather than silently claiming five-slot or FK enforcement.
            uniques = {
                tuple(c["column_names"])
                for c in sa.inspect(bind).get_unique_constraints(name)
            }
            for constraint in expected.constraints:
                if (
                    isinstance(constraint, sa.UniqueConstraint)
                    and tuple(c.name for c in constraint.columns) not in uniques
                ):
                    raise RuntimeError(f"Missing activity uniqueness: {name}")
            checks = {c["name"] for c in sa.inspect(bind).get_check_constraints(name)}
            if (
                not {
                    c.name
                    for c in expected.constraints
                    if isinstance(c, sa.CheckConstraint)
                }
                <= checks
            ):
                raise RuntimeError(f"Missing activity constraints: {name}")
            fks = {
                (
                    tuple(x["constrained_columns"]),
                    x["referred_table"],
                    tuple(x["referred_columns"]),
                    (x.get("options", {}).get("ondelete") or "").upper(),
                )
                for x in sa.inspect(bind).get_foreign_keys(name)
            }
            for fk in expected.foreign_keys:
                target, column = fk.target_fullname.split(".")
                if ((fk.parent.name,), target, (column,), "RESTRICT") not in fks:
                    raise RuntimeError(
                        f"Missing activity reference: {name}.{fk.parent.name}"
                    )
            existing_indexes = {
                x["name"]: x for x in sa.inspect(bind).get_indexes(name)
            }
            frozen_indexes = {
                "task_activity_contexts": {
                    "ix_activity_tenant_user_status": [
                        "tenant_id",
                        "user_id",
                        "status",
                    ],
                    "ix_activity_task_subtask": ["task_id", "subtask_id"],
                },
                "task_work_corrections": {
                    "ix_work_corrections_tenant_user": ["tenant_id", "user_id"]
                },
            }
            for index_name, columns in frozen_indexes[name].items():
                if index_name in existing_indexes:
                    if (
                        existing_indexes[index_name]["column_names"] != columns
                        or existing_indexes[index_name]["unique"]
                    ):
                        raise RuntimeError(f"Incompatible activity index: {index_name}")
                else:
                    op.create_index(index_name, name, columns)
        indexes = sa.inspect(bind).get_indexes("audit_events")
        name = "uq_work_activity_request"
        current = next((x for x in indexes if x["name"] == name), None)
        if current:
            predicate = str(
                current.get("dialect_options", {}).get(bind.dialect.name + "_where", "")
            )
            # Inspect the predicate semantically as PostgreSQL normalizes IN to
            # ANY/ARRAY. Reject extra boolean clauses or hidden column filters.
            identifiers = set(
                re.findall(r"[a-z_]+", re.sub(r"'[^']*'", "", predicate).lower())
            )
            if (
                not current["unique"]
                or current["column_names"]
                != ["tenant_id", "actor_id", "correlation_id"]
                or not predicate
                or not identifiers
                <= {"event_type", "in", "any", "array", "text", "character", "varying"}
            ):
                raise RuntimeError("Incompatible activity request index")
            for event_type in (*ddl.EVENTS, "work.other", "task.status_changed"):
                actual = bind.execute(
                    sa.text(
                        f"SELECT ({predicate}) FROM (SELECT CAST(:probe AS TEXT) AS event_type) AS probe"
                    ),
                    {"probe": event_type},
                ).scalar_one()
                if bool(actual) != (event_type in ddl.EVENTS):
                    raise RuntimeError("Incompatible activity request predicate")
        else:
            op.create_index(
                name,
                "audit_events",
                ["tenant_id", "actor_id", "correlation_id"],
                unique=True,
                sqlite_where=sa.text(ddl.EVENT_PREDICATE),
                postgresql_where=sa.text(ddl.EVENT_PREDICATE),
            )
        for suffix, table, operation, invalid in ddl.specs(bind.dialect.name):
            if (
                operation == "INSERT"
                and bind.execute(
                    sa.text(f"SELECT 1 FROM {table} AS NEW WHERE {invalid} LIMIT 1")
                ).first()
            ):
                raise RuntimeError(f"Incompatible existing activity data: {table}")
        for statement in ddl.statements(bind.dialect.name):
            op.execute(sa.text(statement))


def downgrade():
    raise RuntimeError(
        "Retain activity and confirmed-work history; roll forward safely"
    )
