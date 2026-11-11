"""Transactional alerts over the existing notification inbox and task stream.

Write hooks store alerts without point calculation, timer changes or historical
backfill. Invalidations publish after the outer commit; the existing maintenance
worker pattern drains browser push delivery.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import uuid
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import event, func, inspect, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from .. import models as m

log = logging.getLogger(__name__)


def _event_key(tenant_id, source, kind):
    return hashlib.sha256(f"phase6:{tenant_id}:{source}:{kind}".encode()).hexdigest()


def _created_at(value=None):
    value = value or m.utc_now()
    return (
        value.replace(tzinfo=timezone.utc).replace(tzinfo=None)
        if value.tzinfo is None
        else value.astimezone(timezone.utc).replace(tzinfo=None)
    )


def preferences(db, user_id):
    return db.scalar(
        select(m.NotificationPreference)
        .where(
            m.NotificationPreference.user_id == user_id,
            m.NotificationPreference.module == "tasks",
        )
        .execution_options(populate_existing=True)
    )


def quiet(pref, user, now):
    if not pref or not pref.quiet_start or not pref.quiet_end:
        return False
    try:
        local = now.astimezone(ZoneInfo(user.timezone or "UTC")).strftime("%H:%M")
    except (ValueError, ZoneInfoNotFoundError):
        return True  # Invalid timezone must not defeat configured quiet hours.
    start, end = pref.quiet_start, pref.quiet_end
    return start <= local < end if start < end else local >= start or local < end


def task_module_allowed(db, user):
    from ..navigation_registry import api_pages
    from .navigation import enforce_pages

    cache = db.info.setdefault("phase6_module_access", {})
    key = (str(user.tenant_id), user.role.value)
    if key not in cache:
        try:
            enforce_pages(db, user, api_pages("/tasks", "GET"))
            cache[key] = True
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
            cache[key] = False
    return cache[key]


def can_view(task, user):
    from ..routers.tasks import _ensure_task_access

    try:
        _ensure_task_access(task, user)
        return user.status == m.UserStatusEnum.ACTIVE and task_module_allowed(
            inspect(task).session, user
        )
    except HTTPException:
        return False


def emit_account(
    db, *, user, kind, source, message, title, subject_id=None, occurred_at=None
):
    """An owned balance/workload alert can outlive access to a former task."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    key = _event_key(user.tenant_id, source, kind)
    result = db.execute(
        insert(m.Notification)
        .values(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"zea:{user.id}:{key}")),
            user_id=user.id,
            tenant_id=user.tenant_id,
            dedupe_key=key,
            alert_kind=kind,
            type=m.NotificationTypeEnum.TASK_UPDATED,
            title=title,
            message=message,
            body=message,
            entity_type=m.NotificationEntityTypeEnum.USER if subject_id else None,
            entity_id=subject_id,
            is_read=False,
            created_at=_created_at(occurred_at),
            delivery_pending=True,
            delivery_attempts=0,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        .returning(m.Notification.user_id)
    ).scalar_one_or_none()
    if result is not None:
        db.info.setdefault("phase6_fanout", set()).add((str(user.tenant_id), user.id))


def recipients(db, task, responsible=None):
    """Manager pointers are candidates, never implicit task visibility grants."""
    owner = task.creator
    if not owner:
        return []
    employee = (
        db.get(m.User, responsible or task.assigned_to_id)
        if (responsible or task.assigned_to_id)
        else None
    )
    ids = {
        task.created_by_id,
        task.assigned_to_id,
        responsible,
        *(u.id for u in task.followers),
    }
    if employee and employee.tenant_id == owner.tenant_id:
        manager = (
            db.scalar(
                select(m.User).where(
                    m.User.tenant_id == owner.tenant_id,
                    m.User.status == m.UserStatusEnum.ACTIVE,
                    m.User.role.in_(
                        [m.RoleEnum.MANAGER, m.RoleEnum.ADMIN, m.RoleEnum.OWNER]
                    ),
                    m.User.id == employee.manager_id,
                )
            )
            if employee.manager_id
            else None
        )
        # Legacy reporting email is resolved only inside the same workspace.
        if not manager and not employee.manager_id and employee.manager_email:
            manager = db.scalar(
                select(m.User).where(
                    m.User.tenant_id == owner.tenant_id,
                    func.lower(m.User.email) == employee.manager_email.lower(),
                    m.User.status == m.UserStatusEnum.ACTIVE,
                    m.User.role.in_(
                        [m.RoleEnum.MANAGER, m.RoleEnum.ADMIN, m.RoleEnum.OWNER]
                    ),
                )
            )
        if manager:
            ids.add(manager.id)
    users = db.scalars(
        select(m.User)
        .where(
            m.User.id.in_(ids - {None}),
            m.User.tenant_id == owner.tenant_id,
            m.User.status == m.UserStatusEnum.ACTIVE,
        )
        .execution_options(populate_existing=True)
    ).all()
    return [u for u in users if can_view(task, u)]


