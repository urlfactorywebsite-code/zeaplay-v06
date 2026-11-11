"""Additive subtask schedule, scoped task activity, XP adjustments and manual work.

Online migration only: existing installations can have startup-created tables.
No historical events, credits or creation/completion timestamps are fabricated.
"""

import sys

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e5a7c9d1f3b5"
down_revision = "d4f6a8b0c2e4"
branch_labels = None
depends_on = None


def _column(table, column, reference=None):
    bind = op.get_bind()
    existing = {c["name"]: c for c in sa.inspect(bind).get_columns(table)}
    if column.name in existing:
        actual = existing[column.name]
        if actual["nullable"] != column.nullable:
            raise RuntimeError(f"Incompatible workflow column: {table}.{column.name}")
        if column.server_default is not None:
            expected_default = str(column.server_default.arg).strip("'\"() ").lower()
            actual_default = (
                str(actual.get("default") or "").split("::")[0].strip("'\"() ").lower()
            )
            if actual_default != expected_default:
                raise RuntimeError(
                    f"Incompatible workflow default: {table}.{column.name}"
                )
        for kind in (sa.Integer, sa.DateTime, sa.Date, sa.Boolean, sa.JSON):
            if isinstance(column.type, kind) and not isinstance(actual["type"], kind):
                raise TypeError(f"Incompatible workflow type: {table}.{column.name}")
        if isinstance(column.type, sa.String) and (
            not isinstance(actual["type"], sa.String)
            or (
                column.type.length is not None
                and (actual["type"].length or 0) < column.type.length
            )
        ):
            raise TypeError(f"Incompatible workflow type: {table}.{column.name}")
    elif reference and bind.dialect.name == "sqlite":
        target, ondelete = reference
        definition = str(sa.schema.CreateColumn(column).compile(dialect=bind.dialect))
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN {definition} REFERENCES {target}(id) ON DELETE {ondelete}"
        )
    else:
        op.add_column(table, column)
    if reference:
        target, ondelete = reference
        fks = sa.inspect(bind).get_foreign_keys(table)
        matching = [
            fk
            for fk in fks
            if fk["constrained_columns"] == [column.name]
            and fk["referred_table"] == target
            and fk["referred_columns"] == ["id"]
        ]
        if not matching:
            if bind.dialect.name == "sqlite":
                raise RuntimeError(
                    f"Missing workflow FK on adopted column: {table}.{column.name}"
                )
            op.create_foreign_key(
                f"fk_{table}_{column.name}_phase1",
                table,
                target,
                [column.name],
                ["id"],
                ondelete=ondelete,
            )


def _index(table, name, columns, unique=False):
    indexes = {idx["name"]: idx for idx in sa.inspect(op.get_bind()).get_indexes(table)}
    constraints = {
        c["name"]: c for c in sa.inspect(op.get_bind()).get_unique_constraints(table)
    }
    existing = indexes.get(name) or constraints.get(name)
    if existing:
        if existing["column_names"] != columns or (
            name in indexes and bool(existing.get("unique")) != unique
        ):
            raise RuntimeError(f"Incompatible workflow index: {name}")
    else:
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Task audit migration requires an online disposable rehearsal"
        )
    bind = op.get_bind()
    if bind.dialect.name not in ("sqlite", "postgresql"):
        raise RuntimeError("Task audit migration supports PostgreSQL and SQLite")
    required = {"users", "tasks", "subtasks", "audit_events", "xp_ledger"}
    if not required.issubset(sa.inspect(bind).get_table_names()):
        raise RuntimeError(
            "Reconcile the existing core schema before task audit migration"
        )
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '120s'")
    if (
        bind.dialect.name == "sqlite"
        and not bind.connection.driver_connection.in_transaction
    ):
        bind.exec_driver_sql("BEGIN")
    # SAVEPOINT also makes SQLite DDL transactional with its default DBAPI mode.
    with bind.begin_nested():
        _upgrade()


