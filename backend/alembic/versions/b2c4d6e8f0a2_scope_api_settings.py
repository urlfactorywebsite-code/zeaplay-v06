"""Scope existing API credential configuration to authenticated tenants.

Unowned legacy records are retained. Automatic ownership is safe only when the
database contains exactly one tenant. Multi-tenant ownership needs an explicit
operator mapping; no legacy secret is copied into another tenant.
"""
from alembic import context, op
import sqlalchemy as sa

revision = "b2c4d6e8f0a2"
down_revision = "a8d6e4f2c0b1"
branch_labels = None
depends_on = None
TABLES = ("api_config", "smtp_config", "multiple_smtp_configs", "email_templates", "oauth_config")


def legacy_tables():
    # These tables historically relied on application bootstrap rather than an
    # Alembic revision. Define their pre-tenant shape here so a fresh migration
    # also works without starting the application first.
    metadata = sa.MetaData()
    def times():
        return [sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False)]
    return [
        sa.Table('api_config', metadata, sa.Column('id', sa.Integer, primary_key=True), sa.Column('provider', sa.String(255), nullable=False), sa.Column('api_key', sa.String(255))),
        sa.Table('smtp_config', metadata, sa.Column('id', sa.Integer, primary_key=True), sa.Column('host', sa.String(255), nullable=False), sa.Column('port', sa.Integer, nullable=False), sa.Column('username', sa.String(255), nullable=False), sa.Column('password', sa.String(255)), sa.Column('encryption', sa.String(50), nullable=False)),
        sa.Table('multiple_smtp_configs', metadata, sa.Column('id', sa.String(36), primary_key=True), sa.Column('name', sa.String(255), nullable=False), sa.Column('host', sa.String(255), nullable=False), sa.Column('port', sa.Integer, nullable=False), sa.Column('username', sa.String(255), nullable=False), sa.Column('password', sa.String(255)), sa.Column('encryption', sa.String(50), nullable=False), sa.Column('notification_types', sa.JSON, nullable=False), *times()),
        sa.Table('email_templates', metadata, sa.Column('id', sa.String(36), primary_key=True), sa.Column('notification_type', sa.String(100), nullable=False, unique=True), sa.Column('subject', sa.String(255), nullable=False), sa.Column('body', sa.Text, nullable=False), *times()),
        sa.Table('oauth_config', metadata, sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(255), nullable=False), sa.Column('client_id', sa.String(255), nullable=False, unique=True), sa.Column('client_secret', sa.String(255), nullable=False), sa.Column('api_key', sa.String(255), unique=True), sa.Column('redirect_url', sa.String(500), nullable=False), sa.Column('scopes', sa.JSON, nullable=False), sa.Column('n8n_integration', sa.Boolean, nullable=False), *times()),
    ]


def upgrade():
    offline = context.is_offline_mode()
    bind = None if offline else op.get_bind()
    for table in legacy_tables():
        op.execute(sa.schema.CreateTable(table, if_not_exists=True))
    inspector = None if offline else sa.inspect(bind)
    for table in TABLES:
        if offline or "tenant_id" not in {column['name'] for column in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
        if offline or f"ix_{table}_tenant_id" not in {index['name'] for index in inspector.get_indexes(table)}:
            op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"], unique=table in ("api_config", "smtp_config"))
    # Composite uniqueness preserves independent templates with the same type.
    if offline:
        op.drop_constraint("email_templates_notification_type_key", "email_templates", type_="unique")
        op.create_unique_constraint("uq_email_template_tenant_type", "email_templates", ["tenant_id", "notification_type"])
    else:
        constraints = inspector.get_unique_constraints("email_templates")
        with op.batch_alter_table("email_templates", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}) as batch:
            for constraint in constraints:
                if constraint["column_names"] == ["notification_type"]:
                    batch.drop_constraint(constraint["name"] or "uq_email_templates_notification_type", type_="unique")
            if not any(constraint['column_names'] == ['tenant_id', 'notification_type'] for constraint in constraints):
                batch.create_unique_constraint("uq_email_template_tenant_type", ["tenant_id", "notification_type"])
    if offline or bind.dialect.name == "postgresql":
        for table in TABLES:
            op.execute(sa.text(f"""UPDATE {table} SET tenant_id =
                (SELECT MIN(tenant_id::text) FROM users WHERE tenant_id IS NOT NULL)
                WHERE tenant_id IS NULL AND (SELECT COUNT(DISTINCT tenant_id) FROM users) = 1"""))
        for table in ("api_config", "smtp_config"):
            op.execute(sa.text(f"""SELECT setval(pg_get_serial_sequence('{table}', 'id'),
                GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 1), 1), true)"""))
    else:
        tenants = bind.execute(sa.text("SELECT DISTINCT tenant_id FROM users WHERE tenant_id IS NOT NULL")).scalars().all()
        if len(tenants) == 1:
            # Existing SQLite UUID columns use hex storage; new tenant IDs use
            # the same canonical hyphenated representation as authentication.
            import uuid
            tenant = str(uuid.UUID(str(tenants[0])))
            for table in TABLES:
                bind.execute(sa.text(f"UPDATE {table} SET tenant_id=:tenant WHERE tenant_id IS NULL"), {"tenant": tenant})


def downgrade():
    # Tenant-owned secrets cannot safely collapse into a shared global store.
    # A destructive downgrade would violate isolation and template uniqueness.
    raise RuntimeError("Restore a verified backup or explicitly reconcile tenant configuration before downgrade.")
