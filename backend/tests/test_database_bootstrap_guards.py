"""Import-time compatibility helpers must not bootstrap an empty installation."""
import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from backend.app import database


@pytest.fixture
def isolated_database(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('PRAGMA foreign_keys=ON'))
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(database, 'is_sqlite', True)
    yield engine
    engine.dispose()


@pytest.mark.parametrize('parents', [(), ('tasks',), ('users',)])
def test_missing_parents_never_attempt_follower_ddl(isolated_database, parents):
    engine = isolated_database
    with engine.begin() as connection:
        for parent in parents:
            connection.execute(text(f'CREATE TABLE {parent} (id VARCHAR(36) PRIMARY KEY)'))
    statements = []
    event.listen(engine, 'before_cursor_execute', lambda connection, cursor, statement, *args: statements.append(statement))
    database._ensure_task_followers_table()
    assert set(inspect(engine).get_table_names()) == set(parents)
    assert not any(statement.lstrip().upper().startswith(('CREATE ', 'ALTER ', 'INSERT ')) for statement in statements)


def test_existing_core_retains_follower_setup_integrity_and_rows(isolated_database):
    engine = isolated_database
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE tasks (id VARCHAR(36) PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)'))
        connection.execute(text("INSERT INTO tasks VALUES ('task-fixture')"))
        connection.execute(text("INSERT INTO users VALUES ('user-fixture')"))
    database._ensure_task_followers_table()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO task_followers VALUES ('task-fixture','user-fixture',CURRENT_TIMESTAMP)"))
    database._ensure_task_followers_table()
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM task_followers')) == 1
        assert 'ix_task_followers_user_id' in {index['name'] for index in inspect(connection).get_indexes('task_followers')}
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("INSERT INTO task_followers VALUES ('absent-task','user-fixture',CURRENT_TIMESTAMP)"))
