from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from ..database import SessionLocal
from ..dependencies import _decode_access_token
from ..models import Task, User, UserStatusEnum
from ..services.navigation_sockets import bind_socket, socket_allowed
from ..services.task_activity import _subject
from ..services.task_access import apply_task_visibility

TASK_PAGES = ("tasks.list", "kanban", "calendar", "gantt", "dashboard")


router = APIRouter()


class TaskConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, tenant_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(tenant_id, set()).add(websocket)

    async def disconnect(self, tenant_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(tenant_id)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(tenant_id, None)

    async def broadcast(self, tenant_id: str | None, message: dict[str, Any]) -> None:
        if not tenant_id:
            return  # A missing scope must never broadcast across every tenant.
        if message.get("tenant_id") is not None and str(message["tenant_id"]) != str(tenant_id):
            return
        async with self._lock:
            recipients = list(self._connections.get(tenant_id, set()))
        subject = (
            message.get("user_id") if message.get("type") in {"work.changed", "notifications.changed"} else None
        )
        groups = {}
        for socket in recipients:
            identity = getattr(socket.state, "navigation_identity", None)
            if identity and str(identity[1]) != str(tenant_id):
                continue
            if message.get("type") == "notifications.changed" and (not subject or not identity or identity[0] != subject):
                continue
            if subject and (
                not identity
                or subject
                not in {identity[0], getattr(socket.state, "activity_subject", None)}
            ):
                continue
            # Separate sessions for the same user can be revoked independently.
            claims = getattr(socket.state, "auth_claims", {})
            groups.setdefault((identity, claims.get("sid"), claims.get("exp")), []).append(socket)
        # Bound slow-client fanout, and check identity once per event/user rather
        # than once per tab. No cached role/tenant permissions across events.
        slots = asyncio.Semaphore(16)

        async def deliver(sockets):
            async with slots:
                first = sockets[0]
                permitted = await run_in_threadpool(_delivery_allowed, first, subject)
                visible_message = (await run_in_threadpool(_visible_message, first, message)
                                   if permitted else None)
                for socket in sockets:
                    try:
                        if not permitted or visible_message is None:
                            await asyncio.wait_for(
                                socket.close(code=status.WS_1008_POLICY_VIOLATION),
                                timeout=5,
                            )
                            await self.disconnect(tenant_id, socket)
                            continue
                        await asyncio.wait_for(socket.send_json(visible_message), timeout=5)
                    except Exception:  # noqa: BLE001 -- isolate broken client transports
                        await self.disconnect(tenant_id, socket)

        await asyncio.gather(*(deliver(sockets) for sockets in groups.values()))


def _visible_message(socket, message):
    """Group invalidations must not disclose another assignment's identifiers."""
    if message.get("type") != "task.changed":
        return message
    identity = getattr(socket.state, "navigation_identity", None)
    if not identity:
        return None
    safe = {"type": "task.changed", "tenant_id": identity[1], "action": "invalidate"}
    primary = message.get("task_id")
    batch = message.get("task_ids") or []
    if not isinstance(batch, list):
        return safe
    ids = [value for value in [primary, *batch] if isinstance(value, str)]
    try:
        with SessionLocal() as db:
            user = db.get(User, identity[0])
            if not user or user.status != UserStatusEnum.ACTIVE or str(user.tenant_id) != identity[1]:
                return None
            visible = set(db.scalars(apply_task_visibility(
                select(Task.id).where(Task.id.in_(ids)), user))) if ids else set()
    except SQLAlchemyError:
        return safe  # Refetch without disclosing IDs when authorization is unavailable.
    if isinstance(primary, str) and primary in visible:
        safe["task_id"] = primary
    if "task_ids" in message:
        safe["task_ids"] = [value for value in batch if isinstance(value, str) and value in visible]
    if (not primary or primary in visible) and all(value in visible for value in ids):
        safe["action"] = message.get("action", "invalidate")
    return safe


def _delivery_allowed(socket, subject):
    if not socket_allowed(socket, TASK_PAGES):
        return False
    identity = getattr(socket.state, "navigation_identity", None)
    if subject and identity and subject != identity[0]:
        return _watch_subject(socket, subject) is not None
    return True


def _watch_subject(socket, subject):
    identity = getattr(socket.state, "navigation_identity", None)
    if not identity:
        return None
    try:
        with SessionLocal() as db:
            user = db.get(User, identity[0])
            if (
                not user
                or user.status != UserStatusEnum.ACTIVE
                or str(user.tenant_id) != identity[1]
            ):
                return None
            if not bind_socket(socket, user, db, TASK_PAGES):
                return None
            return _subject(db, user, subject).id
    except (HTTPException, SQLAlchemyError):
        return None


def _authenticate_socket(socket, payload):
    socket.state.auth_claims = payload
    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        return None
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == str(user_id)))
        if not user or user.status != UserStatusEnum.ACTIVE:
            return None
        tenant_id = str(user.tenant_id)
        if str(payload.get("tenant_id") or "") != tenant_id or not bind_socket(
            socket, user, db, TASK_PAGES
        ):
            return None
        return tenant_id


manager = TaskConnectionManager()


def _extract_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token")
    if token:
        return token
    auth_header = websocket.headers.get("authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    return None


async def _heartbeat(websocket: WebSocket, interval_seconds: int = 25) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            if not await run_in_threadpool(socket_allowed, websocket, TASK_PAGES):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            await websocket.send_json({"type": "ping"})
        except Exception:  # noqa: BLE001 -- heartbeat must stop on transport failure
            return


async def broadcast_task_event(payload: dict[str, Any]) -> None:
    tenant_id = payload.get("tenant_id")
    await manager.broadcast(tenant_id, payload)


async def broadcast_task_resync() -> None:
    """Recover missed invalidations after Redis subscribes; send no task data."""
    async with manager._lock:
        tenants = list(manager._connections)
    for tenant_id in tenants:
        await manager.broadcast(tenant_id, {"type": "tasks.resync", "tenant_id": tenant_id})


@router.websocket("/ws/tasks")
async def tasks_ws(websocket: WebSocket) -> None:
    token = _extract_token(websocket)
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        payload = _decode_access_token(token)
    except Exception:  # noqa: BLE001 -- malformed authentication always fails closed
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    tenant_id = await run_in_threadpool(_authenticate_socket, websocket, payload)
    if not tenant_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(tenant_id, websocket)
    heartbeat_task = asyncio.create_task(_heartbeat(websocket))
    try:
        while True:
            message = await websocket.receive_json()
            if not await run_in_threadpool(socket_allowed, websocket, TASK_PAGES):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                break
            if message.get("type") == "pong":
                continue
            if message.get("type") == "activity.watch":
                subject = message.get("user_id")
                if subject is not None and (
                    not isinstance(subject, str) or len(subject) > 36
                ):
                    websocket.state.activity_subject = None
                    await websocket.send_json({"type": "activity.watch_denied"})
                    continue
                subject = await run_in_threadpool(_watch_subject, websocket, subject)
                websocket.state.activity_subject = subject
                await websocket.send_json(
                    {
                        "type": "activity.watching"
                        if subject
                        else "activity.watch_denied",
                        "user_id": subject,
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        await manager.disconnect(tenant_id, websocket)
