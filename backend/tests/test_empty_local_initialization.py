"""Real PostgreSQL checks restricted to a newly owned initializer-test database."""
import os
import pytest
import sqlalchemy as sa

from backend.checks import initialize_empty_local as bootstrap


@pytest.fixture
def empty_database():
    raw = os.environ.get('ZEA_EMPTY_INIT_TEST_URL')
    run = os.environ.get('ZEA_EMPTY_INIT_RUN', '')
    if not raw:
        pytest.skip('Requires the owned disposable PostgreSQL initializer fixture')
    url = sa.engine.make_url(raw)
    assert len(run) == 32 and url.host == '127.0.0.1' and url.username == 'zea_init_test' and url.database == 'zea_init_' + run
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        assert not sa.inspect(connection).get_table_names()
    yield engine
    # This fixture name is an exact run-owned UUID, never an installed DB.
    with engine.begin() as connection:
        assert connection.scalar(sa.text('SELECT current_database()')) == 'zea_init_' + run
        connection.exec_driver_sql('DROP SCHEMA public CASCADE')
        connection.exec_driver_sql('CREATE SCHEMA public')
    engine.dispose()


def test_initialization_includes_workflow_and_auth_guards(empty_database):
    core = bootstrap.models()
    before = {name: set(table.c.keys()) for name, table in core.Base.metadata.tables.items()}
    with empty_database.begin() as connection:
        result = bootstrap.initialize(connection)
        assert result == {'initialized':True,'revisions_reused':9,'alembic_stamped':False,'mcp_enabled':False}
        assert connection.scalar(sa.text('SELECT count(*) FROM users')) == 0
        assert 'alembic_version' not in sa.inspect(connection).get_table_names()
        assert not any(name.startswith('mcp_') for name in sa.inspect(connection).get_table_names())
    assert before == {name: set(table.c.keys()) for name, table in core.Base.metadata.tables.items()}
    from backend.app.services.auth_sessions import require_session_schema
    from backend.app.services.audit_security import require_audit_schema
    require_session_schema(empty_database)
    require_audit_schema(empty_database)
    with pytest.raises(RuntimeError, match='contains application objects'), empty_database.begin() as connection:
        bootstrap.initialize(connection)


def test_existing_data_refused_and_preserved(empty_database):
    with empty_database.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE keep_data (value text)")
        connection.exec_driver_sql("INSERT INTO keep_data VALUES ('keep-fixture')")
    with pytest.raises(RuntimeError, match='contains application objects'), empty_database.begin() as connection:
        bootstrap.initialize(connection)
    with empty_database.connect() as connection:
        assert connection.scalar(sa.text('SELECT value FROM keep_data')) == 'keep-fixture'
        assert sa.inspect(connection).get_table_names() == ['keep_data']


@pytest.mark.parametrize('fail_after', [bootstrap.REVISIONS[0], bootstrap.REVISIONS[-1]])
def test_interrupted_initialization_rolls_back_everything(empty_database, fail_after):
    def stop(name):
        if name == fail_after:
            raise RuntimeError('Owned rollback probe')
    with pytest.raises(RuntimeError, match='Owned rollback probe'), empty_database.begin() as connection:
        bootstrap.initialize(connection, after_revision=stop)
    with empty_database.connect() as connection:
        assert sa.inspect(connection).get_table_names() == []
