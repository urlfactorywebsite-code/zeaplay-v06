from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from queue import Empty, Full, Queue
from threading import Lock, Thread
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .. import models
from ..database import SessionLocal


def _write_savepoint(db):
    # sqlite3 legacy transaction mode does not BEGIN for SELECT. An outermost
    # RELEASE SAVEPOINT would otherwise commit work owned by the caller.
    # Reserve the writer before nested activity reads: concurrent deferred
    # transactions cannot safely upgrade their shared locks at payout time.
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    return db.begin_nested()


def _activity_context(db, actor_id, task_id, subtask_id=None, *, write=True):
    """Use the canonical parent tenancy/access checks, with a live actor role."""
    from ..routers.tasks import (
        _ensure_task_access,
        _ensure_task_update_access,
        _fetch_task_or_404,
    )
    actor = db.scalar(select(models.User).where(models.User.id == actor_id).execution_options(populate_existing=True))
    if not actor or actor.status != models.UserStatusEnum.ACTIVE:
        raise HTTPException(403, "An active actor is required")
    task = _fetch_task_or_404(db, task_id)
    (_ensure_task_update_access if write else _ensure_task_access)(task, actor)
    if write and actor.role == models.RoleEnum.USER and actor.id not in {task.created_by_id, task.assigned_to_id}:
        raise HTTPException(403, "Observers cannot write task activity")
    subtask = db.get(models.Subtask, subtask_id) if subtask_id else None
    if subtask_id and (not subtask or subtask.task_id != task_id):
        raise HTTPException(404, "Subtask not found")
    return actor, task, subtask


def record_task_activity(db, *, actor_id, task_id, data, subtask_id=None):
    """Synchronous audit repository: flush only; caller owns commit/rollback.

    This is intentionally distinct from best-effort queue_log. Transactional
    notification hooks may store alerts for the new event; external delivery
    waits for commit. No task mutation or wallet recalculation occurs here.
    """
    from ..schemas import TaskActivityInput
    data = data if isinstance(data, TaskActivityInput) else TaskActivityInput.model_validate(data)
    actor, task, subtask = _activity_context(db, actor_id, task_id, subtask_id)
    row = models.AuditEvent(
        audit_schema_version=2, tenant_id=actor.tenant_id, task_id=task.id,
        subtask_id=subtask.id if subtask else None, actor_id=actor.id,
        event_type=data.event_type, entity_type="subtask" if subtask else "task",
        entity_id=subtask.id if subtask else task.id, before=data.before,
        after=data.after, payload=data.metadata, correlation_id=data.correlation_id,
        created_at=models.utc_now(),
    )
    db.add(row)
    db.flush()
    return row


def list_task_activity(db, *, actor_id, task_id, subtask_id=None, limit=100):
    actor, _, _ = _activity_context(db, actor_id, task_id, subtask_id, write=False)
    stmt = select(models.AuditEvent).where(
        models.AuditEvent.audit_schema_version == 2,
        models.AuditEvent.tenant_id == actor.tenant_id,
        models.AuditEvent.task_id == task_id,
    )
    if subtask_id:
        stmt = stmt.where(models.AuditEvent.subtask_id == subtask_id)
    return list(db.scalars(stmt.order_by(models.AuditEvent.created_at.desc(), models.AuditEvent.id.desc()).limit(max(1, min(limit, 200)))))


def create_policy_subtask(db, *, actor_id, task_id, title, planned_start_date=None, planned_end_date=None):
    """Compatibility entry point; all current writers use the managed contract."""
    from .subtasks import create
    return create(db, actor_id=actor_id, task_id=task_id, data={
        "title": title, "planned_start_date": planned_start_date,
        "planned_end_date": planned_end_date,
    })


def update_subtask_schedule(db, *, actor_id, task_id, subtask_id, data):
    from ..schemas import SubtaskScheduleUpdate
    data = data if isinstance(data, SubtaskScheduleUpdate) else SubtaskScheduleUpdate.model_validate(data)
    actor, _, subtask = _activity_context(db, actor_id, task_id, subtask_id)
    if subtask.managed:
        # Phase 1 callers cannot bypass the managed confirmation contract.
        from .subtasks import edit
        return edit(db, actor_id=actor_id, task_id=task_id, subtask_id=subtask_id,
                    data=data.model_dump(exclude_unset=True))
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    before = {name: getattr(subtask, name) for name in fields}
    candidate = {name: getattr(subtask, name) for name in ("planned_start_date", "planned_end_date", "actual_start_at", "actual_end_at", "priority_override")}
    candidate.update(fields)
    SubtaskScheduleUpdate(expected_version=data.expected_version, **candidate)
    def snapshot(values):
        return {key: value.isoformat() if hasattr(value, "isoformat") else value.value if hasattr(value, "value") else value for key, value in values.items()}
    with _write_savepoint(db):
        result = db.execute(update(models.Subtask).where(
            models.Subtask.id == subtask.id, models.Subtask.version == data.expected_version,
        ).values(**fields, version=models.Subtask.version + 1))
        if result.rowcount != 1:
            raise HTTPException(409, "Subtask changed; reload before saving")
        record_task_activity(db, actor_id=actor.id, task_id=task_id, subtask_id=subtask.id,
                             data={"event_type": "subtask.schedule_changed", "before": snapshot(before), "after": snapshot(fields)})
        db.refresh(subtask)
    return subtask


