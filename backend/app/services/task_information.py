"""Authorized task read model. Never posts rewards, repairs history or writes time."""
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.orm import load_only, selectinload

from .. import models as m
from ..tickets.models import XpLedger
from . import subtask_rewards as rewards
from . import task_activity as activity
from .points_table import resolve_task_points

SECTIONS = {"overview", "timeline", "subtasks", "points", "activity"}
COVERAGE = (
    "Recorded history only. Legacy history may be incomplete; missing transitions and "
    "main-task payouts are not reconstructed. Personal activity is separate from workflow status."
)
# Audit logs also contain network/security metadata. Expose task fields only,
# never arbitrary metadata, IP addresses, user agents, credentials or configuration.
FIELDS = {
    "title", "description", "status", "priority", "priority_override", "assigned_to_id",
    "assigned_to_ids", "assigned_at", "due_at", "completed_at", "estimated_hours", "team",
    "planned_start_date", "planned_end_date", "actual_start_at", "actual_end_at",
    "approval_status", "approval_required", "approver_id", "clarity_rating", "tags",
    "completed", "deleted_at", "workflow_version", "point_policy_version", "version",
    "note", "notes", "content", "started_at", "ended_at", "start", "end", "interval_id",
    "elapsed_ms", "slot", "subtask_id", "user_id", "context_id", "resumed_at", "components",
    "active_entries", "follower_ids", "recurrence_rule", "attachments", "dependencies", "fields",
}
PERSON_FIELDS = {"assigned_to_id", "assigned_to_ids", "approver_id", "follower_ids", "user_id"}


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return activity.utc(value) if value is not None else None


def values(value):
    return {key: item for key, item in value.items() if key in FIELDS} if isinstance(value, dict) else {}


def safe_values(value, people):
    result = values(value)
    for key in PERSON_FIELDS & result.keys():
        item = result[key]
        if isinstance(item, list):
            result[key] = [user if isinstance(user, str) and user in people else "[restricted user]" for user in item]
        elif item is not None and (not isinstance(item, str) or item not in people):
            result[key] = "[restricted user]"
    return result


def person(user, tenant):
    return {"id": user.id, "name": user.name} if user and user.tenant_id == tenant else None


def parent(db, task_id, who):
    from ..routers.tasks import _ensure_task_access

    # Authenticate the live record, not a detached cached role. Do not load an
    # unbounded subtask/dependency hierarchy merely to authorize this read.
    who = db.scalar(select(m.User).where(m.User.id == who.id).options(load_only(
        m.User.id, m.User.name, m.User.tenant_id, m.User.role, m.User.status, m.User.department_id,
    )).execution_options(populate_existing=True))
    if not who or who.status != m.UserStatusEnum.ACTIVE:
        raise HTTPException(403, "An active user is required")
    task = db.scalar(select(m.Task).where(m.Task.id == task_id).options(
        load_only(m.Task.id, m.Task.title, m.Task.description, m.Task.team, m.Task.priority,
                  m.Task.status, m.Task.assigned_to_id, m.Task.created_by_id, m.Task.created_at,
                  m.Task.updated_at, m.Task.assigned_at, m.Task.estimated_hours, m.Task.due_at,
                  m.Task.completed_at, m.Task.approval_status, m.Task.approval_required),
        selectinload(m.Task.creator).load_only(m.User.id, m.User.name, m.User.tenant_id),
        selectinload(m.Task.assignee).load_only(m.User.id, m.User.name, m.User.tenant_id, m.User.department_id),
        selectinload(m.Task.followers).load_only(m.User.id),
    ))
    if not task:
        raise HTTPException(404, "Task not found")
    _ensure_task_access(task, who)
    return task, who


def productive(db, task, tenant):
    """Reuse the confirmed-work union across each contributor's OTHER tasks too.

    Other tasks' names, notes and identities never leave this function. Allocation
    order must match Phase 4; unioning only this parent would double-count overlaps.
    """
    participants = select(m.TaskWorkInterval.user_id).where(
        m.TaskWorkInterval.tenant_id == tenant, m.TaskWorkInterval.task_id == task.id,
    ).distinct()
    rows = db.scalars(select(m.TaskWorkInterval).where(
        m.TaskWorkInterval.tenant_id == tenant,
        m.TaskWorkInterval.user_id.in_(participants),
        ~exists().where(m.TaskWorkCorrection.original_interval_id == m.TaskWorkInterval.id),
    ).options(load_only(
        m.TaskWorkInterval.id, m.TaskWorkInterval.task_id, m.TaskWorkInterval.subtask_id,
        m.TaskWorkInterval.user_id, m.TaskWorkInterval.started_at,
        m.TaskWorkInterval.ended_at, m.TaskWorkInterval.created_at,
    )))
    by_user, result = defaultdict(list), defaultdict(float)
    for row in rows:
        by_user[row.user_id].append(row)
    for intervals in by_user.values():
        for (task_id, child_id), seconds in activity.allocate(intervals)["by_scope"].items():
            if task_id == task.id:
                result[child_id] += seconds
    return result


