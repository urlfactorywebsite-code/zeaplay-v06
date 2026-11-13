"""Durable session families, rotation history and user security epoch.

PostgreSQL only. Apply explicitly with Alembic, never via runtime schema repair.
Downgrade is for disposable verification only: it destroys revocation history.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "l2b4d6f8a0c2"
down_revision = "k1a3c5e7f9b1"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Durable authentication requires PostgreSQL")
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    op.add_column("users", sa.Column("auth_epoch", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_users_auth_epoch", "users", "auth_epoch >= 0")
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth_epoch", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.String(64)),
        sa.CheckConstraint("auth_epoch >= 0", name="ck_auth_sessions_epoch"),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_sessions_lifetime"))
    op.create_index("ix_auth_sessions_user_revoked", "auth_sessions", ["user_id", "revoked_at"])
    op.create_index("ix_auth_sessions_retention", "auth_sessions", ["expires_at", "id"])
    op.create_table("auth_refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("digest", sa.String(64), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by", sa.String(36)))
    op.create_index("ix_auth_refresh_session", "auth_refresh_tokens", ["session_id"])
    op.execute("""
        CREATE FUNCTION zea_invalidate_auth_sessions() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE reason text;
        BEGIN
          IF NEW.auth_epoch < OLD.auth_epoch THEN
            RAISE EXCEPTION 'Authentication epoch cannot decrease';
          END IF;
          reason := CASE
            WHEN NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN 'tenant_change'
            WHEN NEW.hashed_password IS DISTINCT FROM OLD.hashed_password THEN 'password_change'
            WHEN NEW.status IS DISTINCT FROM OLD.status THEN 'status_change'
            WHEN NEW.role IS DISTINCT FROM OLD.role THEN 'role_change'
            WHEN NEW.auth_epoch > OLD.auth_epoch THEN 'security_invalidation'
            ELSE NULL END;
          IF reason IS NOT NULL THEN
            NEW.auth_epoch := GREATEST(NEW.auth_epoch, OLD.auth_epoch + 1);
            UPDATE auth_sessions SET revoked_at = clock_timestamp(), revocation_reason = reason
              WHERE user_id = OLD.id AND revoked_at IS NULL;
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""CREATE TRIGGER zea_user_auth_invalidation
        BEFORE UPDATE OF tenant_id, hashed_password, status, role, auth_epoch ON users
        FOR EACH ROW EXECUTE FUNCTION zea_invalidate_auth_sessions()""")


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DROP TRIGGER zea_user_auth_invalidation ON users")
    op.execute("DROP FUNCTION zea_invalidate_auth_sessions()")
    op.drop_table("auth_refresh_tokens")
    op.drop_table("auth_sessions")
    op.drop_constraint("ck_users_auth_epoch", "users", type_="check")
    op.drop_column("users", "auth_epoch")
