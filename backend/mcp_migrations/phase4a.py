"""Explicitly reviewed, additive DDL for an owned disposable database only.

This is deliberately outside the production Alembic revision chain. There is
no deployment/startup caller. Approval must name the exact SQL SHA-256.
"""
import hashlib
from pathlib import Path
from sqlalchemy import inspect, text

SQL = Path(__file__).with_suffix('.sql')


def apply_reviewed(connection, *, approved_sha256: str, owned_run_id: str):
    raw = SQL.read_bytes()
    if hashlib.sha256(raw).hexdigest() != approved_sha256:
        raise RuntimeError('Exact schema review approval is required')
    url = connection.engine.url
    if (connection.dialect.name != 'postgresql' or url.host != '127.0.0.1'
            or url.database != 'zea_phase2b' or url.username != 'zea_phase2b'
            or not owned_run_id or len(owned_run_id) != 32):
        raise RuntimeError('Only the disposable integration database is supported')
    if connection.scalar(text('SELECT run_id FROM phase2b_fixture_guard')) != owned_run_id:
        raise RuntimeError('Disposable database ownership attestation failed')
    if any(name.startswith('mcp_') for name in inspect(connection).get_table_names()):
        raise RuntimeError('Refusing existing MCP storage')
    # Called inside an explicit transaction. No existing-table DML, ALTER,
    # ownership backfill, broad DROP, or production migration is performed.
    connection.exec_driver_sql(raw.decode('utf-8'))