def elapsed(db, task, tenant, now, child_ids=None):
    """Persisted parent totals + current segment; child history stays version bounded."""
    contexts = list(db.scalars(select(m.TaskActivityContext).where(
        m.TaskActivityContext.tenant_id == tenant, m.TaskActivityContext.task_id == task.id,
    ).options(load_only(m.TaskActivityContext.id, m.TaskActivityContext.subtask_id,
                        m.TaskActivityContext.status, m.TaskActivityContext.elapsed_ms,
                        m.TaskActivityContext.resumed_at, m.TaskActivityContext.version))))
    total, children = 0.0, defaultdict(float)
    for row in contexts:
        running = max(0, (now - utc(row.resumed_at)).total_seconds()) if row.status == "RUNNING" and row.resumed_at else 0
        total += row.elapsed_ms / 1000 + running
        if row.subtask_id and (child_ids is None or row.subtask_id in child_ids):
            children[row.subtask_id] += running
    if child_ids is not None and not child_ids:
        return total, children
    # Join the captured context/version in bounded batches instead of loading
    # every event or running one query per child. BEFORE owns a switched segment.
    prior_child = m.AuditEvent.before["subtask_id"].as_string()
    delta = m.AuditEvent.after["elapsed_ms"].as_integer() - func.coalesce(m.AuditEvent.before["elapsed_ms"].as_integer(), 0)
    for offset in range(0, len(contexts), 100):
        batch = contexts[offset:offset + 100]
        for child, milliseconds in db.execute(select(prior_child, func.sum(delta)).where(
            m.AuditEvent.tenant_id == tenant, m.AuditEvent.task_id == task.id,
            m.AuditEvent.event_type.in_(activity.EVENTS), prior_child.is_not(None),
            *([prior_child.in_(child_ids)] if child_ids is not None else []),
            or_(*[and_(m.AuditEvent.after["context_id"].as_string() == c.id,
                       m.AuditEvent.after["version"].as_integer() <= c.version) for c in batch]),
        ).group_by(prior_child)):
            children[child] += milliseconds / 1000
    return total, children


def ledger_scope(tenant, task_id):
    # Include every explicitly task-linked v2 ledger policy, including future
    # main-task adjustments. Legacy ticket XP has no verified task relationship.
    return (XpLedger.tenant_id == tenant, XpLedger.task_id == task_id, XpLedger.record_version == 2)