def _upgrade():
    json_type = sa.JSON().with_variant(JSONB, "postgresql")
    for column in [
        sa.Column("planned_start_date", sa.Date()),
        sa.Column("planned_end_date", sa.Date()),
        sa.Column("actual_start_at", sa.DateTime(timezone=True)),
        sa.Column("actual_end_at", sa.DateTime(timezone=True)),
        sa.Column("priority_override", sa.String(16)),
        sa.Column(
            "point_policy_version",
            sa.String(80),
            nullable=False,
            server_default="legacy",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    ]:
        _column("subtasks", column)
    for column, reference in [
        (
            sa.Column(
                "audit_schema_version", sa.Integer(), nullable=False, server_default="1"
            ),
            None,
        ),
        (sa.Column("tenant_id", UUID(as_uuid=True)), None),
        (sa.Column("task_id", sa.String(36)), ("tasks", "RESTRICT")),
        (sa.Column("subtask_id", sa.String(36)), ("subtasks", "RESTRICT")),
        (sa.Column("before", json_type), None),
        (sa.Column("after", json_type), None),
        (sa.Column("correlation_id", sa.String(128)), None),
    ]:
        _column("audit_events", column, reference)
    for column, reference in [
        (
            sa.Column(
                "record_version", sa.Integer(), nullable=False, server_default="1"
            ),
            None,
        ),
        (sa.Column("task_id", sa.String(36)), ("tasks", "RESTRICT")),
        (sa.Column("subtask_id", sa.String(36)), ("subtasks", "RESTRICT")),
        (sa.Column("component_type", sa.String(16)), None),
        (sa.Column("policy_version", sa.String(80)), None),
        (sa.Column("idempotency_key", sa.String(128)), None),
        (sa.Column("activity_event_id", sa.String(36)), ("audit_events", "RESTRICT")),
        (sa.Column("reason", sa.Text()), None),
        (sa.Column("reversal_of_id", UUID(as_uuid=True)), ("xp_ledger", "RESTRICT")),
    ]:
        _column("xp_ledger", column, reference)

    # The ORM has already been loaded by Alembic env.py (or the test harness).
    # Reuse the same table/guard definitions without importing another app engine.
    models = sys.modules.get("app.models") or sys.modules.get("backend.app.models")
    if models is None:
        raise RuntimeError("Load existing ORM metadata before task audit migration")
    # Frozen table definitions: never copy a future ORM revision into an old migration.
    tables = {
        "task_workflow_settings": [
            sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column(
                "point_policy_version",
                sa.String(80),
                primary_key=True,
                nullable=False,
                server_default="legacy",
            ),
            sa.Column("activated_at", sa.DateTime(timezone=True)),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.CheckConstraint(
                "version >= 1", name="ck_task_workflow_settings_version"
            ),
            sa.CheckConstraint(
                "NOT enabled OR (activated_at IS NOT NULL AND point_policy_version <> 'legacy')",
                name="ck_task_workflow_settings_activation",
            ),
            sa.CheckConstraint(
                "length(trim(point_policy_version)) > 0",
                name="ck_task_workflow_settings_policy",
            ),
        ],
        "task_work_intervals": [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
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
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "created_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("note", sa.Text()),
            sa.Column(
                "activity_event_id",
                sa.String(36),
                sa.ForeignKey("audit_events.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("request_id", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "ended_at > started_at", name="ck_task_work_intervals_positive"
            ),
            sa.UniqueConstraint(
                "tenant_id", "request_id", name="uq_task_work_intervals_request"
            ),
        ],
    }
    for name, definitions in tables.items():
        if name not in sa.inspect(op.get_bind()).get_table_names():
            op.create_table(name, *definitions)
        else:
            expected = [c for c in definitions if isinstance(c, sa.Column)]
            actual = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(name)}
            if actual != {c.name for c in expected}:
                raise RuntimeError(
                    f"Refusing incompatible adopted workflow table: {name}"
                )
            for column in expected:
                _column(name, column)
                for fk in column.foreign_keys:
                    target, target_column = fk.target_fullname.split(".")
                    existing_fks = sa.inspect(op.get_bind()).get_foreign_keys(name)
                    if not any(
                        item["constrained_columns"] == [column.name]
                        and item["referred_table"] == target
                        and item["referred_columns"] == [target_column]
                        for item in existing_fks
                    ):
                        raise RuntimeError(
                            f"Refusing missing workflow relationship: {name}.{column.name}"
                        )
            expected_pk = [c.name for c in expected if c.primary_key]
            if (
                sa.inspect(op.get_bind()).get_pk_constraint(name)["constrained_columns"]
                != expected_pk
            ):
                raise RuntimeError(
                    f"Refusing incompatible workflow primary key: {name}"
                )
            checks = {
                c["name"] for c in sa.inspect(op.get_bind()).get_check_constraints(name)
            }
            if not {
                c.name for c in definitions if isinstance(c, sa.CheckConstraint)
            }.issubset(checks):
                raise RuntimeError(
                    f"Refusing missing workflow check constraints: {name}"
                )
    indexes = [
        (
            "tasks",
            "ix_tasks_assignee_status_updated",
            ["assigned_to_id", "status", "updated_at"],
            False,
        ),
        ("tasks", "ix_tasks_creator_status", ["created_by_id", "status"], False),
        ("subtasks", "ix_subtasks_task_completed", ["task_id", "completed"], False),
        (
            "subtasks",
            "ix_subtasks_task_policy",
            ["task_id", "point_policy_version"],
            False,
        ),
        (
            "audit_events",
            "ix_audit_events_tenant_task_time",
            ["tenant_id", "task_id", "created_at", "id"],
            False,
        ),
        (
            "audit_events",
            "ix_audit_events_tenant_subtask_time",
            ["tenant_id", "subtask_id", "created_at", "id"],
            False,
        ),
        (
            "audit_events",
            "ix_audit_events_tenant_type_time",
            ["tenant_id", "event_type", "created_at", "id"],
            False,
        ),
        (
            "audit_events",
            "ix_audit_events_tenant_correlation",
            ["tenant_id", "correlation_id"],
            False,
        ),
        (
            "xp_ledger",
            "uq_xp_ledger_tenant_idempotency",
            ["tenant_id", "idempotency_key"],
            True,
        ),
        ("xp_ledger", "uq_xp_ledger_reversal", ["tenant_id", "reversal_of_id"], True),
        (
            "xp_ledger",
            "ix_xp_ledger_tenant_user_time",
            ["tenant_id", "user_id", "created_at", "id"],
            False,
        ),
        (
            "xp_ledger",
            "ix_xp_ledger_tenant_task_time",
            ["tenant_id", "task_id", "created_at", "id"],
            False,
        ),
        ("xp_ledger", "ix_xp_ledger_event", ["activity_event_id"], False),
        (
            "task_work_intervals",
            "uq_task_work_intervals_request",
            ["tenant_id", "request_id"],
            True,
        ),
        (
            "task_work_intervals",
            "ix_task_work_intervals_tenant_task_time",
            ["tenant_id", "task_id", "started_at", "id"],
            False,
        ),
        (
            "task_work_intervals",
            "ix_task_work_intervals_tenant_user_time",
            ["tenant_id", "user_id", "started_at", "id"],
            False,
        ),
    ]
    for table, name, columns, unique in indexes:
        _index(table, name, columns, unique)
    name = "uq_task_workflow_settings_active_tenant"
    active_index = next(
        (
            index
            for index in sa.inspect(op.get_bind()).get_indexes("task_workflow_settings")
            if index["name"] == name
        ),
        None,
    )
    if active_index:
        predicate = str(
            active_index.get("dialect_options", {}).get(
                op.get_bind().dialect.name + "_where", ""
            )
        ).strip("() ")
        if (
            active_index["column_names"] != ["tenant_id"]
            or not active_index["unique"]
            or predicate not in {"enabled", "enabled = 1"}
        ):
            raise RuntimeError("Refusing incompatible active policy uniqueness index")
    else:
        op.create_index(
            name,
            "task_workflow_settings",
            ["tenant_id"],
            unique=True,
            sqlite_where=sa.text("enabled = 1"),
            postgresql_where=sa.text("enabled"),
        )
    for statement in models.task_audit_guard_statements_v1(op.get_bind().dialect.name):
        op.execute(sa.text(statement))


def downgrade():
    raise RuntimeError(
        "Additive audit history is not destructively downgraded; retain schema or restore a verified backup"
    )
