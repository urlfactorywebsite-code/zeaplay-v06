"""Tenant navigation policy; additive, no application data changes."""
from alembic import op
import sqlalchemy as sa

revision = "a8d6e4f2c0b1"
down_revision = "9c8d7e6f5a4b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("navigation_policies",
        sa.Column("tenant_id", sa.String(36), primary_key=True),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("navigation_policies")
