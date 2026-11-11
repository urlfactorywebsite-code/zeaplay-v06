"""Add tenant-scoped backup jobs and export presets; no business-data changes."""

import sqlalchemy as sa
from alembic import op

revision = "d4f6a8b0c2e4"
down_revision = "c3e5f7a9b1d2"
branch_labels = None
depends_on = None


def _create_or_adopt(name, *columns):
    """Existing startup create_all may have already created compatible metadata."""
    inspector = sa.inspect(op.get_bind())
    if name not in inspector.get_table_names():
        op.create_table(name, *columns)
    else:
        existing = {column["name"]: column for column in inspector.get_columns(name)}
        compatible = set(existing) == {column.name for column in columns}
        for column in columns:
            actual = existing.get(column.name)
            if (
                not actual
                or not isinstance(actual["type"], type(column.type))
                or actual["nullable"] != column.nullable
            ):
                compatible = False
                break
            if (
                isinstance(column.type, sa.String)
                and (actual["type"].length or 0) < column.type.length
            ):
                compatible = False
                break
        if not compatible or inspector.get_pk_constraint(name)[
            "constrained_columns"
        ] != ["id"]:
            raise RuntimeError(f"Refusing incompatible backup metadata table: {name}")
    index_name = f"ix_{name}_tenant_id"
    indexes = {
        index["name"]: index for index in sa.inspect(op.get_bind()).get_indexes(name)
    }
    if index_name in indexes and indexes[index_name]["column_names"] != ["tenant_id"]:
        raise RuntimeError(f"Refusing incompatible backup metadata index: {index_name}")
    if index_name not in indexes:
        op.create_index(index_name, name, ["tenant_id"])


def upgrade():
    _create_or_adopt(
        "backup_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("error", sa.String(500)),
    )
    _create_or_adopt(
        "export_presets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("creator_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("export_presets")
    op.drop_table("backup_jobs")
