"""Final review regressions over actual HTTP guards and durable SQL state."""
# ruff: noqa: F811 -- shared isolated fixtures
import os
from time import perf_counter

import pytest
import redis
import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.app import cache
from backend.app import models as m
from backend.app.routers import tasks
from backend.tests.test_phase7_system import login, ok, parent, system  # noqa: F401
from backend.tests.test_task_audit_foundation import engine, harness  # noqa: F401


class UnavailableCache:
    def get(self, *_):
        raise redis.ConnectionError("synthetic private cache URL")

    def setex(self, *_):
        raise redis.ConnectionError("synthetic private cache URL")

    def scan_iter(self, **_):
        raise redis.ConnectionError("synthetic private cache URL")


def test_cache_outage_preserves_committed_http_success_and_db_reads(system, monkeypatch, caplog):
    client, engine, _ = system
    owner = login(client)
    task = parent(client, owner, count=0)
    monkeypatch.setattr(cache, "_get_client", lambda: UnavailableCache())
    for name in ("get_cached_json", "set_cached_json", "invalidate_prefix"):
        monkeypatch.setattr(tasks, name, getattr(cache, name))
    changed = ok(client, "PATCH", f"/api/tasks/{task['id']}", owner, json={"title": "Committed during cache outage"})
    assert changed["title"] == "Committed during cache outage"
    page = ok(client, "GET", "/api/tasks/page", owner)
    assert task["id"] in {row["id"] for row in page["items"]}
    with Session(engine) as db:
        assert db.get(m.Task, task["id"]).title == changed["title"]
    assert "synthetic private cache URL" not in caplog.text


@pytest.mark.parametrize("path", ["/api/tasks/page", "/api/tasks/kanban", "/api/tasks/calendar/summary?start_date=2026-11-04&end_date=2026-11-04"])
@pytest.mark.parametrize("role", [m.RoleEnum.USER, m.RoleEnum.MANAGER])
def test_removed_watcher_cannot_replay_cached_task_or_aggregate_data(system, monkeypatch, path, role):
    client, engine, _ = system
    with Session(engine) as db:
        db.get(m.User, "watcher").role = role
        db.commit()
    owner, watcher = login(client), login(client, "watcher")
    task = parent(client, owner, count=0)
    if "kanban" in path:
        with Session(engine) as db:
            db.add(m.KanbanColumn(id="TODO", title="TODO", order=0))
            db.commit()
    cached = ok(client, "GET", path, watcher)
    assert task["id"] in str(cached) or ("days" in cached and cached["days"][0]["total"] == 1)
    with Session(engine) as db:
        db.get(m.Task, task["id"]).followers = []
        db.commit()
    # Simulate missed invalidation or a previously connected Redis cache after an outage.
    monkeypatch.setattr(tasks, "get_cached_json", lambda *_: cached)
    fresh = ok(client, "GET", path, watcher)
    assert task["id"] not in str(fresh)
    if "days" in fresh:
        assert fresh["days"][0]["total"] == 0


def test_cache_invalidation_is_bounded_and_json_corruption_is_a_miss(monkeypatch):
    class Cached:
        def __init__(self):
            self.batches = []

        def get(self, _):
            return "not-json"

        def scan_iter(self, **kwargs):
            assert kwargs == {"match": "scoped:*", "count": 100}
            return iter(f"scoped:{i}" for i in range(1001))

        def delete(self, *keys):
            self.batches.append(keys)

    cached = Cached()
    monkeypatch.setattr(cache, "_get_client", lambda: cached)
    assert cache.get_cached_json("scoped:bad") is None
    cache.invalidate_prefix("scoped:")
    assert [len(batch) for batch in cached.batches] == [100] * 10 + [1]
    assert len({key for batch in cached.batches for key in batch}) == 1001


def test_cache_outage_warnings_are_bounded_and_sanitized(monkeypatch, caplog):
    monkeypatch.setattr(cache, "_get_client", lambda: UnavailableCache())
    monkeypatch.setattr(cache, "_last_warning", float("-inf"))
    for _ in range(100):
        assert cache.get_cached_json("private-key") is None
        cache.set_cached_json("private-key", {}, ttl_seconds=10)
        cache.invalidate_prefix("private-key")
    assert caplog.text.count("Cache unavailable") == 1
    assert "private-key" not in caplog.text and "synthetic private" not in caplog.text


@pytest.mark.parametrize("role", [m.RoleEnum.OWNER, m.RoleEnum.ADMIN])
def test_owner_cache_is_retained_with_tenant_and_user_scoping(system, monkeypatch, role):
    client, engine, _ = system
    with Session(engine) as db:
        db.get(m.User, "owner").role = role
        db.commit()
    owner = login(client)
    expected = ok(client, "GET", "/api/tasks/page", owner)
    keys = []

    def cached(key):
        keys.append(key)
        return expected

    monkeypatch.setattr(tasks, "get_cached_json", cached)
    assert ok(client, "GET", "/api/tasks/page", owner) == expected
    assert len(keys) == 1 and ":tenant:" in keys[0] and ":user:owner:" in keys[0]


def test_member_page_queries_remain_bounded_without_acl_cache(system, record_property):
    client, engine, _ = system
    worker = login(client, "worker")
    with engine.begin() as connection:
        connection.execute(sa.insert(m.Task), [
            {"id": f"member-{i}", "title": f"Task {i}", "created_by_id": "owner", "assigned_to_id": "worker"}
            for i in range(250)
        ])
    statements = []

    def capture(_conn, _cursor, statement, *_):
        statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", capture)
    started = perf_counter()
    try:
        page = ok(client, "GET", "/api/tasks/page?page_size=25", worker)
    finally:
        elapsed = perf_counter() - started
        sa.event.remove(engine, "before_cursor_execute", capture)
    assert len(page["items"]) == 25 and page["total"] >= 250
    assert len(statements) <= 20
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
    record_property("member_page_profile", {"rows": 250, "page": 25, "queries": len(statements), "seconds": elapsed})


def test_stopped_real_redis_preserves_http_mutation_and_read(system, monkeypatch):
    url = os.getenv("ZEA_FINAL_OFFLINE_REDIS_URL")
    if not url:
        pytest.skip("Run only while the explicitly owned disposable Redis server is stopped")
    assert url == "redis://127.0.0.1:16379/15"
    real_client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1, retry=redis.retry.Retry(redis.backoff.NoBackoff(), 0))
    with pytest.raises(redis.RedisError):
        real_client.ping()
    monkeypatch.setattr(cache, "_get_client", lambda: real_client)
    client, engine, _ = system
    owner = login(client)
    task = parent(client, owner, count=0)
    for name in ("get_cached_json", "set_cached_json", "invalidate_prefix"):
        monkeypatch.setattr(tasks, name, getattr(cache, name))
    started = perf_counter()
    ok(client, "PATCH", f"/api/tasks/{task['id']}", owner, json={"title": "Real Redis offline"})
    page = ok(client, "GET", "/api/tasks/page", owner)
    assert task["id"] in {row["id"] for row in page["items"]}
    with Session(engine) as db:
        assert db.get(m.Task, task["id"]).title == "Real Redis offline"
    assert perf_counter() - started < 10
    real_client.close()
