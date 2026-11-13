"""Immutable event-time audit ownership; legacy records remain unattributed.

Explicit deployment migration only. Never backfill using an actor's current
tenant. Downgrade destroys attribution and is for disposable rehearsal only.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "m3c5e7f9a1d3"
down_revision = "l2b4d6f8a0c2"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Audit attribution requires PostgreSQL")
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    op.add_column("audit_logs", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_audit_logs_tenant_created", "audit_logs", ["tenant_id", "created_at"])
    op.execute("""CREATE FUNCTION zea_audit_tenant_immutable() RETURNS trigger AS $$
    BEGIN
      IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
        RAISE EXCEPTION 'Audit tenant attribution is immutable';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER audit_tenant_immutable BEFORE UPDATE ON audit_logs "
               "FOR EACH ROW EXECUTE FUNCTION zea_audit_tenant_immutable()")


def downgrade():
    op.execute("DROP TRIGGER audit_tenant_immutable ON audit_logs")
    op.execute("DROP FUNCTION zea_audit_tenant_immutable()")
    op.drop_index("ix_audit_logs_tenant_created", table_name="audit_logs")
    op.drop_column("audit_logs", "tenant_id")
