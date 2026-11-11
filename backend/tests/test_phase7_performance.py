"""Bounded, read-only aggregation profiles; timings are not production SLAs."""
# ruff: noqa: F811 -- shared disposable fixtures
import json
import time
import tracemalloc
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.app import models as m
from backend.app.services import task_information
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401


@pytest.mark.parametrize("history_size", [100, 5000])
def test_activity_history_pagination_query_count_and_memory(harness, history_size, record_property):
    engine, _, _ = harness
    now = datetime(2026, 11, 2, 12, tzinfo=UTC)
    with Session(engine) as db:
        db.execute(sa.insert(m.AuditEvent), [{
            "id": f"profile-event-{index:06d}", "actor_id": "owner",
            "event_type": "task.updated", "entity_type": "task", "entity_id": "task",
            "created_at": now + timedelta(seconds=index), "payload": {"status": "TODO"},
        } for index in range(history_size)])
        db.commit()
    statements = []

    def track(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    sa.event.listen(engine, "before_cursor_execute", track)
    tracemalloc.start()
    started = time.perf_counter()
    try:
        with Session(engine) as db:
            result = task_information.read(db, task_id="task", who=db.get(m.User, "owner"),
                                           section="activity", page=2, size=25)
        seconds = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        sa.event.remove(engine, "before_cursor_execute", track)
    assert result["total"] == history_size and len(result["items"]) == 25
    assert statements and set(statements) <= {"SELECT"}
    # This catches one SELECT per history item while allowing bounded role/tenant reads.
    assert len(statements) <= 30
    record_property("history_profile", json.dumps({"rows": history_size, "page_size": 25,
                    "queries": len(statements), "writes": 0, "seconds": round(seconds, 4),
                    "python_peak_bytes": peak, "dialect": engine.dialect.name}))