def append_point_adjustment(db, *, actor_id, task_id, data, subtask_id=None):
    """Append an adjustment; it does not credit/debit the existing reward wallet."""
    from ..schemas import PointAdjustmentInput
    from ..tickets.models import XpLedger
    data = data if isinstance(data, PointAdjustmentInput) else PointAdjustmentInput.model_validate(data)
    actor, _, subtask = _activity_context(db, actor_id, task_id, subtask_id)
    from .subtask_rewards import POLICY
    if data.policy_version == POLICY or (subtask and subtask.point_policy_version == POLICY):
        raise HTTPException(409, "Additional subtask adjustments must use the transactional reward engine")
    recipient = db.get(models.User, data.user_id)
    event = db.get(models.AuditEvent, data.activity_event_id)
    if not recipient or recipient.tenant_id != actor.tenant_id:
        raise HTTPException(404, "Recipient not found")
    if not event or event.audit_schema_version != 2 or event.tenant_id != actor.tenant_id or event.task_id != task_id or event.subtask_id != subtask_id:
        raise HTTPException(404, "Activity event not found")
    if subtask and (subtask.point_policy_version == "legacy" or subtask.point_policy_version != data.policy_version):
        raise HTTPException(409, "Legacy or different-policy subtasks cannot receive new-policy adjustments")
    values = data.model_dump()
    values.update(tenant_id=actor.tenant_id, task_id=task_id, subtask_id=subtask_id, record_version=2)
    stmt = select(XpLedger).where(XpLedger.tenant_id == actor.tenant_id, XpLedger.idempotency_key == data.idempotency_key)
    def replay(existing):
        if any(getattr(existing, key) != value for key, value in values.items()):
            raise HTTPException(409, "Idempotency key already used for a different adjustment")
        return existing
    existing = db.scalar(stmt)
    if existing:
        return replay(existing)
    if data.reversal_of_id:
        original = db.get(XpLedger, data.reversal_of_id)
        if not original or original.record_version != 2 or (original.tenant_id, original.task_id, original.subtask_id, original.user_id, original.policy_version) != (actor.tenant_id, task_id, subtask_id, data.user_id, data.policy_version):
            raise HTTPException(404, "Original adjustment not found")
        if original.points != -data.points:
            raise HTTPException(422, "A reversal must exactly negate its original adjustment")
    row = XpLedger(**values, event_type=event.event_type, created_at=models.utc_now())
    try:
        with _write_savepoint(db):
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.scalar(stmt)
        if existing:
            return replay(existing)
        if data.reversal_of_id and db.scalar(select(XpLedger.id).where(XpLedger.tenant_id == actor.tenant_id, XpLedger.reversal_of_id == data.reversal_of_id)):
            raise HTTPException(409, "This adjustment already has a reversal") from None
        raise
    return row


def record_manual_work(db, *, actor_id, task_id, data, subtask_id=None):
    from ..schemas import ManualWorkIntervalInput
    data = data if isinstance(data, ManualWorkIntervalInput) else ManualWorkIntervalInput.model_validate(data)
    actor, _, _ = _activity_context(db, actor_id, task_id, subtask_id)
    stmt = select(models.TaskWorkInterval).where(models.TaskWorkInterval.tenant_id == actor.tenant_id, models.TaskWorkInterval.request_id == data.request_id)
    def replay(row):
        if (row.task_id, row.subtask_id, row.user_id, row.started_at, row.ended_at, row.note) != (task_id, subtask_id, actor.id, data.started_at, data.ended_at, data.note):
            raise HTTPException(409, "Request ID already used for another work interval")
        return row
    existing = db.scalar(stmt)
    if existing:
        return replay(existing)
    try:
        with _write_savepoint(db):
            event = record_task_activity(db, actor_id=actor.id, task_id=task_id, subtask_id=subtask_id, data={
                "event_type": "subtask.manual_work_logged" if subtask_id else "task.manual_work_logged",
                "after": {"started_at": data.started_at.isoformat(), "ended_at": data.ended_at.isoformat(), "note": data.note},
                "correlation_id": data.request_id,
            })
            row = models.TaskWorkInterval(tenant_id=actor.tenant_id, task_id=task_id, subtask_id=subtask_id,
                user_id=actor.id, created_by_id=actor.id, started_at=data.started_at, ended_at=data.ended_at,
                note=data.note, request_id=data.request_id, activity_event_id=event.id)
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.scalar(stmt)
        if existing:
            return replay(existing)
        raise
    return row


