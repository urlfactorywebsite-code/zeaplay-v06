import importlib
import io
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

TENANT_A = uuid.UUID('a1111111-1111-4111-8111-111111111111')
TENANT_B = uuid.UUID('b2222222-2222-4222-8222-222222222222')


@pytest.mark.parametrize('tenant_count', [1, 2])
def test_migration_preserves_legacy_secrets_and_only_backfills_unambiguous_owner(monkeypatch, tmp_path, tenant_count):
    # Optional PostgreSQL URL must point at the disposable review database.
    url = os.getenv('ZEA_REVIEW_POSTGRES_URL') or f"sqlite:///{tmp_path / 'migration.db'}"
    if os.getenv('ZEA_REVIEW_POSTGRES_URL'):
        target = sa.engine.make_url(url)
        if target.host != '127.0.0.1' or target.database != 'zea_review' or target.username != 'zea_review':
            raise RuntimeError('PostgreSQL checks require the disposable local zea_review database')
    engine = sa.create_engine(url)
    schema = f'nav_review_{uuid.uuid4().hex}' if engine.dialect.name == 'postgresql' else None
    metadata = sa.MetaData()
    sa.Table('users', metadata, sa.Column('id', sa.String, primary_key=True), sa.Column('tenant_id', sa.UUID))
    for name in ('api_config', 'smtp_config', 'multiple_smtp_configs', 'oauth_config'):
        sa.Table(name, metadata, sa.Column('id', sa.Integer, primary_key=True), sa.Column('secret_fixture', sa.String))
    sa.Table('email_templates', metadata, sa.Column('id', sa.String, primary_key=True), sa.Column('notification_type', sa.String, unique=True), sa.Column('body', sa.String))
    module = importlib.import_module('backend.alembic.versions.b2c4d6e8f0a2_scope_api_settings')
    try:
        with engine.begin() as conn:
            if schema:
                conn.execute(sa.text(f'CREATE SCHEMA {schema}'))
                conn.execute(sa.text(f'SET search_path TO {schema}'))
            metadata.create_all(conn)
            conn.execute(metadata.tables['users'].insert(), [{'id': 'a', 'tenant_id': TENANT_A}] + ([{'id': 'b', 'tenant_id': TENANT_B}] if tenant_count == 2 else []))
            for name in ('api_config', 'smtp_config', 'multiple_smtp_configs', 'oauth_config'):
                conn.execute(metadata.tables[name].insert(), {'id': 7, 'secret_fixture': 'preserved-fixture'})
            conn.execute(metadata.tables['email_templates'].insert(), {'id': 'legacy', 'notification_type': 'system', 'body': 'preserved-fixture'})
            monkeypatch.setattr(module, 'op', Operations(MigrationContext.configure(conn)))
            monkeypatch.setattr(module.context, 'is_offline_mode', lambda: False)
            navigation = importlib.import_module('backend.alembic.versions.a8d6e4f2c0b1_add_navigation_policies')
            monkeypatch.setattr(navigation, 'op', Operations(MigrationContext.configure(conn)))
            navigation.upgrade()
            module.upgrade()
            assert 'navigation_policies' in sa.inspect(conn).get_table_names()
            for name in module.TABLES:
                rows = conn.execute(sa.text(f'SELECT * FROM {name}')).mappings().all()
                assert len(rows) == 1
                assert rows[0]['tenant_id'] == (str(TENANT_A) if tenant_count == 1 else None)
                assert 'preserved-fixture' in rows[0].values()
            conn.execute(sa.text("INSERT INTO email_templates(id,notification_type,body,tenant_id) VALUES ('new-b','system','fixture',:tenant)"), {'tenant': str(TENANT_B)})
            if schema:
                # The singleton sequence must advance past preserved IDs.
                conn.execute(sa.text("INSERT INTO api_config(secret_fixture,tenant_id) VALUES ('new-fixture',:tenant)"), {'tenant': str(TENANT_B)})
                assert conn.execute(sa.text('SELECT MAX(id) FROM api_config')).scalar_one() > 7
    finally:
        if schema:
            with engine.begin() as conn:
                conn.execute(sa.text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        engine.dispose()


def test_postgres_offline_migration_sql_and_destructive_downgrade_guard(monkeypatch):
    module = importlib.import_module('backend.alembic.versions.b2c4d6e8f0a2_scope_api_settings')
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': buffer})
    monkeypatch.setattr(module, 'op', Operations(context))
    monkeypatch.setattr(module.context, 'is_offline_mode', lambda: True)
    module.upgrade()
    assert 'ADD COLUMN tenant_id' in buffer.getvalue() and 'COUNT(DISTINCT tenant_id)' in buffer.getvalue()
    with pytest.raises(RuntimeError, match='Restore a verified backup'):
        module.downgrade()


@pytest.mark.parametrize('bootstrapped', [False, True])
def test_fresh_and_already_bootstrapped_installations_migrate(monkeypatch, tmp_path, bootstrapped):
    from backend.app import models
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    module = importlib.import_module('backend.alembic.versions.b2c4d6e8f0a2_scope_api_settings')
    with engine.begin() as conn:
        conn.execute(sa.text('CREATE TABLE users(id VARCHAR PRIMARY KEY, tenant_id VARCHAR)'))
        if bootstrapped:
            for model in (models.ApiConfig, models.SmtpConfig, models.MultipleSmtpConfig, models.EmailTemplate, models.OAuthConfig):
                model.__table__.create(conn)
        monkeypatch.setattr(module, 'op', Operations(MigrationContext.configure(conn)))
        monkeypatch.setattr(module.context, 'is_offline_mode', lambda: False)
        module.upgrade()
        for table in module.TABLES:
            assert 'tenant_id' in {column['name'] for column in sa.inspect(conn).get_columns(table)}
    engine.dispose()