def point_summary(db, task, tenant):
    eligible = select(
        m.Subtask.id, m.Subtask.completed,
        func.row_number().over(order_by=(m.Subtask.created_at, m.Subtask.id)).label("ordinal"),
    ).where(m.Subtask.task_id == task.id, m.Subtask.point_policy_version == rewards.POLICY,
            m.Subtask.deleted_at.is_(None)).subquery()
    counts = select(
        func.count().label("eligible_count"),
        func.coalesce(func.sum(case((and_(eligible.c.ordinal > 1, eligible.c.completed.is_(False)), 1), else_=0)), 0).label("available"),
    ).select_from(eligible).subquery()
    ledger = select(
        XpLedger.user_id, XpLedger.component_type, XpLedger.subtask_id.is_not(None).label("child"),
        func.sum(XpLedger.points).label("points"),
    ).where(*ledger_scope(tenant, task.id)).group_by(
        XpLedger.user_id, XpLedger.component_type, XpLedger.subtask_id.is_not(None),
    ).subquery()
    # Capacity counts and signed recipient/component totals share one statement
    # snapshot, including during payout/deletion/reassignment.
    rows = db.execute(select(counts, ledger, m.Task.priority.label("current_priority"),
                             m.Task.team.label("current_team"), m.TaskWorkflowSettings.reward_policy_data)
                      .select_from(counts).join(m.Task, m.Task.id == task.id)
                      .outerjoin(m.TaskWorkflowSettings, and_(m.TaskWorkflowSettings.tenant_id == tenant,
                                                            m.TaskWorkflowSettings.point_policy_version == rewards.POLICY))
                      .outerjoin(ledger, literal(True))
                      .where(m.Task.creator.has(m.User.tenant_id == tenant))).all()
    if not rows:
        raise HTTPException(404, "Task not found")
    components = dict.fromkeys(("BASE", "BONUS", "PENALTY", "ADJUSTMENT", "REVERSAL"), 0)
    subtask_components, main_components = dict.fromkeys(components, 0), dict.fromkeys(components, 0)
    recipients, child_net, net = {}, 0, 0
    for row in rows:
        if row.user_id is None:
            continue
        components[row.component_type] += row.points
        net += row.points
        if row.child:
            child_net += row.points
        (subtask_components if row.child else main_components)[row.component_type] += row.points
        recipient = recipients.setdefault(row.user_id, {"id": row.user_id, "net": 0, "main_net": 0, "subtask_net": 0, "components": dict.fromkeys(components, 0)})
        recipient["net"] += row.points
        recipient["subtask_net" if row.child else "main_net"] += row.points
        recipient["components"][row.component_type] += row.points
    users = {u.id: u for u in db.scalars(select(m.User).where(m.User.tenant_id == tenant, m.User.id.in_(recipients)).options(
        load_only(m.User.id, m.User.name, m.User.tenant_id),
    ))} if recipients else {}
    for key, recipient in recipients.items():
        recipient["name"] = users[key].name if key in users else "Unavailable recipient"
    current = rows[0]
    rule = rewards._snapshot_points(db, team=current.current_team, priority=current.current_priority, data=current.reward_policy_data) if current.eligible_count else {"base": 0}
    main = resolve_task_points(db, team=current.current_team, priority=current.current_priority)
    return {
        "main_base_value": main["base"], "main_earned": None,
        "subtask_base_capacity": max(0, rows[0].eligible_count - 1) * rule["base"],
        "subtask_available_base": rows[0].available * rule["base"],
        "subtask_earned": child_net, "components": components,
        "subtask_components": subtask_components, "main_recorded_components": main_components,
        "main_recorded_net": net - child_net,
        "verified_net_earned": net, "total_net_earned": None,
        "recipients": sorted(recipients.values(), key=lambda r: r["id"]),
        "coverage": "Verified task-linked ledger only. Main-task payout history is incomplete; full task net is unknown. Base capacity and available base exclude potential bonuses/penalties. Components show posted amounts; reversals are separate signed adjustments.",
    }


