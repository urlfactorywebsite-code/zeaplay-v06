"""Owned localhost E2E fixture: real routers/SQL/JWT, no startup or providers.

Copy source to an isolated verification root containing OWNED-VERIFICATION.txt.
Run from that root: python -m backend.checks.phase7_browser_app
This entry point refuses execution from the application checkout.
"""
import os
from pathlib import Path

ROOT = Path.cwd().resolve()
if not (ROOT / "OWNED-VERIFICATION.txt").is_file() or not ROOT.name.startswith("zeaplay-phase7-"):
    raise RuntimeError("This fixture requires an owned Phase 7 verification copy")
os.environ.update(
    VEE_DATABASE_URL="sqlite:///:memory:", VEE_ENVIRONMENT="test",
    VEE_JWT_SECRET_KEY="phase7-disposable-signing-key",
    VEE_JWT_REFRESH_SECRET_KEY="phase7-disposable-refresh-key",
    VEE_REDIS_URL="", VEE_CACHE_REDIS_URL="", VEE_ENABLE_N8N_FORWARDING="false",
)

import asyncio
import inspect
import socket
import uuid

import uvicorn
from fastapi import Depends, FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app import database
from backend.app import models as m
from backend.app.auth import hash_password
from backend.app.navigation_guard import enforce_navigation_policy
from backend.app.routers import (
    auth,
    comments,
    config,
    navigation,
    notification_preferences,
    notifications,
    push,
    tasks,
    users,
)
from backend.app.services import (
    audit_logger,
    navigation_sockets,
    task_activity,
    task_events,
)
from backend.app.services import workload_notifications as alerts
from backend.app.ws import tasks as task_sockets

original_connect = socket.socket.connect


def block_external_connect(self, address):
    caller = inspect.currentframe().f_back
    if caller.f_code.co_filename == socket.__file__ and caller.f_code.co_name == "_fallback_socketpair":
        return original_connect(self, address)
    raise RuntimeError("External network disabled in the Phase 7 API fixture")


def build_app():
    engine = create_engine(f"sqlite:///{ROOT / 'browser-synthetic.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def sqlite_setup(connection, _):
        connection.create_function("to_tsvector", 2, lambda _language, value: value, deterministic=True)
        connection.execute("PRAGMA foreign_keys=ON")

    m.Base.metadata.create_all(engine)
    with Session(engine) as db:
        if not db.get(m.User, "owner"):
            hashed = hash_password("phase7-synthetic-password")
            tenant = uuid.uuid5(uuid.NAMESPACE_URL, "zea-phase7-browser-fixture")
            for key, role in (("owner", m.RoleEnum.OWNER), ("worker", m.RoleEnum.USER), ("watcher", m.RoleEnum.USER)):
                db.add(m.User(id=key, name=f"Phase 7 {key}", email=f"{key}@example.com", hashed_password=hashed,
                              tenant_id=tenant, role=role, timezone="Asia/Kolkata", points=100))
            db.commit()
    database.SessionLocal = sessionmaker(engine)
    # Existing asynchronous/external transports are outside this test server.
    # Transactional task audits, ledgers and inbox rows remain enabled.
    audit_logger.log_event = lambda *args, **kwargs: None
    for name in ("get_cached_json", "set_cached_json", "invalidate_prefix", "trigger_n8n_event"):
        setattr(tasks, name, lambda *args, **kwargs: None)
    comments.trigger_n8n_event = lambda *args, **kwargs: None
    app = FastAPI(dependencies=[Depends(enforce_navigation_policy)])
    for module in (auth, config, tasks, comments, notifications, notification_preferences, navigation, users, push):
        app.include_router(module.router, prefix="/api")
    app.include_router(task_sockets.router, prefix="/api")
    task_sockets.SessionLocal = database.SessionLocal
    navigation_sockets.SessionLocal = database.SessionLocal

    @app.on_event("startup")
    async def local_event_loop():
        app.state.fixture_loop = asyncio.get_running_loop()

    def local_fanout(payload):
        # Actual socket authentication/fanout; the Redis transport hop is local
        # here and has its own real Redis recovery test.
        asyncio.run_coroutine_threadsafe(task_sockets.broadcast_task_event(payload), app.state.fixture_loop)

    task_events.publish_task_event = local_fanout
    app.add_exception_handler(task_activity.ActivityLimitExceeded, alerts.limit_error_handler)

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[database.get_db] = session
    return app


if __name__ == "__main__":
    application = build_app()
    socket.socket.connect = block_external_connect
    uvicorn.run(application, host="127.0.0.1", port=16217, log_level="warning", loop="asyncio")
