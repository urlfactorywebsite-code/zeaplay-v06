"""Extend canonical users and avatar assets without copying profile data."""

import sqlalchemy as sa
from alembic import op

revision = "c3e5f7a9b1d2"
down_revision = "b2c4d6e8f0a2"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table, columns in {
        "users": [sa.Column("profile_bio", sa.String(500), nullable=True)],
        "avatar_assets": [
            sa.Column("tenant_id", sa.Uuid(), nullable=True),
            sa.Column("storage_provider", sa.String(32), nullable=True),
            sa.Column("thumbnail_path", sa.String(500), nullable=True),
        ],
    }.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    if "ix_avatar_assets_tenant_id" not in {
        index["name"] for index in inspector.get_indexes("avatar_assets")
    }:
        op.create_index("ix_avatar_assets_tenant_id", "avatar_assets", ["tenant_id"])
    op.execute(
        sa.text("""UPDATE avatar_assets SET tenant_id =
        (SELECT tenant_id FROM users WHERE users.id = avatar_assets.created_by_id)
        WHERE tenant_id IS NULL AND created_by_id IS NOT NULL""")
    )


def downgrade():
    raise RuntimeError(
        "This additive migration preserves profile data; restore a verified backup to downgrade."
    )