def event_index(db, who, task, *, timeline=False, subtask_id=None):
    from ..routers.comments import _ensure_comment_access
    from ..routers.logs import _apply_scope_filters

    tenant, task_id = who.tenant_id, task.id
    e, log, comment = m.AuditEvent, m.AuditLog, m.Comment
    actor_member = select(m.User.id).where(m.User.tenant_id == tenant)
    valid_child = or_(e.subtask_id.is_(None), exists().where(m.Subtask.id == e.subtask_id, m.Subtask.task_id == task_id))
    modern = and_(e.audit_schema_version == 2, e.tenant_id == tenant, e.task_id == task_id, valid_child)
    legacy = and_(e.audit_schema_version == 1, e.entity_type == "task", e.entity_id == task_id,
                  or_(e.actor_id.is_(None), e.actor_id.in_(actor_member)))
    filters = [or_(modern, legacy)]
    logs = [log.entity_type == "task", log.entity_id == task_id, log.deleted_at.is_(None),
            log.category == m.AuditLogCategoryEnum.TASK,
            or_(log.actor_id.is_(None), log.actor_id.in_(actor_member))]
    if subtask_id:
        filters = [modern, or_(e.subtask_id == subtask_id,
                              and_(e.event_type.in_(activity.EVENTS), e.before["subtask_id"].as_string() == subtask_id))]
        logs.append(literal(False))
    def workflow_status(snapshot):
        completed = cast(snapshot["completed"].as_string(), String)
        return func.coalesce(snapshot["workflow_status"].as_string(), snapshot["status"].as_string(),
                             case((completed.in_(["true", "1"]), "COMPLETED"), (completed.in_(["false", "0"]), "TODO"), else_=None))

    previous, new = workflow_status(e.before), workflow_status(e.after)
    log_previous, log_new = log.before["status"].as_string(), log.after["status"].as_string()
    if timeline:
        # Legacy status observations without a previous value cannot establish a
        # transition. Structured legacy AuditLog remains the transition source.
        filters.extend([new.is_not(None), or_(previous.is_(None), previous != new, e.event_type.in_(activity.EVENTS))])
        logs.extend([log_new.is_not(None), or_(log_previous.is_(None), log_previous != log_new)])
    personal = e.event_type.in_(activity.EVENTS)
    channel = case((personal, "personal activity"),
                   (e.event_type.in_(["task.manual_work_logged", "subtask.manual_work_logged", "work.interval_corrected"]), "productive work"),
                   else_="workflow")

    def index(source, key, at, actor, child, old, current, stream, stream_id=None, sequence=None):
        return select(literal(source).label("source"), cast(key, String).label("id"), at.label("at"),
                      actor.label("actor_id"), child.label("child_id"), old.label("previous"),
                      current.label("new"), stream.label("channel"),
                      (stream_id if stream_id is not None else cast(literal(None), String)).label("stream_id"),
                      (sequence if sequence is not None else literal(0)).label("sequence"))

    parts = [
        index("audit_event", e.id, e.created_at, e.actor_id, e.subtask_id, previous, new, channel,
              case((personal, e.after["context_id"].as_string()), else_=None),
              case((personal, e.after["version"].as_integer()), else_=0)).where(*filters),
        _apply_scope_filters(
            index("audit_log", log.id, log.created_at, log.actor_id, cast(literal(None), String), log_previous, log_new, literal("workflow")).where(*logs),
            current_user=who, db=db,
        ),
    ]
    if not timeline and not subtask_id:
        try:
            _ensure_comment_access(task, who)
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
        else:
            parts.append(index("comment", comment.id, comment.created_at, comment.user_id,
                               cast(literal(None), String), cast(literal(None), String), cast(literal(None), String), literal("note")).where(
                                   comment.task_id == task_id, comment.user_id.in_(actor_member)))
    if not timeline:
        parts.append(index("ledger", XpLedger.id, XpLedger.created_at, cast(literal(None), String),
                           XpLedger.subtask_id, cast(literal(None), String), cast(literal(None), String), literal("points")).where(
                               *ledger_scope(tenant, task_id), *([XpLedger.subtask_id == subtask_id] if subtask_id else [])))
    return union_all(*parts).subquery()


