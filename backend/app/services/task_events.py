import asyncio
import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from ..cache import get_cache_prefix, get_redis_client

TASK_EVENT_CHANNEL = f"{get_cache_prefix()}:tasks:events"

_listener_thread: threading.Thread | None = None
_stop_event = threading.Event()
_pubsub = None
_listener_lock = threading.Lock()
log = logging.getLogger(__name__)


def publish_task_event(payload: dict[str, Any]) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        client.publish(TASK_EVENT_CHANNEL, json.dumps(payload))
    except Exception:  # noqa: BLE001 -- committed changes survive an invalidation transport outage
        log.warning("Task event publication unavailable; clients must refetch")


def start_task_event_listener(
    *,
    loop: asyncio.AbstractEventLoop,
    handler: Callable[[dict[str, Any]], Any],
    on_reconnect: Callable[[], Any] | None = None,
) -> None:
    global _listener_thread, _stop_event
    client = get_redis_client()
    if client is None:
        return
    with _listener_lock:
        if _listener_thread is not None and _listener_thread.is_alive():
            return
        stop = threading.Event()
        _stop_event = stop

        def dispatch(coroutine):
            # One pending fanout per listener bounds memory during activity bursts.
            future = asyncio.run_coroutine_threadsafe(coroutine, loop)
            while not stop.is_set():
                try:
                    future.result(timeout=0.25)
                    return
                except FutureTimeout:
                    if future.done():
                        raise  # The handler itself raised TimeoutError; do not spin.
                    continue
            future.cancel()

        def run():
            global _pubsub
            delay = 1
            while not stop.is_set():
                stream = None
                try:
                    stream = client.pubsub()
                    _pubsub = stream
                    stream.subscribe(TASK_EVENT_CHANNEL)
                    while not stop.is_set():
                        message = stream.get_message(timeout=1)
                        if not message:
                            continue
                        if message.get("type") == "subscribe":
                            delay = 1
                            if on_reconnect:
                                dispatch(on_reconnect())
                            continue
                        if message.get("type") != "message":
                            continue
                        raw = message.get("data")
                        try:
                            payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                            continue
                        if isinstance(payload, dict):
                            dispatch(handler(payload))
                except Exception:  # noqa: BLE001 -- transport/handler failure is recoverable
                    if not stop.is_set():
                        log.warning("Task event listener interrupted; reconnecting")
                finally:
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:  # noqa: BLE001, S110 -- best-effort transport cleanup
                            pass
                    if _pubsub is stream:
                        _pubsub = None
                if stop.wait(delay):
                    break
                delay = min(30, delay * 2)

        _listener_thread = threading.Thread(target=run, name="tasks-event-listener", daemon=True)
        _listener_thread.start()


def stop_task_event_listener() -> None:
    global _listener_thread
    with _listener_lock:
        thread = _listener_thread
        _stop_event.set()
    # get_message has a one-second timeout. Avoid closing its socket from another
    # thread, which can race a concurrent Redis parser read.
    if thread:
        thread.join(timeout=3)
    with _listener_lock:
        if thread is _listener_thread and (not thread or not thread.is_alive()):
            _listener_thread = None
