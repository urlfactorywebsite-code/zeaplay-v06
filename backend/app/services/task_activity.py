"""Personal activity projection over the existing immutable task audit stream.

Caller owns commit. Activity elapsed time never writes manual actual timestamps
or productive work. All writers use reward lock ordering before user row locks.
"""

import heapq
import math
import uuid
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.orm import attributes, load_only, selectinload

from .. import models as m
from . import audit_logger as audit
from . import subtask_rewards as rewards
from .task_activity_schema import EVENTS

LIMIT = 5
DONE = {m.TaskStatusEnum.DONE, m.TaskStatusEnum.DEPLOYED}
UTC = timezone.utc


class ActivityLimitExceeded(HTTPException):
    def __init__(self, actor_id, task_id, request_id):
        self.actor_id, self.task_id, self.request_id = actor_id, task_id, request_id
        super().__init__(409, "You already have five active parent tasks. Pause one before starting or resuming another.")


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def actor(db, user_id):
    user = db.scalar(
        select(m.User)
        .where(m.User.id == user_id)
        .execution_options(populate_existing=True)
    )
    if not user or user.status != m.UserStatusEnum.ACTIVE:
        raise HTTPException(403, "An active user is required")
    return user


def _user_lock(db, user_id):
    return db.scalar(
        select(m.User)
        .where(m.User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _lock_activity_scope(db, who, task_id):
    """Share the reward barrier; lock actor/creator in deterministic order.

    Pure activity cannot change a reward input. Different users can work in
    parallel, while exclusive reward/workflow writers still exclude this scope.
    Audit guards SHARE-lock the creator: take it before the actor UPDATE lock
    when ordered first, avoiding crossed actor/creator lock upgrades.
    """
    tenant_id, user_id = who.tenant_id, who.id
    db.flush()
    if db.bind.dialect.name != "postgresql":
        rewards.lock_scope(db, task_id, tenant_id=tenant_id)
        return _user_lock(db, user_id)
    rewards.tenant_lock(db, tenant_id, shared=True)
    owner = db.execute(
        select(m.Task.created_by_id, m.User.tenant_id)
        .join(m.User, m.User.id == m.Task.created_by_id)
        .where(m.Task.id == task_id)
    ).first()
    if not owner or owner.tenant_id != tenant_id:
        raise HTTPException(404, "Task not found")
    locked = {}
    for key in sorted({user_id, owner.created_by_id}):
        locked[key] = db.scalar(
            select(m.User)
            .where(m.User.id == key)
            .with_for_update(read=key != user_id, key_share=key == user_id)
            .execution_options(populate_existing=True)
        )
    user = locked[user_id]
    if (
        not user
        or user.tenant_id != tenant_id
        or user.status != m.UserStatusEnum.ACTIVE
    ):
        raise HTTPException(403, "An active user in this workspace is required")
    return user


def _event(db, who, task_id, subtask_id, event_type, before, after, request_id=None):
    # Internal workflow hooks may release an old assignee's context after the
    # parent writer's pre-change authorization. Scope is still enforced by DB.
    row = m.AuditEvent(
        audit_schema_version=2,
        tenant_id=who.tenant_id,
        actor_id=who.id,
        task_id=task_id,
        subtask_id=subtask_id,
        entity_type="subtask" if subtask_id else "task",
        entity_id=subtask_id or task_id,
        event_type=event_type,
        before=before,
        after=after,
        payload={"source": "personal_task_activity"},
        correlation_id=request_id,
        created_at=m.utc_now(),
    )
    db.add(row)
    db.flush([row])
    return row


def _state(row):
    return {
        "status": row.status,
        "slot": row.slot,
        "subtask_id": row.subtask_id,
        "elapsed_ms": row.elapsed_ms,
        "resumed_at": row.resumed_at.isoformat() if row.resumed_at else None,
        "version": row.version,
    }


def _advance(
    db, who, row, *, status, slot=None, subtask_id=None, action, request_id=None
):
    now = m.utc_now()
    if row.version and now < utc(row.updated_at):
        raise HTTPException(
            409,
            "Server clock is behind the last activity event; retry after server time recovers",
        )
    before = _state(row) if row.version else None
    if row.resumed_at:
        row.elapsed_ms += max(
            0, int((now - utc(row.resumed_at)).total_seconds() * 1000)
        )
    row.status, row.slot, row.subtask_id = status, slot, subtask_id
    row.resumed_at = now if status == "RUNNING" else None
    row.version += 1
    row.updated_at = now
    after = {
        **_state(row),
        "action": action,
        "context_id": row.id,
        "user_id": row.user_id,
        "requested_subtask_id": subtask_id,
    }
    event_type = {
        "START": "work.started",
        "RESUME": "work.resumed",
        "PAUSE": "work.paused",
        "STOP": "work.stopped",
        "COMPLETE": "work.completed",
        "SWITCH": "work.switched",
    }[action]
    # Do not flush a dirty projection until its immutable event exists.
    with db.no_autoflush:
        event = _event(
            db, who, row.task_id, subtask_id, event_type, before, after, request_id
        )
        row.activity_event_id = event.id
        db.add(row)
        db.flush()
    return row


def command(
    db,
    *,
    actor_id,
    task_id,
    action,
    subtask_id=None,
    expected_version=None,
    request_id=None,
):
    db.flush()
    who = actor(db, actor_id)
    who = _lock_activity_scope(db, who, task_id)
    if who.status != m.UserStatusEnum.ACTIVE:
        raise HTTPException(403, "An active user is required")
    row = db.scalar(
        select(m.TaskActivityContext)
        .where(
            m.TaskActivityContext.tenant_id == who.tenant_id,
            m.TaskActivityContext.user_id == who.id,
            m.TaskActivityContext.task_id == task_id,
        )
        .execution_options(populate_existing=True)
    )
    request_id = str(request_id or uuid.uuid4())
    replay = db.scalar(
        select(m.AuditEvent).where(
            m.AuditEvent.tenant_id == who.tenant_id,
            m.AuditEvent.actor_id == who.id,
            m.AuditEvent.correlation_id == request_id,
            m.AuditEvent.event_type.in_(EVENTS),
        )
    )
    if replay:
        detail = replay.after or {}
        # A replay returns current state but never reapplies an old Start after
        # a later Pause. The original operation's arguments must still match.
        requested_action = detail.get("action")
        if (
            replay.task_id != task_id
            or requested_action
            not in {action, "SWITCH" if action == "START" else action}
            or detail.get("requested_subtask_id") != subtask_id
            or expected_version is not None
            and (replay.before or {}).get("version", 0) != expected_version
        ):
            raise HTTPException(
                409, "Request ID already used for another activity command"
            )
        return row
    if expected_version is not None and expected_version != (row.version if row else 0):
        raise HTTPException(
            409, "Activity changed in another session; refresh before retrying"
        )
    if action in {"START", "RESUME"}:
        _, task, child = audit._activity_context(db, who.id, task_id, subtask_id)
        if task.status in DONE or child and (child.completed or child.deleted_at):
            raise HTTPException(409, "Completed or deleted work cannot be started")
        if action == "RESUME" and (not row or row.status != "PAUSED"):
            raise HTTPException(409, "Only paused personal activity can be resumed")
        if action == "RESUME" and row.subtask_id != subtask_id:
            raise HTTPException(
                409, "Resume the paused activity or explicitly Start another subtask"
            )
        slots = set(
            db.scalars(
                select(m.TaskActivityContext.slot).where(
                    m.TaskActivityContext.tenant_id == who.tenant_id,
                    m.TaskActivityContext.user_id == who.id,
                    m.TaskActivityContext.status == "RUNNING",
                )
            )
        )
        slot = (
            row.slot
            if row and row.status == "RUNNING"
            else next((n for n in range(1, LIMIT + 1) if n not in slots), None)
        )
        if slot is None:
            raise ActivityLimitExceeded(who.id, task_id, request_id)
        status = "RUNNING"
        if row and row.status == "RUNNING" and row.subtask_id != subtask_id:
            action = "SWITCH"
    else:
        # Users can always release their own slot after assignment/access was
        # revoked. This grants no task-field or other-user editing authority.
        if not row:
            raise HTTPException(404, "Personal activity not found")
        if subtask_id != row.subtask_id:
            raise HTTPException(
                409, "Selected activity changed; refresh before pausing"
            )
        if action == "PAUSE" and row.status not in {"RUNNING", "PAUSED"}:
            raise HTTPException(409, "Only running personal activity can be paused")
        status, slot = ("PAUSED" if action == "PAUSE" else "STOPPED"), None
    with audit._write_savepoint(db):
        if not row:
            row = m.TaskActivityContext(
                id=str(uuid.uuid4()),
                tenant_id=who.tenant_id,
                user_id=who.id,
                task_id=task_id,
                status="STOPPED",
                elapsed_ms=0,
                version=0,
                created_at=m.utc_now(),
            )
        return _advance(
            db,
            who,
            row,
            status=status,
            slot=slot,
            subtask_id=subtask_id,
            action=action,
            request_id=request_id,
        )


def close_contexts(db, *, who, task_id, subtask_id=None, only_user=None):
    rows = list(
        db.scalars(
            select(m.TaskActivityContext)
            .where(
                m.TaskActivityContext.tenant_id == who.tenant_id,
                m.TaskActivityContext.task_id == task_id,
                m.TaskActivityContext.status.in_(["RUNNING", "PAUSED"]),
                *(
                    [m.TaskActivityContext.subtask_id == subtask_id]
                    if subtask_id
                    else []
                ),
                *([m.TaskActivityContext.user_id == only_user] if only_user else []),
            )
            .order_by(m.TaskActivityContext.user_id)
            .execution_options(populate_existing=True)
        )
    )
    for row in rows:
        _user_lock(db, row.user_id)
        _advance(
            db,
            who,
            row,
            status="COMPLETED",
            subtask_id=row.subtask_id,
            action="COMPLETE",
        )


def sync_subtask(db, *, who, task, child, previous_status):
    if child.completed or child.deleted_at:
        close_contexts(db, who=who, task_id=task.id, subtask_id=child.id)
    elif child.status != previous_status and child.status == "IN_PROGRESS":
        command(
            db, actor_id=who.id, task_id=task.id, subtask_id=child.id, action="START"
        )
    elif child.status != previous_status and child.status == "PAUSED":
        row = db.scalar(
            select(m.TaskActivityContext).where(
                m.TaskActivityContext.tenant_id == who.tenant_id,
                m.TaskActivityContext.user_id == who.id,
                m.TaskActivityContext.task_id == task.id,
            )
        )
        if row and row.status == "RUNNING" and row.subtask_id == child.id:
            command(
                db,
                actor_id=who.id,
                task_id=task.id,
                subtask_id=child.id,
                action="PAUSE",
            )


def sync_task(db, *, who, task, previous_status):
    if task.status in DONE:
        close_contexts(db, who=who, task_id=task.id)
    elif task.status != previous_status and task.status == m.TaskStatusEnum.IN_PROGRESS:
        command(db, actor_id=who.id, task_id=task.id, action="START")


def active_intervals(db, who):
    return list(
        db.scalars(
            select(m.TaskWorkInterval)
            .where(
                m.TaskWorkInterval.tenant_id == who.tenant_id,
                m.TaskWorkInterval.user_id == who.id,
                ~exists().where(
                    m.TaskWorkCorrection.original_interval_id == m.TaskWorkInterval.id
                ),
            )
            .options(
                load_only(
                    m.TaskWorkInterval.id,
                    m.TaskWorkInterval.task_id,
                    m.TaskWorkInterval.subtask_id,
                    m.TaskWorkInterval.user_id,
                    m.TaskWorkInterval.started_at,
                    m.TaskWorkInterval.ended_at,
                    m.TaskWorkInterval.created_at,
                )
            )
        )
    )


def record_work(db, *, actor_id, task_id, data):
    who = _lock_activity_scope(db, actor(db, actor_id), task_id)
    audit._activity_context(db, who.id, task_id, data.subtask_id)
    replay = db.scalar(
        select(m.TaskWorkInterval).where(
            m.TaskWorkInterval.tenant_id == who.tenant_id,
            m.TaskWorkInterval.request_id == data.request_id,
        )
    )
    if replay:
        correction = db.scalar(
            select(m.TaskWorkCorrection).where(
                m.TaskWorkCorrection.replacement_interval_id == replay.id
            )
        )
        if (
            replay.user_id,
            replay.task_id,
            replay.subtask_id,
            replay.started_at,
            replay.ended_at,
            replay.note,
            correction.original_interval_id if correction else None,
        ) != (
            who.id,
            task_id,
            data.subtask_id,
            data.started_at,
            data.ended_at,
            data.note,
            data.supersedes_id,
        ):
            raise HTTPException(
                409, "Request ID already used for different confirmed work"
            )
        return replay
    current = active_intervals(db, who)
    original = next((r for r in current if r.id == data.supersedes_id), None)
    if data.supersedes_id and (
        not original
        or original.task_id != task_id
        or original.subtask_id != data.subtask_id
    ):
        raise HTTPException(
            409,
            "Only your current confirmed interval in this task can be corrected; refresh the work log",
        )
    conflicts = [
        r
        for r in current
        if r.id != data.supersedes_id
        and r.started_at < data.ended_at
        and r.ended_at > data.started_at
    ]
    if conflicts:
        # No foreign task titles/notes in a conflict response. These are the
        # actor's own interval IDs and UTC timestamps, useful for correction.
        raise HTTPException(
            409,
            "Confirmed work overlaps your existing interval(s): "
            + "; ".join(
                f"{r.id} ({r.started_at.isoformat()} to {r.ended_at.isoformat()})"
                for r in conflicts[:5]
            )
            + ". Correct the existing log or choose non-overlapping times. No time was added.",
        )
    with audit._write_savepoint(db):
        row = audit.record_manual_work(
            db,
            actor_id=who.id,
            task_id=task_id,
            subtask_id=data.subtask_id,
            data=data.model_dump(exclude={"confirmed", "subtask_id", "supersedes_id"}),
        )
        if original:
            event = _event(
                db,
                who,
                task_id,
                data.subtask_id,
                "work.interval_corrected",
                {
                    "interval_id": original.id,
                    "start": original.started_at.isoformat(),
                    "end": original.ended_at.isoformat(),
                },
                {
                    "interval_id": row.id,
                    "start": row.started_at.isoformat(),
                    "end": row.ended_at.isoformat(),
                },
                data.request_id,
            )
            db.add(
                m.TaskWorkCorrection(
                    tenant_id=who.tenant_id,
                    user_id=who.id,
                    original_interval_id=original.id,
                    replacement_interval_id=row.id,
                    activity_event_id=event.id,
                    request_id=data.request_id,
                )
            )
            db.flush()
        return row


def allocate(intervals, lower=None, upper=None):
    """Union time, allocated once by original confirmation order during conflicts."""
    events, rows, raw = [], {}, 0.0
    for row in intervals:
        start, end = utc(row.started_at), utc(row.ended_at)
        if lower:
            start = max(start, lower)
        if upper:
            end = min(end, upper)
        if end <= start:
            continue
        rows[row.id] = row
        raw += (end - start).total_seconds()
        events += [(start, 1, row.id), (end, -1, row.id)]
    heap, active, amounts = [], set(), defaultdict(float)
    previous = None
    for instant, kind, key in sorted(events):
        while heap and heap[0][1] not in active:
            heapq.heappop(heap)
        if previous and heap:
            row = rows[heap[0][1]]
            amounts[(row.task_id, row.subtask_id)] += (
                instant - previous
            ).total_seconds()
        if kind == 1:
            active.add(key)
            heapq.heappush(heap, (utc(rows[key].created_at), key))
        else:
            active.discard(key)
        previous = instant
    total = sum(amounts.values())
    return {
        "total_seconds": total,
        "overlap_seconds": max(0, raw - total),
        "by_scope": dict(amounts),
    }


def _wall(day, value, zone):
    parsed = None
    for pattern in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
        try:
            parsed = datetime.strptime(value.strip(), pattern).time()  # noqa: DTZ007 -- configured civil clock; zone attached below
            break
        except (ValueError, AttributeError):
            pass
    if parsed is None:
        raise ValueError("Missing or invalid configured shift")
    naive = datetime.combine(day, parsed)
    options = {
        naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        for fold in (0, 1)
        if naive.replace(tzinfo=zone, fold=fold)
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == naive
    }
    if len(options) != 1:
        raise ValueError(
            "Configured shift boundary is ambiguous or nonexistent on this date"
        )
    return options.pop()


def capacity(user, day, zone, *, after=None):
    try:
        start, end = (
            _wall(day, user.shift_start, zone),
            _wall(day, user.shift_end, zone),
        )
        if end == start:
            return None
        if end < start:
            end = _wall(day + timedelta(days=1), user.shift_end, zone)
        breaks = []
        for prefix in ("morning_break", "lunch_break", "evening_break"):
            a, b = getattr(user, prefix + "_start"), getattr(user, prefix + "_end")
            if not a and not b:
                continue
            left, right = _wall(day, a, zone), _wall(day, b, zone)
            if left < start and end.astimezone(zone).date() > day:
                left = _wall(day + timedelta(days=1), a, zone)
                right = _wall(day + timedelta(days=1), b, zone)
            if right < left:
                right = _wall(left.astimezone(zone).date() + timedelta(days=1), b, zone)
            left, right = max(start, left), min(end, right)
            if right > left:
                breaks.append((left, right))
        if after is not None:
            start = max(start, after)
            breaks = [(max(start, left), right) for left, right in breaks if right > start]
        merged, seconds = None, 0
        for left, right in sorted(breaks):
            if merged and left <= merged[1]:
                merged = (merged[0], max(merged[1], right))
            else:
                if merged:
                    seconds += (merged[1] - merged[0]).total_seconds()
                merged = (left, right)
        if merged:
            seconds += (merged[1] - merged[0]).total_seconds()
        return max(0, (end - start).total_seconds() - seconds)
    except (ValueError, OverflowError):
        return None


def _subject(db, who, user_id):
    target = (
        who
        if not user_id or user_id == who.id
        else db.scalar(
            select(m.User)
            .where(
                m.User.id == user_id,
                m.User.tenant_id == who.tenant_id,
                m.User.status == m.UserStatusEnum.ACTIVE,
            )
            .execution_options(populate_existing=True)
        )
    )
    if not target:
        raise HTTPException(404, "Workload user not found")
    if (
        target.id != who.id
        and who.role not in {m.RoleEnum.OWNER, m.RoleEnum.ADMIN}
        and not (who.role == m.RoleEnum.MANAGER and target.manager_id == who.id)
    ):
        raise HTTPException(
            403, "You can view only your workload or authorized direct reports"
        )
    return target


def snapshot(db, *, actor_id, user_id=None, include_elapsed=True):
    from ..routers.tasks import _apply_task_visibility

    who = actor(db, actor_id)
    target = _subject(db, who, user_id)
    from .workload_notifications import preferences
    pref = preferences(db, target.id)
    near_hours = pref.near_deadline_hours if pref else 24
    now = m.utc_now()
    zone_issue = None
    try:
        zone = ZoneInfo(target.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone, zone_issue = (
            ZoneInfo("UTC"),
            "Invalid configured timezone; UTC used and capacity is unknown",
        )
    day = now.astimezone(zone).date()
    lower = datetime.combine(day, time.min, zone).astimezone(UTC)
    upper = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
    contexts = list(
        db.scalars(
            select(m.TaskActivityContext)
            .where(
                m.TaskActivityContext.tenant_id == who.tenant_id,
                m.TaskActivityContext.user_id == target.id,
            )
            .order_by(m.TaskActivityContext.updated_at.desc())
            .execution_options(populate_existing=True)
        )
    )
    # Completed segments belong to the selection BEFORE an event (including a
    # switch); the current running segment belongs to the current selection.
    prior_child = m.AuditEvent.before["subtask_id"].as_string()
    segment_delta = m.AuditEvent.after["elapsed_ms"].as_integer() - func.coalesce(
        m.AuditEvent.before["elapsed_ms"].as_integer(), 0
    )
    child_elapsed = {}
    # No event scan for parent-only activity. Bounded batches avoid SQLite's
    # expression-depth limit and giant OR trees for long-lived user histories.
    selected = [c for c in contexts if c.subtask_id] if include_elapsed else []
    for offset in range(0, len(selected), 100):
        batch = selected[offset : offset + 100]
        child_elapsed.update(
            {
                (task_id, child_id): milliseconds / 1000
                for task_id, child_id, milliseconds in db.execute(
                    select(m.AuditEvent.task_id, prior_child, func.sum(segment_delta))
                    .where(
                        m.AuditEvent.tenant_id == who.tenant_id,
                        m.AuditEvent.task_id.in_([c.task_id for c in batch]),
                        m.AuditEvent.event_type.in_(EVENTS),
                        m.AuditEvent.after["user_id"].as_string() == target.id,
                        # READ COMMITTED may see a later event than the context query.
                        # Bound history to the selected projection version so that a
                        # concurrently paused/switched segment cannot be counted twice.
                        or_(
                            false(),
                            *[
                                and_(
                                    m.AuditEvent.after["context_id"].as_string()
                                    == c.id,
                                    m.AuditEvent.after["version"].as_integer()
                                    <= c.version,
                                    prior_child == c.subtask_id,
                                )
                                for c in batch
                            ],
                        ),
                    )
                    .group_by(m.AuditEvent.task_id, prior_child)
                ).all()
            }
        )
    intervals = active_intervals(db, target)
    daily, lifetime = allocate(intervals, lower, upper), allocate(intervals)
    relevant = (
        select(m.Task)
        .options(
            load_only(
                m.Task.id,
                m.Task.created_by_id,
                m.Task.title,
                m.Task.status,
                m.Task.priority,
                m.Task.assigned_to_id,
                m.Task.due_at,
                m.Task.estimated_hours,
            ),
            selectinload(m.Task.subtasks).load_only(
                m.Subtask.id,
                m.Subtask.task_id,
                m.Subtask.title,
                m.Subtask.completed,
                m.Subtask.workflow_version,
                m.Subtask.workflow_status,
                m.Subtask.deleted_at,
                m.Subtask.planned_end_date,
                m.Subtask.reward_timezone,
                m.Subtask.actual_start_at,
                m.Subtask.actual_end_at,
            ),
        )
        .where(
            or_(
                m.Task.assigned_to_id == target.id,
                and_(m.Task.assigned_to_id.is_(None), m.Task.created_by_id == target.id),
                m.Task.id.in_([c.task_id for c in contexts]),
            )
        )
    )
    visible = db.execute(_apply_task_visibility(relevant, who)).unique().scalars().all()
    # Historical planned rows may predate a captured deadline timezone. Resolve
    # their creator's CURRENT configured zone consistently for every subject,
    # without inventing a historical capture or performing a query per child.
    uncaptured = [t for t in visible if any(c.planned_end_date and not c.reward_timezone for c in t.subtasks)]
    if uncaptured:
        creators = {u.id: u for u in db.scalars(select(m.User).where(
            m.User.id.in_({t.created_by_id for t in uncaptured}), m.User.tenant_id == who.tenant_id
        ).options(load_only(m.User.id, m.User.tenant_id, m.User.timezone)))}
        for task in uncaptured:
            if task.created_by_id in creators:
                attributes.set_committed_value(task, "creator", creators[task.created_by_id])
    tasks = {t.id: t for t in visible}
    totals = defaultdict(float)
    for (task_id, _), seconds in lifetime["by_scope"].items():
        totals[task_id] += seconds
    result = []
    for row in contexts:
        task = tasks.get(row.task_id)
        child = (
            next((c for c in task.subtasks if c.id == row.subtask_id), None)
            if task
            else None
        )
        if not task and target.id != who.id:
            if row.status == "RUNNING":
                result.append(
                    {
                        "id": f"restricted-slot-{row.slot}",
                        "task_id": "",
                        "subtask_id": None,
                        "task_title": "Restricted task",
                        "subtask_title": None,
                        "priority": None,
                        "status": "RUNNING",
                        "slot": row.slot,
                        "version": 0,
                        "elapsed_seconds": 0,
                        "elapsed_ms": 0,
                        "resumed_at": None,
                        "productive_seconds": 0,
                        "subtask_productive_seconds": None,
                        "subtask_elapsed_seconds": None,
                        "actual_start_at": None,
                        "actual_end_at": None,
                        "deadline": None,
                        "task_status": None,
                        "subtask_status": None,
                        "can_start": False,
                        "restricted": True,
                    }
                )
            continue
        elapsed = row.elapsed_ms / 1000 + (
            max(0, (now - utc(row.resumed_at)).total_seconds()) if row.resumed_at else 0
        )
        result.append(
            {
                "id": row.id,
                "task_id": row.task_id,
                "subtask_id": row.subtask_id,
                "task_title": task.title if task else "Task access changed",
                "subtask_title": child.title if child else None,
                "priority": task.priority.value if task else None,
                "status": row.status,
                "task_status": task.status.value if task else None,
                "subtask_status": child.status if child else None,
                "slot": row.slot,
                "version": row.version,
                "elapsed_seconds": elapsed,
                "elapsed_ms": row.elapsed_ms,
                "resumed_at": row.resumed_at,
                "productive_seconds": totals[row.task_id],
                "subtask_productive_seconds": lifetime["by_scope"].get(
                    (row.task_id, row.subtask_id), 0
                )
                if row.subtask_id
                else None,
                "subtask_elapsed_seconds": (
                    child_elapsed.get((row.task_id, row.subtask_id), 0)
                    + (
                        max(0, (now - utc(row.resumed_at)).total_seconds())
                        if row.resumed_at
                        else 0
                    )
                )
                if row.subtask_id
                else None,
                "actual_start_at": child.actual_start_at if child else None,
                "actual_end_at": child.actual_end_at if child else None,
                "deadline": deadline(task, child, zone) if task else None,
                "can_start": bool(
                    task
                    and task.status not in DONE
                    and not (child and (child.completed or child.deleted_at))
                ),
            }
        )
    count = sum(row.status == "RUNNING" for row in contexts)
    personal_tasks = {
        row.task_id for row in contexts if row.status in {"RUNNING", "PAUSED"}
    }
    workload_tasks = [
        t
        for t in visible
        if (t.assigned_to_id == target.id or (t.assigned_to_id is None and t.created_by_id == target.id) or t.id in personal_tasks)
    ]
    estimates = [
        t
        for t in workload_tasks
        if t.status not in DONE and t.estimated_hours is not None
        and math.isfinite(t.estimated_hours)
        and t.estimated_hours >= 0
    ]
    remaining = sum(max(0, t.estimated_hours * 3600 - totals[t.id]) for t in estimates)
    due_tasks, due_children, near = [], [], []
    for task in workload_tasks:
        due = deadline(task, None, zone) if task.status not in DONE else None
        if due and due < now:
            due_tasks.append({"task_id": task.id, "title": task.title, "deadline": due})
        elif due and due <= now + timedelta(hours=near_hours):
            near.append(
                {
                    "task_id": task.id,
                    "subtask_id": None,
                    "title": task.title,
                    "deadline": due,
                }
            )
        for child in task.subtasks:
            if child.completed or child.deleted_at or (task.status in DONE and not child.managed):
                continue
            due = deadline(task, child, zone)
            item = {
                "task_id": task.id,
                "subtask_id": child.id,
                "title": child.title,
                "deadline": due,
            }
            if due and due < now:
                due_children.append(item)
            elif due and due <= now + timedelta(hours=near_hours):
                near.append(item)
    configured = capacity(target, day, zone) if not zone_issue else None
    future_capacity = capacity(target, day, zone, after=now) if not zone_issue else None
    if pref and pref.productive_capacity_hours is not None and not zone_issue:
        configured = pref.productive_capacity_hours * 3600
        if future_capacity is None:
            future_capacity = max(0, (upper - now).total_seconds())
    remaining_capacity = min(max(0, configured - daily["total_seconds"]), future_capacity) if configured is not None and future_capacity is not None else None
    return {
        "user_id": target.id,
        "user_name": target.name,
        "read_only": target.id != who.id,
        "server_now": now,
        "timezone": zone.key,
        "active_count": count,
        "limit": LIMIT,
        "contexts": result,
        "workload": {
            "period_start": lower,
            "period_end": upper,
            "manual_seconds": daily["total_seconds"],
            "overlap_seconds": daily["overlap_seconds"],
            "estimated_remaining_seconds": remaining,
            "unestimated_tasks": sum(t.status not in DONE for t in workload_tasks) - len(estimates),
            "capacity_seconds": configured,
            "remaining_capacity_seconds": remaining_capacity,
            "overtime_threshold_seconds": (pref.overtime_threshold_minutes if pref else 0) * 60,
            "overtime_seconds": max(0, daily["total_seconds"] - configured)
            if configured is not None
            else None,
            "capacity_note": zone_issue
            or (
                None
                if configured is not None
                else "Configure a valid shift and breaks to calculate capacity; no daily-hours default is applied"
            ),
            "near_deadline": near,
            "overdue_tasks": due_tasks,
            "overdue_subtasks": due_children,
            "near_deadline_window_hours": near_hours,
        },
    }


def deadline(task, child, zone):
    if child and child.planned_end_date:
        try:
            creator = getattr(task, "creator", None) if not child.reward_timezone else None
            local = ZoneInfo(child.reward_timezone) if child.reward_timezone else ZoneInfo(creator.timezone or "UTC") if creator else zone
            return datetime.combine(
                child.planned_end_date + timedelta(days=1), time.min, local
            ).astimezone(UTC) - timedelta(microseconds=1)
        except (OverflowError, ValueError, ZoneInfoNotFoundError):
            return None
    return utc(task.due_at) if task.due_at else None


def work_log(db, *, actor_id, task_id, limit=50):
    who, _, _ = audit._activity_context(db, actor_id, task_id, write=False)
    intervals = db.scalars(
        select(m.TaskWorkInterval)
        .where(
            m.TaskWorkInterval.tenant_id == who.tenant_id,
            m.TaskWorkInterval.user_id == who.id,
            m.TaskWorkInterval.task_id == task_id,
        )
        .order_by(m.TaskWorkInterval.created_at.desc(), m.TaskWorkInterval.id.desc())
        .limit(limit)
    )
    superseded = set(
        db.scalars(
            select(m.TaskWorkCorrection.original_interval_id).where(
                m.TaskWorkCorrection.tenant_id == who.tenant_id,
                m.TaskWorkCorrection.user_id == who.id,
            )
        )
    )
    return [
        {
            "id": row.id,
            "subtask_id": row.subtask_id,
            "started_at": row.started_at,
            "ended_at": row.ended_at,
            "note": row.note,
            "superseded": row.id in superseded,
        }
        for row in intervals
    ]