def events(db, who, task, *, page, size, timeline, child_id):
    tenant = who.tenant_id
    index = event_index(db, who, task, timeline=timeline, subtask_id=child_id)
    total = db.scalar(select(func.count()).select_from(index))
    if timeline:
        # A duration is known only between consecutive, consistent transitions
        # of the same workflow/personal stream, even across pagination boundaries.
        partition = [case((index.c.channel == "personal activity", None), else_=index.c.child_id), index.c.channel, index.c.stream_id]
        order = [index.c.at, index.c.sequence, index.c.source, index.c.id]
        history = select(index,
            func.lead(index.c.at).over(partition_by=partition, order_by=order).label("next_at"),
            func.lead(index.c.previous).over(partition_by=partition, order_by=order).label("next_previous"),
            func.lead(index.c.sequence).over(partition_by=partition, order_by=order).label("next_sequence"),
        ).subquery()
        stmt = select(history).order_by(history.c.at, history.c.sequence, history.c.source, history.c.id)
    else:
        stmt = select(index).order_by(index.c.at.desc(), index.c.source, index.c.id)
    rows = db.execute(stmt.offset((page - 1) * size).limit(size)).all()
    classes = {"ledger": XpLedger, "audit_event": m.AuditEvent, "audit_log": m.AuditLog, "comment": m.Comment}
    records = {}
    for source, cls in classes.items():
        ids = [row.id for row in rows if row.source == source]
        linked = [record.activity_event_id for (kind, _), record in records.items() if kind == "ledger"] if source == "audit_event" else []
        if ids or linked:
            # UUID column comparison expects UUID objects on SQLite too.
            keys = [uuid.UUID(key) for key in ids] if source == "ledger" else ids
            condition = cls.id.in_(keys)
            if linked:
                condition = or_(condition, and_(cls.id.in_(linked), cls.tenant_id == tenant, cls.task_id == task.id))
            records.update({(source, str(record.id)): record for record in db.scalars(select(cls).where(condition))})
    actor_ids = {row.actor_id for row in rows if row.actor_id}
    actor_ids.update(record.actor_id for (kind, _), record in records.items() if kind == "audit_event" and record.actor_id)
    # Legacy diffs can contain cross-wired or subsequently moved assignments.
    # Resolve every referenced person in the SAME batch as actors, then mask
    # foreign references just as the existing task serializer does.
    for record in records.values():
        for field in ("before", "after", "payload"):
            for key, value in values(getattr(record, field, None)).items():
                if key in PERSON_FIELDS:
                    actor_ids.update(v for v in (value if isinstance(value, list) else [value]) if isinstance(v, str))
    users = {u.id: u for u in db.scalars(select(m.User).where(m.User.tenant_id == tenant, m.User.id.in_(actor_ids)).options(
        load_only(m.User.id, m.User.name, m.User.tenant_id),
    ))} if actor_ids else {}
    result = []
    for row in rows:
        record_id = str(uuid.UUID(row.id)) if row.source == "ledger" else row.id
        record = records.get((row.source, record_id))
        if not record:
            continue
        before, after, details = None, None, {}
        actor_id = row.actor_id
        if row.source in {"audit_event", "audit_log"}:
            before, after = safe_values(record.before, users), safe_values(record.after, users)
            event_type = record.event_type if row.source == "audit_event" else record.action
            if row.source == "audit_event":
                details = safe_values(record.payload, users)
                # Raw confirmed-work notes have a stricter existing own-log
                # contract than shared task fields. Preserve the event/times,
                # but do not broaden that contract through the audit projection.
                if event_type in {"task.manual_work_logged", "subtask.manual_work_logged"} and record.actor_id != who.id:
                    before.pop("note", None)
                    after.pop("note", None)
                    details.pop("note", None)
        elif row.source == "comment":
            event_type, details = "comment.recorded", {"content": record.content}
        else:
            linked_event = records.get(("audit_event", record.activity_event_id))
            actor_id = linked_event.actor_id if linked_event else None
            event_type = "points." + record.component_type.lower()
            details = {"delta": record.points, "component": record.component_type,
                       "recipient_id": record.user_id, "policy_version": record.policy_version,
                       "reason": record.reason, "reversal_of_id": str(record.reversal_of_id) if record.reversal_of_id else None,
                       "event_id": record.activity_event_id}
        duration = None
        personal = row.channel == "personal activity"
        known_interval = (not timeline or not personal or row.next_sequence == row.sequence + 1)
        visible_interval = not (row.source == "audit_log" and who.role not in {m.RoleEnum.OWNER, m.RoleEnum.ADMIN})
        selected_interval = not child_id or not personal or row.child_id == child_id
        if timeline and row.next_at and row.new and row.next_previous == row.new and known_interval and visible_interval and selected_interval:
            duration = max(0, (utc(row.next_at) - utc(row.at)).total_seconds())
        result.append({"kind": "event", "id": f"{row.source}:{row.id}", "source": row.source,
                       "event_type": event_type, "timestamp": utc(row.at),
                       "actor": person(users.get(actor_id), tenant), "subtask_id": row.child_id,
                       "channel": row.channel, "previous_status": row.previous, "new_status": row.new,
                       "duration_seconds": duration, "before": before, "after": after, "details": details})
    return result, total


