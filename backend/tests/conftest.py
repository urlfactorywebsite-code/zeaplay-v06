"""SQLite DDL compatibility shared by the repository's disposable tests.

SQLite task search uses ILIKE. Registering this deterministic function only
allows the PostgreSQL-generated search column to exist in SQLite fixtures; it
does not emulate or certify PostgreSQL full-text search behavior.
"""
import sqlite3
import sys

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine


@event.listens_for(Engine, "connect")
def sqlite_generated_search_column(connection, _record):
    if isinstance(connection, sqlite3.Connection):
        connection.create_function("to_tsvector", 2, lambda _language, value: value, deterministic=True)


@pytest.fixture(autouse=True)
def explicit_test_lifecycle(monkeypatch):
    """Legacy TestClients must not launch installed seeding/maintenance workers.

    Each API test owns its schema and fixtures. Startup/worker behavior is
    exercised explicitly by the migration, maintenance and realtime suites.
    """
    main = sys.modules.get("backend.app.main")
    if main is not None:
        monkeypatch.setattr(main.app.router, "on_startup", [])
        monkeypatch.setattr(main.app.router, "on_shutdown", [])