_QUEUE_MAX_SIZE = 2000
_queue: Queue[Dict[str, Any]] = Queue(maxsize=_QUEUE_MAX_SIZE)
_worker_lock = Lock()
_worker_started = False


def _now() -> datetime:
    return datetime.utcnow()


def _extract_ip(request: Request) -> Optional[str]:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _request_context(request: Optional[Request]) -> Dict[str, Optional[str]]:
    if not request:
        return {
            "ip_address": None,
            "user_agent": None,
            "accept_language": None,
            "sec_ch_ua": None,
            "sec_ch_platform": None,
            "route": None,
            "method": None,
        }
    return {
        "ip_address": _extract_ip(request),
        "user_agent": request.headers.get("user-agent"),
        "accept_language": request.headers.get("accept-language"),
        "sec_ch_ua": request.headers.get("sec-ch-ua"),
        "sec_ch_platform": request.headers.get("sec-ch-ua-platform"),
        "route": request.url.path if request.url else None,
        "method": request.method,
    }


def _parse_user_agent(value: Optional[str]) -> Dict[str, Optional[str]]:
    if not value:
        return {"browser": None, "browser_version": None, "os": None}
    ua = value.lower()
    browser = None
    version = None
    os_name = None
    if "edg/" in ua:
        browser = "Edge"
        version = ua.split("edg/")[-1].split(" ")[0]
    elif "chrome/" in ua and "safari/" in ua:
        browser = "Chrome"
        version = ua.split("chrome/")[-1].split(" ")[0]
    elif "firefox/" in ua:
        browser = "Firefox"
        version = ua.split("firefox/")[-1].split(" ")[0]
    elif "safari/" in ua:
        browser = "Safari"
        version = ua.split("version/")[-1].split(" ")[0] if "version/" in ua else None

    if "windows" in ua:
        os_name = "Windows"
    elif "mac os x" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "iOS"
    elif "linux" in ua:
        os_name = "Linux"

    return {"browser": browser, "browser_version": version, "os": os_name}


def _write_log(payload: Dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        db.add(models.AuditLog(**payload))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _worker() -> None:
    while True:
        try:
            payload = _queue.get(timeout=0.5)
        except Empty:
            continue
        _write_log(payload)
        _queue.task_done()


def ensure_worker_started() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        thread = Thread(target=_worker, name="audit-log-worker", daemon=True)
        thread.start()
        _worker_started = True


def queue_log(payload: Dict[str, Any]) -> None:
    ensure_worker_started()
    try:
        _queue.put_nowait(payload)
    except Full:
        _write_log(payload)


@dataclass
class AuditLogInput:
    action: str
    category: models.AuditLogCategoryEnum
    tenant_id: Any = None
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    target_user_id: Optional[str] = None
    approval_id: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    source: models.AuditLogSourceEnum = models.AuditLogSourceEnum.MANUAL
    severity: models.AuditLogSeverityEnum = models.AuditLogSeverityEnum.INFO
    status: models.AuditLogStatusEnum = models.AuditLogStatusEnum.SUCCESS
    reason: Optional[str] = None
    trigger: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    request: Optional[Request] = None
    created_at: datetime = field(default_factory=_now)


def log_event(entry: AuditLogInput) -> None:
    from .audit_security import event_tenant, redact
    context = _request_context(entry.request)
    client_meta = _parse_user_agent(context["user_agent"])
    metadata_payload = dict(entry.metadata or {})
    metadata_payload.setdefault(
        "client",
        {
            **client_meta,
            "accept_language": context["accept_language"],
            "sec_ch_ua": context["sec_ch_ua"],
            "sec_ch_platform": context["sec_ch_platform"],
        },
    )
    payload = {
        "tenant_id": event_tenant(entry),
        "actor_id": entry.actor_id,
        "actor_role": entry.actor_role,
        "action": entry.action,
        "category": entry.category,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "target_user_id": entry.target_user_id,
        "approval_id": entry.approval_id,
        "old_value": entry.old_value,
        "new_value": entry.new_value,
        "before": entry.before,
        "after": entry.after,
        "ip_address": context["ip_address"],
        "user_agent": context["user_agent"],
        "source": entry.source,
        "severity": entry.severity,
        "status": entry.status,
        "reason": entry.reason,
        "trigger": entry.trigger,
        "route": context["route"],
        "method": context["method"],
        "metadata_payload": metadata_payload,
        "created_at": entry.created_at,
    }
    queue_log(redact(payload))