def children(db, task, tenant, *, page, size, search, now):
    eligible = select(m.Subtask.id, func.row_number().over(order_by=(m.Subtask.created_at, m.Subtask.id)).label("ordinal")).where(
        m.Subtask.task_id == task.id, m.Subtask.point_policy_version == rewards.POLICY,
        m.Subtask.deleted_at.is_(None),
    ).subquery()
    stmt = select(m.Subtask, eligible.c.ordinal, m.Task.priority.label("current_priority"),
                  m.Task.team.label("current_team"), m.TaskWorkflowSettings.reward_policy_data)
    stmt = stmt.join(m.Task, m.Task.id == m.Subtask.task_id).outerjoin(eligible, eligible.c.id == m.Subtask.id).outerjoin(
        m.TaskWorkflowSettings, and_(m.TaskWorkflowSettings.tenant_id == tenant, m.TaskWorkflowSettings.point_policy_version == rewards.POLICY),
    ).where(m.Subtask.task_id == task.id, m.Task.creator.has(m.User.tenant_id == tenant))
    count_stmt = select(func.count()).select_from(m.Subtask).join(m.Task, m.Task.id == m.Subtask.task_id).where(
        m.Subtask.task_id == task.id, m.Task.creator.has(m.User.tenant_id == tenant),
    )
    if search:
        # Literal substring search: wildcard characters must not change meaning.
        matches = m.Subtask.title.icontains(search, autoescape=True)
        stmt, count_stmt = stmt.where(matches), count_stmt.where(matches)
    total = db.scalar(count_stmt)
    rows = db.execute(stmt.order_by(m.Subtask.created_at, m.Subtask.id).offset((page - 1) * size).limit(size)).all()
    if not rows:
        return [], total
    ids = [row[0].id for row in rows]
    amounts = defaultdict(lambda: defaultdict(int))
    if ids:
        for child_id, component, delta in db.execute(select(XpLedger.subtask_id, XpLedger.component_type, func.sum(XpLedger.points)).where(
            *ledger_scope(tenant, task.id), XpLedger.subtask_id.in_(ids),
        ).group_by(XpLedger.subtask_id, XpLedger.component_type)):
            amounts[child_id][component] = delta
    current = rows[0]
    rule = rewards._snapshot_points(db, team=current.current_team, priority=current.current_priority, data=current.reward_policy_data) if any(row.ordinal for row in rows) else {"base": 0}
    work, (_, elapsed_children) = productive(db, task, tenant), elapsed(db, task, tenant, now, child_ids=ids)
    assignee = person(task.assignee, tenant)
    result = []
    for row in rows:
        child, ordinal = row[0], row.ordinal
        base = rule["base"] if ordinal and ordinal > 1 else 0
        result.append({"kind": "subtask", "id": child.id, "name": child.title, "assignee": assignee,
                       "effective_priority": child.priority_override or row.current_priority.value,
                       "priority_inherited": child.priority_override is None,
                       "planned_start_date": child.planned_start_date, "planned_end_date": child.planned_end_date,
                       "actual_start_at": child.actual_start_at, "actual_end_at": child.actual_end_at,
                       "status": child.status, "completed": child.completed, "deleted_at": child.deleted_at,
                       "created_at": child.created_at, "policy_version": child.point_policy_version,
                       "additional_base_value": base, "available_base": base if not child.completed else 0,
                       "earned": sum(amounts[child.id].values()) if child.point_policy_version == rewards.POLICY or amounts[child.id] else None,
                       "components": dict(amounts[child.id]),
                       "productive_seconds": work.get(child.id, 0), "elapsed_seconds": elapsed_children.get(child.id, 0)})
    return result, total


def read(db, *, task_id, who, section, page=1, size=25, search="", child_id=None):
    task, who = parent(db, task_id, who)
    if child_id and not db.scalar(select(m.Subtask.id).where(m.Subtask.id == child_id, m.Subtask.task_id == task.id)):
        raise HTTPException(404, "Subtask not found")
    now = datetime.now(UTC)
    result = {"viewer_id": who.id, "task_id": task.id, "section": section, "as_of": now, "page": page,
              "page_size": size, "created_at": utc(task.created_at), "coverage": COVERAGE}
    if section == "overview":
        work = productive(db, task, who.tenant_id)
        total_elapsed, _ = elapsed(db, task, who.tenant_id, now, child_ids=())
        assignee = person(task.assignee, who.tenant_id)
        result["overview"] = {
            "id": task.id, "name": task.title, "description": task.description, "team": task.team,
            "project": None, "creator": person(task.creator, who.tenant_id), "assignees": [assignee] if assignee else [],
            "priority": task.priority.value, "status": task.status.value, "created_at": utc(task.created_at),
            "updated_at": utc(task.updated_at), "assigned_at": utc(task.assigned_at),
            "estimated_hours": task.estimated_hours, "productive_seconds": sum(work.values()),
            "elapsed_seconds": total_elapsed, "due_at": utc(task.due_at), "completed_at": utc(task.completed_at),
            "approval_required": task.approval_required, "approval_status": task.approval_status.value,
            "limitations": ["Parent tasks have no project, planned-date or manual actual-time fields in this schema.",
                            "Shared assignments are separate parent records; this view covers this task ID only.",
                            "Elapsed and productive durations sum contributor time, not wall-clock task age."]}
    elif section == "points":
        result["points"] = point_summary(db, task, who.tenant_id)
    elif section == "subtasks":
        result["items"], result["total"] = children(db, task, who.tenant_id, page=page, size=size, search=search, now=now)
    else:
        result["items"], result["total"] = events(db, who, task, page=page, size=size, timeline=section == "timeline", child_id=child_id)
    return result