def emit(
    db,
    *,
    task,
    kind,
    source,
    message,
    title=None,
    responsible=None,
    only=None,
    child_id=None,
    occurred_at=None,
):
    """One durable row per recipient/source, including dismissed tombstones."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    db.expire(task, ["creator", "assignee", "followers"])
    users = recipients(db, task, responsible)
    if only is not None:
        users = [u for u in users if u.id in only]
    tenant = task.creator.tenant_id
    key = _event_key(tenant, source, kind)
    typ = (
        m.NotificationTypeEnum.TASK_ASSIGNED
        if kind in {"assignment", "subtask_assigned"}
        else m.NotificationTypeEnum.TASK_CREATED
        if kind in {"task_created", "subtask_created"}
        else m.NotificationTypeEnum.TASK_DELETED
        if kind == "task_deleted"
        else m.NotificationTypeEnum.TASK_OVERDUE
        if "overdue" in kind
        else m.NotificationTypeEnum.TASK_COMPLETED
        if kind.endswith("completed")
        else m.NotificationTypeEnum.TASK_UPDATED
    )
    created_at = _created_at(occurred_at)
    values = []
    for user in users:
        values.append(
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"zea:{user.id}:{key}")),
                "user_id": user.id,
                "tenant_id": tenant,
                "dedupe_key": key,
                "type": typ,
                "alert_kind": kind,
                "title": title or kind.replace("_", " ").capitalize(),
                "body": message,
                "message": message,
                "entity_type": m.NotificationEntityTypeEnum.TASK,
                "entity_id": task.id,
                "related_task_id": None if kind == "task_deleted" else task.id,
                "deep_link": (
                    "/tasks" if kind == "task_deleted" else f"/tasks/{task.id}"
                )
                + (f"?subtask={child_id}" if child_id else ""),
                "is_read": False,
                "created_at": created_at,
                "delivery_pending": True,
                "delivery_attempts": 0,
            }
        )
    # Bound bind parameters and insert each recipient group in one statement.
    for offset in range(0, len(values), 100):
        result = db.scalars(
            insert(m.Notification)
            .values(values[offset : offset + 100])
            .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
            .returning(m.Notification.user_id)
        ).all()
        for user_id in result:
            db.info.setdefault("phase6_fanout", set()).add((str(tenant), user_id))


def task_notice(db, task, kind="task_updated", message=None):
    token = db.info.setdefault("phase6_token", str(uuid.uuid4()))
    # Existing assignee/creator/watcher dispatches share the task mutation key.
    kinds = db.info.setdefault("phase6_task_kinds", {})
    kind = kinds.setdefault(task.id, kind)
    emit(
        db,
        task=task,
        kind=kind,
        source=f"task:{token}:{task.id}",
        title={
            "assignment": "Task assigned",
            "task_created": "Task created",
            "task_completed": "Task completed",
            "task_deleted": "Task deleted",
        }.get(kind, "Task updated"),
        message=message or f"Task '{task.title}' was updated.",
    )


def from_event(db, row):
    before, after = row.before or {}, row.after or {}
    status_before = before.get("workflow_status", before.get("status"))
    status_after = after.get("workflow_status", after.get("status"))
    workflow_change = (
        row.subtask_id
        and status_after
        and status_after != status_before
        and not row.event_type.startswith("work.")
    )
    active_change = (
        row.event_type.startswith("work.")
        and after.get("status") == "RUNNING"
        and before.get("status") != "RUNNING"
    )
    if not (workflow_change or active_change):
        return
    task = db.get(m.Task, row.task_id)
    if not task or not task.creator or task.creator.tenant_id != row.tenant_id:
        return
    if (
        row.subtask_id
        and status_after
        and status_after != status_before
        and not row.event_type.startswith("work.")
    ):
        child = db.get(m.Subtask, row.subtask_id)
        created = row.event_type == "subtask.created"
        emit(
            db,
            task=task,
            kind=("subtask_assigned" if task.assigned_to_id else "subtask_created")
            if created
            else "subtask_completed"
            if status_after == "COMPLETED"
            else "subtask_status",
            source=row.id,
            child_id=row.subtask_id,
            occurred_at=row.created_at,
            message=(
                f"Subtask '{child.title if child else row.subtask_id}' was "
                + (
                    "assigned to the task's assignee."
                    if task.assigned_to_id
                    else "created."
                )
            )
            if created
            else f"Subtask '{child.title if child else row.subtask_id}' moved to {status_after}.",
        )
    if (
        row.event_type.startswith("work.")
        and after.get("status") == "RUNNING"
        and before.get("status") != "RUNNING"
    ):
        from .task_activity import EVENTS

        newer = db.scalar(
            select(m.AuditEvent.id)
            .where(
                m.AuditEvent.tenant_id == row.tenant_id,
                m.AuditEvent.actor_id == row.actor_id,
                m.AuditEvent.task_id == row.task_id,
                m.AuditEvent.event_type.in_(EVENTS),
                m.AuditEvent.after["context_id"].as_string() == after.get("context_id"),
                m.AuditEvent.after["version"].as_integer() > after.get("version", 0),
            )
            .limit(1)
        )
        if (
            newer
            or not after.get("context_id")
            or not isinstance(after.get("version"), int)
        ):
            return  # An older Start must never recreate a current capacity alert.
        active = db.scalar(
            select(func.count())
            .select_from(m.TaskActivityContext)
            .where(
                m.TaskActivityContext.tenant_id == row.tenant_id,
                m.TaskActivityContext.user_id == row.actor_id,
                m.TaskActivityContext.task_id != row.task_id,
                m.TaskActivityContext.status == "RUNNING",
            )
        )
        if active == 4:
            subject = db.get(m.User, row.actor_id)
            emit(
                db,
                task=task,
                kind="active_limit",
                source=row.id,
                responsible=row.actor_id,
                occurred_at=row.created_at,
                message=f"{subject.name} has reached the limit of five active parent tasks.",
            )


def from_ledger(db, row):
    if row.record_version != 2 or not row.task_id or not row.points:
        return
    from .subtask_rewards import POLICY

    if row.policy_version != POLICY or row.ref_type != POLICY:
        return  # Foundation/record-only adjustments are not proof of a wallet payout.
    task = db.get(m.Task, row.task_id)
    if not task or not task.creator or task.creator.tenant_id != row.tenant_id:
        return
    kind = {
        "BASE": "points_credited",
        "BONUS": "bonus_applied",
        "PENALTY": "penalty_applied",
        "REVERSAL": "points_reversed",
    }.get(row.component_type, "points_adjusted")
    child = db.get(m.Subtask, row.subtask_id) if row.subtask_id else None
    label = (
        f"subtask '{child.title}' in '{task.title}'"
        if child
        else f"task '{task.title}'"
    )
    emit(
        db,
        task=task,
        kind=kind,
        source=f"ledger:{row.id}",
        responsible=row.user_id,
        child_id=row.subtask_id,
        occurred_at=row.created_at,
        message=f"{kind.replace('_', ' ').capitalize()}: {row.points:+d} points for {label}.",
    )
    user = db.get(m.User, row.user_id)
    if (
        user
        and user.tenant_id == row.tenant_id
        and user.status == m.UserStatusEnum.ACTIVE
        and not can_view(task, user)
    ):
        # Reassignment may revoke task access before compensating entries post.
        # The former recipient still receives their OWN adjustment, with every
        # task/subtask identifier, title and link omitted.
        emit_account(
            db,
            user=user,
            kind=kind,
            source=f"ledger:{row.id}",
            title="Point balance adjustment",
            message=f"Your point balance was adjusted by {row.points:+d} points.",
            occurred_at=row.created_at,
        )


def install_hooks():
    """Capture only new writes, never scan historical audit/point entries."""

    @event.listens_for(Session, "before_flush")
    def collect(db, context, instances):
        from ..tickets.models import XpLedger

        pending = db.info.setdefault("phase6_pending", [])
        for obj in list(db.new):
            if isinstance(obj, m.AuditEvent) and obj.audit_schema_version == 2:
                pending.append(("event", obj))
            elif isinstance(obj, XpLedger) and obj.record_version == 2:
                pending.append(("ledger", obj))
            elif isinstance(obj, m.Task):
                pending.append(
                    ("assignment" if obj.assigned_to_id else "task_created", obj)
                )
            elif isinstance(obj, m.Notification):
                pending.append(("inbox", obj))
        for obj in list(db.dirty):
            if isinstance(obj, m.Task):
                changes = inspect(obj).attrs
                fields = [
                    c
                    for c in obj.__table__.columns
                    if c.key not in {"updated_at", "search_vector"}
                    and changes[c.key].history.has_changes()
                ]
                unknown = [c for c in fields if not changes[c.key].history.deleted]
                if unknown:
                    prior = (
                        db.connection()
                        .execute(select(*unknown).where(m.Task.id == obj.id))
                        .one()
                    )
                    unknown_keys = {c.key for c in unknown}
                    fields = [
                        c
                        for c in fields
                        if c.key not in unknown_keys
                        or prior._mapping[c.key] != getattr(obj, c.key)
                    ]
                if fields or changes.followers.history.has_changes():
                    pending.append(
                        (
                            "assignment"
                            if any(c.key == "assigned_to_id" for c in fields)
                            else "task_completed"
                            if any(c.key == "status" for c in fields)
                            and obj.status
                            in {m.TaskStatusEnum.DONE, m.TaskStatusEnum.DEPLOYED}
                            else "task",
                            obj,
                        )
                    )

    @event.listens_for(Session, "after_flush_postexec")
    def process(db, context):
        pending = db.info.pop("phase6_pending", [])
        with db.no_autoflush:
            for kind, obj in pending:
                if kind == "event":
                    from_event(db, obj)
                elif kind == "ledger":
                    from_ledger(db, obj)
                elif kind == "inbox":
                    user = db.get(m.User, obj.user_id)
                    if user and user.status == m.UserStatusEnum.ACTIVE:
                        db.info.setdefault("phase6_fanout", set()).add(
                            (str(user.tenant_id), user.id)
                        )
                else:
                    task_notice(
                        db,
                        obj,
                        kind
                        if kind in {"assignment", "task_completed", "task_created"}
                        else "task_updated",
                        f"Task '{obj.title}': {obj.status.value if obj.status else 'assigned'}.",
                    )

    @event.listens_for(Session, "after_transaction_end")
    def clear(db, transaction):
        if transaction.parent is None:
            db.info.pop("phase6_token", None)
            db.info.pop("phase6_pending", None)
            db.info.pop("phase6_task_kinds", None)
            db.info.pop("phase6_fanout", None)
            db.info.pop("phase6_module_access", None)

    @event.listens_for(Session, "after_commit")
    def committed(db):
        if db.in_nested_transaction():
            return  # Releasing a savepoint is not an externally visible commit.
        from .task_events import publish_task_event

        for tenant_id, user_id in db.info.pop("phase6_fanout", set()):
            try:
                publish_task_event(
                    {
                        "type": "notifications.changed",
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                    }
                )
            except Exception:  # noqa: BLE001 -- committed storage survives transport failure
                log.warning("Notification invalidation postponed until client refetch")

    @event.listens_for(Session, "after_transaction_create")
    def savepoint(db, transaction):
        if transaction.nested:
            transaction._phase6_snapshot = {
                key: value.copy() if isinstance(value, (dict, set, list)) else value
                for key, value in db.info.items()
                if key.startswith("phase6_")
            }

    @event.listens_for(Session, "after_soft_rollback")
    def rolled_back(db, previous_transaction):
        snapshot = getattr(previous_transaction, "_phase6_snapshot", None)
        for key in list(db.info):
            if key.startswith("phase6_"):
                db.info.pop(key, None)
        if snapshot is not None:
            db.info.update(snapshot)


def visible_query(user, db=None):
    """Recheck visibility on every inbox read/action, including after reassignment."""
    from ..routers.tasks import _apply_task_visibility

    db = db if db is not None else inspect(user).session
    allowed_module = task_module_allowed(db, user)

    authorized = _apply_task_visibility(select(m.Task.id), user)
    subjects = select(m.User.id).where(
        m.User.tenant_id == user.tenant_id, m.User.status == m.UserStatusEnum.ACTIVE
    )
    if not allowed_module:
        subjects = subjects.where(m.User.id == user.id)
    elif user.role not in {m.RoleEnum.OWNER, m.RoleEnum.ADMIN}:
        subjects = subjects.where(
            or_(m.User.id == user.id, m.User.manager_id == user.id)
            if user.role == m.RoleEnum.MANAGER
            else m.User.id == user.id
        )
    return select(m.Notification).where(
        m.Notification.user_id == user.id,
        m.Notification.dismissed_at.is_(None),
        or_(
            m.Notification.tenant_id.is_(None),
            m.Notification.tenant_id == user.tenant_id,
        ),
        or_(
            m.Notification.related_task_id.is_(None),
            authorized.where(m.Task.id == m.Notification.related_task_id)
            .correlate(m.Notification)
            .exists()
            if allowed_module
            else False,
        ),
        or_(
            m.Notification.alert_kind.is_(None),
            m.Notification.alert_kind != "task_deleted",
            allowed_module,
        ),
        or_(
            m.Notification.alert_kind.is_(None),
            ~m.Notification.alert_kind.in_(
                ["productive_overtime", "estimated_overload"]
            ),
            m.Notification.related_task_id.is_not(None),
            subjects.where(m.User.id == m.Notification.entity_id)
            .correlate(m.Notification)
            .exists(),
        ),
    )


def limit_error_handler(request, exc):
    """Persist a denied attempt independently of the rejected mutation rollback."""
    from starlette.responses import JSONResponse

    from ..database import SessionLocal

    try:
        with SessionLocal() as db:
            user, task = db.get(m.User, exc.actor_id), db.get(m.Task, exc.task_id)
            if user and task and can_view(task, user):
                emit(
                    db,
                    task=task,
                    kind="active_limit_denied",
                    source=f"denied:{exc.actor_id}:{exc.task_id}:{exc.request_id}",
                    responsible=user.id,
                    message=f"{user.name}'s attempt to activate a sixth parent task was denied.",
                )
                db.commit()
    except Exception:  # noqa: BLE001 -- alert failure must preserve the original capacity rejection
        log.warning("Could not store active-limit alert", exc_info=False)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _deadline_current(db, notification, task, now):
    from urllib.parse import parse_qs, urlsplit

    from .task_activity import DONE, deadline

    if notification.alert_kind not in {
        "approaching_deadline",
        "task_overdue",
        "subtask_overdue",
    }:
        return True
    if not task:
        return False
    try:
        child_id = parse_qs(urlsplit(notification.deep_link or "").query).get(
            "subtask", [None]
        )[0]
    except ValueError:
        return False
    child = (
        db.scalar(
            select(m.Subtask)
            .where(m.Subtask.id == child_id, m.Subtask.task_id == task.id)
            .execution_options(populate_existing=True)
        )
        if child_id
        else None
    )
    if child_id and (not child or child.deleted_at or child.completed):
        return False
    if (not child or not child.managed) and task.status in DONE:
        return False
    due = deadline(task, child, ZoneInfo("UTC"))
    if due is None or notification.dedupe_key != _event_key(
        notification.tenant_id,
        f"due:{task.id}:{child_id}:{due.isoformat()}",
        notification.alert_kind,
    ):
        return False
    if notification.alert_kind != "approaching_deadline":
        return due < now
    owner_id = task.assigned_to_id or task.created_by_id
    pref = preferences(db, owner_id)
    return now <= due <= now + timedelta(hours=pref.near_deadline_hours if pref else 24)


def run_delivery(db, limit=100):
    """Existing inbox doubles as the outbox; row locks coordinate workers."""
    from time import monotonic

    from .notification_dispatcher import deliver_stored_notification
    from .task_events import publish_task_event

    started = monotonic()
    budget_end = started + 8
    limit = min(100, max(1, limit))
    now = m.utc_now()
    rows = db.scalars(
        select(m.Notification)
        .where(
            m.Notification.delivery_pending.is_(True),
            or_(
                m.Notification.next_delivery_at.is_(None),
                m.Notification.next_delivery_at <= now,
            ),
        )
        .order_by(m.Notification.created_at, m.Notification.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    fanout = set()
    processed = 0
    stats = {
        "selected": len(rows),
        "processed": 0,
        "delivered": 0,
        "retried": 0,
        "quiet": 0,
        "suppressed": 0,
    }
    for n in rows:
        if monotonic() >= budget_end:
            break  # Unprocessed rows stay pending for the next existing tick.
        processed += 1
        db.info.pop("phase6_module_access", None)
        user = db.get(m.User, n.user_id, populate_existing=True)
        task = (
            db.get(m.Task, n.related_task_id, populate_existing=True)
            if n.related_task_id
            else None
        )
        if task:
            db.expire(task, ["creator", "assignee", "followers"])
        valid = bool(
            user
            and user.status == m.UserStatusEnum.ACTIVE
            and user.tenant_id == n.tenant_id
            and (can_view(task, user) if task else n.related_task_id is None)
        )
        if (
            valid
            and n.alert_kind == "task_deleted"
            and not task_module_allowed(db, user)
        ):
            valid = False
        if (
            valid
            and n.related_task_id is None
            and n.alert_kind in {"productive_overtime", "estimated_overload"}
        ):
            from .task_activity import _subject

            try:
                _subject(db, user, n.entity_id)
                if n.entity_id != user.id and not task_module_allowed(db, user):
                    valid = False
            except HTTPException:
                valid = False
        if not valid or n.dismissed_at or not _deadline_current(db, n, task, now):
            n.delivery_pending = False
            stats["suppressed"] += 1
            continue
        pref = preferences(db, user.id)
        fanout.add((str(n.tenant_id), user.id))
        if quiet(pref, user, now):
            n.next_delivery_at = now + timedelta(minutes=5)
            stats["quiet"] += 1
            continue
        try:
            # A malformed delivery must not poison the remaining batch's SQL
            # transaction or discard other recipients' acknowledgement state.
            with db.begin_nested():
                failure = None
                try:
                    deliver_stored_notification(
                        db, n, sound_enabled=bool(pref and pref.sound_enabled)
                    )
                except SQLAlchemyError:
                    raise  # Roll back only this delivery's failed SQL work.
                except Exception as exc:  # noqa: BLE001 -- preserve valid device revocations on transport failure
                    failure = exc
                if failure is None:
                    n.delivery_pending = False
            if failure is not None:
                raise failure
            stats["delivered"] += 1
        except Exception:  # noqa: BLE001 -- transport failure must never remove an inbox alert
            n.delivery_attempts += 1
            n.next_delivery_at = now + timedelta(
                seconds=min(3600, 30 * 2 ** min(n.delivery_attempts, 7))
            )
            log.warning("Notification delivery postponed", exc_info=False)
            stats["retried"] += 1
    db.commit()
    stats["processed"] = processed
    stats["elapsed_ms"] = round((monotonic() - started) * 1000)
    stats["due_remaining"] = (
        db.scalar(
            select(m.Notification.id)
            .where(
                m.Notification.delivery_pending.is_(True),
                or_(
                    m.Notification.next_delivery_at.is_(None),
                    m.Notification.next_delivery_at <= m.utc_now(),
                ),
            )
            .limit(1)
        )
        is not None
    )
    db.info["phase6_delivery_stats"] = stats
    if rows:
        log.info("notification_delivery_batch %s", stats)
    # No titles/IDs in realtime. The receiver refetches its authorized inbox.
    for tenant_id, user_id in fanout:
        try:
            publish_task_event(
                {
                    "type": "notifications.changed",
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                }
            )
        except Exception:  # noqa: BLE001 -- optional realtime transport
            log.warning("Notification invalidation postponed until client refetch")
    return processed


def _deadline_notice(db, task, *, responsible, child_id, due, kind, title):
    emit(
        db,
        task=task,
        kind=kind,
        source=f"due:{task.id}:{child_id}:{due.isoformat()}",
        responsible=responsible,
        child_id=child_id,
        message=f"{'Subtask' if child_id else 'Task'} '{title}' is "
        + (
            "approaching its deadline."
            if kind == "approaching_deadline"
            else "overdue."
        ),
    )


def scan_inactive_deadlines(db, *, after_task="", limit=100):
    """Keep authorized watchers informed when the responsible account is inactive.

    Personal capacity/active work is intentionally scanned only for active users.
    This bounded exception path does not grant an inactive account access.
    """
    from .task_activity import DONE, deadline

    tasks = db.scalars(
        select(m.Task)
        .where(
            m.Task.id > after_task,
            or_(
                m.Task.assignee.has(m.User.status != m.UserStatusEnum.ACTIVE),
                (
                    m.Task.assigned_to_id.is_(None)
                    & m.Task.creator.has(m.User.status != m.UserStatusEnum.ACTIVE)
                ),
            ),
        )
        .order_by(m.Task.id)
        .limit(limit)
        .options(
            selectinload(m.Task.creator),
            selectinload(m.Task.assignee),
            selectinload(m.Task.subtasks),
        )
    ).all()
    now = m.utc_now()
    for task in tasks:
        owner = task.assignee or task.creator
        if not owner or not task.creator or owner.tenant_id != task.creator.tenant_id:
            continue
        pref = preferences(db, owner.id)
        window = timedelta(hours=pref.near_deadline_hours if pref else 24)
        for child in [None, *task.subtasks]:
            if (child is None and task.status in DONE) or (
                child
                and (
                    child.completed
                    or child.deleted_at
                    or (task.status in DONE and not child.managed)
                )
            ):
                continue
            due = deadline(task, child, ZoneInfo("UTC"))
            if due is None or due > now + window:
                continue
            _deadline_notice(
                db,
                task,
                responsible=owner.id,
                child_id=child.id if child else None,
                due=due,
                kind=("subtask_overdue" if child else "task_overdue")
                if due < now
                else "approaching_deadline",
                title=child.title if child else task.title,
            )
    db.commit()
    return tasks[-1].id if len(tasks) == limit else ""


def scan(db, *, after_user="", limit=100):
    """Bounded keyset batch. Other workers may repeat it safely via unique keys."""
    from .task_activity import snapshot

    users = db.scalars(
        select(m.User)
        .where(m.User.status == m.UserStatusEnum.ACTIVE, m.User.id > after_user)
        .order_by(m.User.id)
        .limit(limit)
    ).all()
    for user in users:
        frame = snapshot(db, actor_id=user.id, include_elapsed=False)
        workload = frame["workload"]
        for kind, items in (
            ("approaching_deadline", workload["near_deadline"]),
            ("task_overdue", workload["overdue_tasks"]),
            ("subtask_overdue", workload["overdue_subtasks"]),
        ):
            for item in items:
                task = db.get(m.Task, item["task_id"])
                # One deadline policy owner: the assignee, or the creator for
                # an unassigned legacy task. Personal parallel contexts must
                # not trigger an earlier alert under another user's threshold.
                if user.id != (task.assigned_to_id or task.created_by_id):
                    continue
                child = item.get("subtask_id")
                # Snapshot includes personal contexts; notify once for each
                # deadline/responsible employee, independent of scanner visits.
                _deadline_notice(
                    db,
                    task,
                    responsible=user.id,
                    child_id=child,
                    due=item["deadline"],
                    kind=kind,
                    title=item["title"],
                )
        pref = preferences(db, user.id)
        threshold = (pref.overtime_threshold_minutes if pref else 0) * 60
        cap = workload["capacity_seconds"]
        risks = []
        if cap is not None and workload["manual_seconds"] > cap + threshold:
            risks.append("productive_overtime")
        available = workload.get("remaining_capacity_seconds")
        if (
            available is not None
            and workload["estimated_remaining_seconds"] > available
        ):
            risks.append("estimated_overload")
        for kind in risks:
            # Personal capacity contains no task details; notify the employee
            # and authorized task recipients for each affected scope.
            tasks = {
                c["task_id"]
                for c in frame["contexts"]
                if c["task_id"] and c["status"] in {"RUNNING", "PAUSED"}
            }
            tasks.update(
                db.scalars(
                    select(m.Task.id).where(
                        m.Task.assigned_to_id == user.id,
                        m.Task.creator.has(m.User.tenant_id == user.tenant_id),
                        ~m.Task.status.in_(
                            [m.TaskStatusEnum.DONE, m.TaskStatusEnum.DEPLOYED]
                        ),
                    )
                )
            )
            source = f"load:{user.id}:{workload['period_start'].isoformat()}:{kind}"
            message = (
                "Confirmed productive work exceeds configured capacity."
                if kind == "productive_overtime"
                else "Estimated work exceeds remaining available hours."
            )
            # One personal event per employee/day, even if several tasks are
            # affected. The reporting manager is checked against the same
            # visibility rule as the existing workload endpoint.
            personal = [user]
            manager = (
                db.scalar(
                    select(m.User).where(
                        m.User.tenant_id == user.tenant_id,
                        m.User.status == m.UserStatusEnum.ACTIVE,
                        m.User.id == user.manager_id,
                    )
                )
                if user.manager_id
                else None
            )
            if not manager and not user.manager_id and user.manager_email:
                manager = db.scalar(
                    select(m.User).where(
                        m.User.tenant_id == user.tenant_id,
                        m.User.status == m.UserStatusEnum.ACTIVE,
                        func.lower(m.User.email) == user.manager_email.lower(),
                    )
                )
            if manager:
                from .task_activity import _subject

                try:
                    _subject(db, manager, user.id)
                    if manager.id != user.id and task_module_allowed(db, manager):
                        personal.append(manager)
                except HTTPException:
                    pass  # The reporting pointer cannot grant visibility.
            for recipient in personal:
                emit_account(
                    db,
                    user=recipient,
                    kind=kind,
                    source=source,
                    subject_id=user.id,
                    title=f"Workload alert: {user.name}",
                    message=message,
                )
            for task_id in sorted(tasks):
                task = db.get(m.Task, task_id)
                emit(
                    db,
                    task=task,
                    kind=kind,
                    source=source,
                    responsible=user.id,
                    message=message,
                )
    db.commit()
    return users[-1].id if len(users) == limit else ""


_cursor = ""
_inactive_cursor = ""
_worker_thread = None
_worker_stop = threading.Event()
_worker_lock = threading.Lock()


def start_maintenance(interval_seconds=30):
    """Reuse the existing process-local maintenance pattern, one aggregate job.

    Kept independent of webhook HTTP delivery so a slow external provider cannot
    stall deadline scans. Durable inbox rows/unique keys coordinate API workers.
    """
    global _worker_thread
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _worker_stop.clear()

        def run():
            from time import monotonic

            next_scan = 0
            while not _worker_stop.is_set():
                delay = interval_seconds
                try:
                    scan_due = monotonic() >= next_scan
                    stats = maintenance(scan_workload=scan_due)
                    if scan_due:
                        next_scan = monotonic() + interval_seconds
                    # Drain a burst promptly without turning workload scans
                    # into a per-user poll or starting another worker thread.
                    if stats and stats.get("due_remaining"):
                        delay = min(1, interval_seconds)
                    else:
                        delay = min(
                            interval_seconds, max(0.01, next_scan - monotonic())
                        )
                except Exception:
                    log.exception("Workload notification maintenance failed; retrying")
                _worker_stop.wait(delay)

        _worker_thread = threading.Thread(
            target=run, name="workload-notifications", daemon=True
        )
        _worker_thread.start()


def stop_maintenance(timeout_seconds=15):
    global _worker_thread
    with _worker_lock:
        thread = _worker_thread
        _worker_stop.set()
    if thread:
        thread.join(timeout_seconds)
    with _worker_lock:
        if thread is _worker_thread and (not thread or not thread.is_alive()):
            _worker_thread = None


def maintenance(*, scan_workload=True):
    """One aggregate maintenance tick with bounded batches; no per-user timers."""
    from ..database import SessionLocal

    global _cursor, _inactive_cursor
    scan_failures = 0
    if scan_workload:
        try:
            with SessionLocal() as db:
                _cursor = scan(db, after_user=_cursor)
        except Exception:  # noqa: BLE001 -- a failed scan must not stall durable delivery
            scan_failures += 1
            log.warning(
                "notification_workload_scan_failed scope=users; retrying next sweep"
            )
        try:
            with SessionLocal() as db:
                _inactive_cursor = scan_inactive_deadlines(
                    db, after_task=_inactive_cursor
                )
        except Exception:  # noqa: BLE001 -- isolate the independent inactive-owner sweep
            scan_failures += 1
            log.warning(
                "notification_workload_scan_failed scope=inactive; retrying next sweep"
            )
    with SessionLocal() as db:
        run_delivery(db)
        stats = db.info.get("phase6_delivery_stats", {})
        stats["scan_failures"] = scan_failures
    if not scan_workload:
        return stats
    # Keep deduplication tombstones permanently, expire read alert content only.
    days = max(1, int(os.environ.get("VEE_NOTIFICATION_RETENTION_DAYS", "30")))
    with SessionLocal() as db:
        cutoff = (m.utc_now() - timedelta(days=days)).replace(tzinfo=None)
        candidates = (
            select(m.Notification.id)
            .where(
                m.Notification.dedupe_key.is_not(None),
                m.Notification.created_at < cutoff,
                m.Notification.is_read.is_(True),
                or_(
                    m.Notification.message != "Expired notification",
                    m.Notification.body.is_not(None),
                    m.Notification.title.is_not(None),
                ),
            )
            .order_by(m.Notification.created_at, m.Notification.id)
            .limit(500)
            .with_for_update(skip_locked=True)
        )
        ids = list(db.scalars(candidates))
        db.execute(
            update(m.Notification)
            .where(m.Notification.id.in_(ids))
            .values(
                dismissed_at=func.coalesce(m.Notification.dismissed_at, m.utc_now()),
                title=None,
                body=None,
                message="Expired notification",
                delivery_pending=False,
                next_delivery_at=None,
            )
        )
        db.commit()
    return stats
