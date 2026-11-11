"""Actual disposable Redis recovery and scoped resync; no installed services."""
import asyncio
import json
import os
import threading
import uuid
from types import SimpleNamespace

import pytest
import redis

from backend.app.services import task_events as events
from backend.app.ws import tasks as sockets


def test_failed_publication_does_not_turn_a_committed_mutation_into_http_failure(monkeypatch, caplog):
    class Unavailable:
        def publish(self, *_):
            raise redis.ConnectionError("synthetic private transport detail")

    monkeypatch.setattr(events, "get_redis_client", lambda: Unavailable())
    events.publish_task_event({"type": "work.changed", "tenant_id": "private-tenant"})
    assert "publication unavailable" in caplog.text
    assert "private-tenant" not in caplog.text and "private transport" not in caplog.text


def test_recovery_resync_is_authorized_scoped_and_contains_no_domain_data(monkeypatch):
    manager = sockets.TaskConnectionManager()
    monkeypatch.setattr(sockets, "manager", manager)
    monkeypatch.setattr(sockets, "_delivery_allowed", lambda socket, _: socket.permitted)

    class Socket:
        def __init__(self, tenant, permitted=True):
            self.state = SimpleNamespace(navigation_identity=("user-" + tenant, tenant))
            self.permitted, self.closed, self.messages = permitted, False, []

        async def accept(self):
            pass

        async def send_json(self, message):
            self.messages.append(message)

        async def close(self, **_):
            self.closed = True

    async def run():
        first, second, revoked = Socket("a"), Socket("b"), Socket("c", False)
        for tenant, socket in (("a", first), ("b", second), ("c", revoked)):
            await manager.connect(tenant, socket)
        await sockets.broadcast_task_resync()
        assert first.messages == [{"type": "tasks.resync", "tenant_id": "a"}]
        assert second.messages == [{"type": "tasks.resync", "tenant_id": "b"}]
        assert revoked.closed and not revoked.messages

    asyncio.run(run())


def test_real_redis_disconnect_resubscribe_burst_and_listener_restart(monkeypatch, record_property):
    url = os.getenv("ZEA_PHASE7_REDIS_URL")
    if not url:
        pytest.skip("Set the guarded owned Redis fixture URL to run transport recovery")
    assert url == "redis://127.0.0.1:16379/15", "Only the disposable Phase 7 Redis endpoint is permitted"
    client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
    assert client.ping()
    events.stop_task_event_listener()
    monkeypatch.setattr(events, "get_redis_client", lambda: client)
    monkeypatch.setattr(events, "TASK_EVENT_CHANNEL", "zea-phase7:" + uuid.uuid4().hex)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    subscribed, recovered, complete = threading.Event(), threading.Event(), threading.Event()
    counts = {"subscriptions": 0, "active": 0, "max_active": 0}
    seen = []

    async def resync():
        counts["subscriptions"] += 1
        (subscribed if counts["subscriptions"] == 1 else recovered).set()

    async def handler(payload):
        if payload.get("synthetic_timeout"):
            raise TimeoutError("synthetic handler timeout")
        counts["active"] += 1
        counts["max_active"] = max(counts["max_active"], counts["active"])
        try:
            await asyncio.sleep(0.002)
            seen.append(payload["index"])
            if len(seen) == 100:
                complete.set()
        finally:
            counts["active"] -= 1

    try:
        events.start_task_event_listener(loop=loop, handler=handler, on_reconnect=resync)
        assert subscribed.wait(10)
        original = events._listener_thread
        events.start_task_event_listener(loop=loop, handler=handler, on_reconnect=resync)
        assert events._listener_thread is original
        client.execute_command("CLIENT", "KILL", "TYPE", "pubsub", "SKIPME", "yes")
        assert recovered.wait(15)
        for value in ("not-json", "[]", "null"):
            client.publish(events.TASK_EVENT_CHANNEL, value)
        for index in range(100):
            events.publish_task_event({"index": index, "tenant_id": "synthetic"})
        assert complete.wait(15)
        assert seen == list(range(100)) and counts["max_active"] == 1
        recovered.clear()
        events.publish_task_event({"synthetic_timeout": True})
        assert recovered.wait(10)  # a completed TimeoutError must reconnect, not busy-spin
        events.stop_task_event_listener()
        assert not original.is_alive() and events._listener_thread is None
        recovered.clear()
        events.start_task_event_listener(loop=loop, handler=handler, on_reconnect=resync)
        assert recovered.wait(10)
        record_property("redis_recovery", json.dumps({"events": len(seen), **counts, "listener_restarted": True}))
    finally:
        events.stop_task_event_listener()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()
        client.close()


def test_actual_startup_wires_the_shared_listener_recovery_callback(monkeypatch):
    from backend.app import main

    # Exercise only startup orchestration; schema, seeds and unrelated workers
    # have separate disposable tests and must not run against the global engine.
    for name in (
        "ensure_task_status_enum", "ensure_pg_trgm_extension", "ensure_reward_schema",
        "ensure_chat_schema", "normalize_legacy_task_status_values", "ensure_employer_id_column",
        "ensure_user_profile_columns", "ensure_media_file_columns", "ensure_webhook_schema",
        "seed_database", "seed_badges_from_achievements", "ensure_kanban_columns", "ensure_avatar_dirs",
        "start_webhook_retry_worker", "start_maintenance", "start_backup_maintenance",
    ):
        monkeypatch.setattr(main, name, lambda *a, **k: None)
    monkeypatch.setattr(main.Base.metadata, "create_all", lambda *a, **k: None)
    monkeypatch.setattr(main.chat_realtime, "start_chat_event_listener", lambda **k: None)
    calls = []
    monkeypatch.setattr(events, "start_task_event_listener", lambda **kwargs: calls.append(kwargs))

    async def run():
        main.startup_event()

    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0]["handler"] is sockets.broadcast_task_event
    assert calls[0]["on_reconnect"] is sockets.broadcast_task_resync
