"""Tenant-scoped additional rewards; immutable XP ledger is the source of truth.

Caller owns commit. Every writer locks policy then the parent group before
reading reward state; never rebuild the existing wallet from historical tasks.
"""

import hashlib
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import and_, case, func, inspect, or_, select
from sqlalchemy.orm import object_session

from .. import models
from ..tickets.models import XpLedger
from . import audit_logger as audit
from .gamification import completion_point_components
from .points_table import _normalize_points_config, resolve_task_points
from .wallet import adjust as adjust_wallet

POLICY = "subtask-additional-v1"


def tenant_lock(db, tenant_id, *, shared=False):
    connection = db.connection()
    if connection.dialect.name == "postgresql":
        # Frozen audit guards take user FOR SHARE locks. Serializing task
        # writers within a tenant before those guards prevents SHARE->UPDATE
        # wallet deadlocks across otherwise unrelated parent tasks.
        key = int.from_bytes(
            hashlib.sha256(f"{POLICY}:{tenant_id}".encode()).digest()[:8],
            "big",
            signed=True,
        )
        function = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
        connection.exec_driver_sql(f"SELECT {function}(%s)", (key,))


def policy(db, tenant_id, *, exclusive=False):
    return db.scalar(
        select(models.TaskWorkflowSettings)
        .where(
            models.TaskWorkflowSettings.tenant_id == tenant_id,
            models.TaskWorkflowSettings.point_policy_version == POLICY,
        )
        .with_for_update(read=not exclusive)
        .execution_options(populate_existing=True)
    )


def lock_scope(db, task_id, *, tenant_id=None):
    # SQLite is a single-writer fallback; PostgreSQL uses row-level locks.
    connection = db.connection()
    if (
        connection.dialect.name == "sqlite"
        and not connection.connection.driver_connection.in_transaction
    ):
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    with db.no_autoflush:
        owner = db.execute(
            select(models.User.tenant_id, models.Task.task_group_id)
            .join(models.Task, models.Task.created_by_id == models.User.id)
            .where(models.Task.id == task_id)
        ).first()
        if not owner:
            raise HTTPException(404, "Task not found")
        if tenant_id is not None and owner.tenant_id != tenant_id:
            raise HTTPException(404, "Task not found")
        tenant_lock(db, owner.tenant_id)
        policy(db, owner.tenant_id)
        group = (
            models.Task.task_group_id == owner.task_group_id
            if owner.task_group_id
            else models.Task.id == task_id
        )
        ids = list(
            db.scalars(
                select(models.Task.id)
                .where(
                    or_(group, models.Task.id == task_id),
                    models.Task.creator.has(models.User.tenant_id == owner.tenant_id),
                )
                .order_by(models.Task.id)
                .with_for_update()
            )
        )
        for key in ids:
            task = db.get(models.Task, key)
            if not db.is_modified(task, include_collections=False):
                db.refresh(
                    task, ["priority", "team", "assigned_to_id", "created_by_id"]
                )
                db.expire(task, ["assignee"])
            if not inspect(task).attrs.subtasks.history.has_changes():
                db.expire(task, ["subtasks"])
    return ids


def rules_snapshot(db):
    # No commit-capable config getter inside a financial transaction.
    row = db.get(models.PointsTableConfig, 1)
    return _normalize_points_config(row.points_config if row else None)


def timezone_name(value):
    try:
        ZoneInfo(value or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise HTTPException(
            422, "Configure a valid IANA timezone before creating reward subtasks"
        ) from exc
    return value or "UTC"


def _snapshot_points(db, *, team, priority, data):
    if (
        not isinstance(data, dict)
        or data.get("algorithm") != POLICY
        or not isinstance(data.get("config"), dict)
        or type(data.get("bonus_enabled")) is not bool
        or type(data.get("penalty_enabled")) is not bool
    ):
        raise HTTPException(409, "Additional subtask reward policy is not configured")
    points = resolve_task_points(
        db, team=team, priority=priority, config_override=data["config"]
    )
    _validate_points(points)
    return points


def calculation(db, task, children, setting):
    data = setting.reward_policy_data if setting else None
    points = _snapshot_points(db, team=task.team, priority=task.priority, data=data)
    return calculate(
        task, children, points=points, policy_data=data, rule_revision=setting.version
    )


def _validate_points(points):
    if (
        points["base"] < 0
        or points["beforeDueBonus"] < 0
        or points["overduePenalty"] > 0
    ):
        raise HTTPException(
            422,
            "Additional subtask rewards require nonnegative base/bonus and a nonpositive penalty",
        )


def calculate(task, children, *, points, policy_data, rule_revision):
    """Pure entitlement calculation: no database, clocks, writes or wallet reads."""
    data = policy_data
    children = sorted(
        (child for child in children if child.point_policy_version == POLICY),
        key=lambda child: (child.created_at, child.id),
    )
    _validate_points(points)
    eligible = [child for child in children if child.deleted_at is None]
    ordinal = {child.id: index for index, child in enumerate(eligible, 1)}
    desired = {}
    inputs = {}
    for child in children:
        position = ordinal.get(child.id)
        due = None
        if child.planned_end_date:
            # Date deadlines include their entire local day, including DST days.
            try:
                due = datetime.combine(
                    child.planned_end_date + timedelta(days=1),
                    time.min,
                    ZoneInfo(child.reward_timezone),
                ).astimezone(timezone.utc) - timedelta(microseconds=1)
            except (OverflowError, ZoneInfoNotFoundError, ValueError, TypeError) as exc:
                raise HTTPException(
                    422,
                    "Subtask deadline or timezone is outside the supported UTC range",
                ) from exc
        detail = {
            "algorithm": POLICY,
            "rule_revision": rule_revision,
            "priority": task.priority.value,
            "team": task.team,
            "points": points,
            "ordinal": position,
            "eligible_count": len(eligible),
            "created_at": child.created_at.isoformat(),
            "subtask_id": child.id,
            "assignee_id": task.assigned_to_id,
            "timezone": child.reward_timezone,
            "deadline": due.isoformat() if due else None,
            "actual_end_at": child.actual_end_at.isoformat()
            if child.actual_end_at
            else None,
            "bonus_enabled": data["bonus_enabled"],
            "penalty_enabled": data["penalty_enabled"],
        }
        inputs[child.id] = detail
        if (
            not position
            or position == 1
            or not points["base"]
            or not child.completed
            or not task.assigned_to_id
        ):
            continue
        values = completion_point_components(points, child.actual_end_at, due)
        if not data["bonus_enabled"]:
            values["BONUS"] = 0
        if not data["penalty_enabled"]:
            values["PENALTY"] = 0
        for component, value in values.items():
            if value:
                desired[(child.id, task.assigned_to_id, component)] = value
    return desired, inputs, ordinal, points


def reconcile(db, **kwargs):
    """Abort the caller's financial transaction on any failed reconciliation.

    Savepoints alone cannot undo parent changes flushed before reconciliation.
    A caller catching an error must never subsequently commit half a payout.
    """
    try:
        return _reconcile(db, **kwargs)
    except Exception:
        db.rollback()
        raise


def _reconcile(
    db,
    *,
    actor_id,
    task_id,
    reason="Subtask reward inputs changed",
    authorized_parent_write=False,
):
    """Reconcile only this policy; all ledger entries and wallet deltas are atomic."""
    if authorized_parent_write:
        # Only internal parent writers use this after canonical pre-change RBAC.
        # A reassignment may remove the initiating assignee's access mid-write.
        actor, task = db.get(models.User, actor_id), db.get(models.Task, task_id)
        if (
            not actor
            or actor.status != models.UserStatusEnum.ACTIVE
            or not task
            or not task.creator
            or task.creator.tenant_id != actor.tenant_id
        ):
            raise HTTPException(404, "Task not found")
    else:
        actor, task, _ = audit._activity_context(db, actor_id, task_id)
    lock_scope(db, task_id, tenant_id=actor.tenant_id)
    if not authorized_parent_write:
        actor, task, _ = audit._activity_context(db, actor_id, task_id)
    db.flush()
    children = list(
        db.scalars(
            select(models.Subtask)
            .where(
                models.Subtask.task_id == task_id,
                models.Subtask.point_policy_version == POLICY,
            )
            .execution_options(populate_existing=True)
        )
    )
    if not children:
        return
    setting = policy(db, actor.tenant_id)
    desired, inputs, _, _ = calculation(db, task, children, setting)
    recipient = (
        db.get(models.User, task.assigned_to_id) if task.assigned_to_id else None
    )
    if task.assigned_to_id and (
        not recipient or recipient.tenant_id != actor.tenant_id
    ):
        raise HTTPException(404, "Reward assignee not found in this tenant")
    rows = list(
        db.scalars(
            select(XpLedger).where(
                XpLedger.tenant_id == actor.tenant_id,
                XpLedger.task_id == task_id,
                XpLedger.record_version == 2,
                or_(XpLedger.ref_type == POLICY, XpLedger.policy_version == POLICY),
            )
        )
    )
    originals = {row.id: row for row in rows if row.reversal_of_id is None}
    reversed_ids = set()
    # Refuse malformed historical/imported accounting rather than guessing a
    # compensating payout. No repair rewrites or retroactive wallet rebuilding.
    for row in rows:
        if (
            row.ref_type != POLICY
            or row.policy_version != POLICY
            or row.subtask_id not in inputs
            or row.ref_id != row.subtask_id
        ):
            raise HTTPException(
                409, "Inconsistent reward ledger; accounting review required"
            )
        if row.reversal_of_id:
            original = originals.get(row.reversal_of_id)
            if (
                not original
                or row.reversal_of_id in reversed_ids
                or row.component_type != "REVERSAL"
                or (row.subtask_id, row.user_id, row.points)
                != (original.subtask_id, original.user_id, -original.points)
            ):
                raise HTTPException(
                    409, "Inconsistent reward ledger; accounting review required"
                )
            reversed_ids.add(row.reversal_of_id)
        elif row.component_type not in {"BASE", "BONUS", "PENALTY"}:
            raise HTTPException(
                409, "Inconsistent reward ledger; accounting review required"
            )
    active = defaultdict(list)
    for row in rows:
        if row.reversal_of_id is None and row.id not in reversed_ids:
            active[(row.subtask_id, row.user_id, row.component_type)].append(row)
    changes = defaultdict(lambda: {"reverse": [], "post": []})
    for key in sorted(active.keys() | desired.keys()):
        existing = active.get(key, [])
        value = desired.get(key, 0)
        # Ordinal/count-only changes with identical entitlement need no wallet churn.
        if len(existing) == 1 and existing[0].points == value:
            continue
        changes[key[0]]["reverse"].extend(sorted(existing, key=lambda row: str(row.id)))
        if value:
            changes[key[0]]["post"].append((key, value))
    balances = defaultdict(int)
    with audit._write_savepoint(db):
        for child_id in sorted(changes):
            change = changes[child_id]
            event = models.AuditEvent(
                audit_schema_version=2,
                tenant_id=actor.tenant_id,
                actor_id=actor_id,
                task_id=task_id,
                subtask_id=child_id,
                entity_type="subtask",
                entity_id=child_id,
                event_type="subtask.rewards_reconciled",
                before={"active_entries": [str(row.id) for row in change["reverse"]]},
                after={"components": {key[2]: value for key, value in change["post"]}},
                payload={"reason": reason, "calculation": inputs[child_id]},
                created_at=models.utc_now(),
            )
            db.add(event)
            db.flush()
            entries = [
                (row.user_id, "REVERSAL", -row.points, row.id, row.calculation_inputs)
                for row in change["reverse"]
            ]
            entries += [
                (key[1], key[2], value, None, inputs[child_id])
                for key, value in change["post"]
            ]
            for index, (user_id, component, delta, reversal, detail) in enumerate(
                entries
            ):
                key = hashlib.sha256(
                    f"{POLICY}:{event.id}:{index}".encode()
                ).hexdigest()
                db.add(
                    XpLedger(
                        tenant_id=actor.tenant_id,
                        task_id=task_id,
                        subtask_id=child_id,
                        user_id=user_id,
                        record_version=2,
                        ref_type=POLICY,
                        ref_id=child_id,
                        event_type=event.event_type,
                        component_type=component,
                        points=delta,
                        policy_version=POLICY,
                        idempotency_key=key,
                        activity_event_id=event.id,
                        reason=reason,
                        reversal_of_id=reversal,
                        calculation_inputs=detail,
                        created_at=models.utc_now(),
                    )
                )
                balances[user_id] += delta
        db.flush()
        # Stable lock order and SQL arithmetic prevent concurrent parent rewards
        # for the same recipient from overwriting each other's wallet increments.
        for user_id in sorted(balances):
            user = db.get(models.User, user_id)
            if not user or user.tenant_id != actor.tenant_id:
                raise HTTPException(409, "Reward recipient changed tenant")
            adjust_wallet(db, user, balances[user_id])
        # Verify a genuinely independent projection: signed SQL ledger sums
        # must equal deterministic entitlement per child/recipient, including zeros
        # left by former recipients and every compensating entry.
        actual = {
            (child_id, user_id): amount
            for child_id, user_id, amount in db.execute(
                select(XpLedger.subtask_id, XpLedger.user_id, func.sum(XpLedger.points))
                .where(
                    XpLedger.tenant_id == actor.tenant_id,
                    XpLedger.task_id == task_id,
                    XpLedger.record_version == 2,
                    XpLedger.ref_type == POLICY,
                )
                .group_by(XpLedger.subtask_id, XpLedger.user_id)
            ).all()
        }
        expected = defaultdict(int)
        for (child_id, user_id, _), value in desired.items():
            expected[(child_id, user_id)] += value
        if any(
            actual.get(scope, 0) != expected.get(scope, 0)
            for scope in actual.keys() | expected.keys()
        ):
            raise HTTPException(
                409, "Reward balance invariant failed; transaction rolled back"
            )


def summary(task):
    return summary_map([task]).get(task.id)


def summary_map(tasks):
    """One statement snapshot: earned and available cannot double-count a payout.

    Read columns rather than cached ORM entities. Window ordinals and ledger
    grouping share the database statement snapshot, including under READ COMMITTED.
    Existing task visibility is established by callers; ownership is rechecked.
    """
    if not tasks or not (db := object_session(tasks[0])):
        return {}
    owners = {task.id: task.creator.tenant_id for task in tasks}
    eligible = (
        select(
            models.Subtask.task_id,
            models.Subtask.completed,
            func.row_number()
            .over(
                partition_by=models.Subtask.task_id,
                order_by=(models.Subtask.created_at, models.Subtask.id),
            )
            .label("ordinal"),
        )
        .where(
            models.Subtask.task_id.in_(owners),
            models.Subtask.point_policy_version == POLICY,
            models.Subtask.deleted_at.is_(None),
        )
        .subquery()
    )
    counts = (
        select(
            eligible.c.task_id,
            func.count().label("eligible_count"),
            func.sum(
                case(
                    (and_(eligible.c.ordinal > 1, eligible.c.completed.is_(False)), 1),
                    else_=0,
                )
            ).label("available_count"),
        )
        .group_by(eligible.c.task_id)
        .subquery()
    )
    earnings = (
        select(
            XpLedger.task_id,
            XpLedger.tenant_id,
            XpLedger.user_id,
            func.sum(XpLedger.points).label("earned"),
        )
        .where(
            XpLedger.task_id.in_(owners),
            XpLedger.tenant_id.in_(set(owners.values())),
            XpLedger.record_version == 2,
            XpLedger.ref_type == POLICY,
        )
        .group_by(XpLedger.task_id, XpLedger.tenant_id, XpLedger.user_id)
        .subquery()
    )
    stmt = (
        select(
            models.Task.id,
            models.User.tenant_id,
            models.Task.team,
            models.Task.priority,
            models.Task.assigned_to_id,
            models.TaskWorkflowSettings.reward_policy_data,
            counts.c.eligible_count,
            counts.c.available_count,
            earnings.c.user_id,
            earnings.c.earned,
        )
        .select_from(models.Task)
        .join(models.User, models.User.id == models.Task.created_by_id)
        .outerjoin(
            models.TaskWorkflowSettings,
            and_(
                models.TaskWorkflowSettings.tenant_id == models.User.tenant_id,
                models.TaskWorkflowSettings.point_policy_version == POLICY,
            ),
        )
        .outerjoin(counts, counts.c.task_id == models.Task.id)
        .outerjoin(
            earnings,
            and_(
                earnings.c.task_id == models.Task.id,
                earnings.c.tenant_id == models.User.tenant_id,
            ),
        )
        .where(
            models.Task.id.in_(owners),
            models.User.tenant_id.in_(set(owners.values())),
            models.Task.subtasks.any(models.Subtask.point_policy_version == POLICY),
        )
    )
    result = {}
    for row in db.execute(stmt):
        if row.tenant_id != owners[row.id]:
            continue
        if row.id not in result:
            points = _snapshot_points(
                db, team=row.team, priority=row.priority, data=row.reward_policy_data
            )
            count = row.eligible_count or 0
            result[row.id] = {
                "eligible_count": count,
                "available_base": (row.available_count or 0) * points["base"],
                "base_capacity": max(0, count - 1) * points["base"],
                "earned": 0,
                "earned_by_recipient": {},
                "available_recipient_id": row.assigned_to_id,
                "policy_version": POLICY,
            }
        if row.user_id is not None:
            result[row.id]["earned_by_recipient"][row.user_id] = row.earned
            result[row.id]["earned"] += row.earned
    return result


def configure(
    db,
    *,
    actor,
    enabled,
    expected_version,
    bonus_enabled=None,
    penalty_enabled=None,
    refresh_rules=False,
):
    if actor.role != models.RoleEnum.OWNER:
        raise HTTPException(
            403, "Only the tenant owner can configure additional subtask rewards"
        )
    connection = db.connection()
    if connection.dialect.name == "postgresql":
        tenant_lock(db, actor.tenant_id)
    elif not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    # Revalidate after waiting for concurrent policy/reward writers. A detached
    # dependency result must not keep owner authority after demotion/deactivation.
    expected_tenant = actor.tenant_id
    actor = db.scalar(
        select(models.User)
        .where(models.User.id == actor.id)
        .execution_options(populate_existing=True)
    )
    if (
        not actor
        or actor.tenant_id != expected_tenant
        or actor.role != models.RoleEnum.OWNER
        or actor.status != models.UserStatusEnum.ACTIVE
    ):
        raise HTTPException(403, "An active tenant owner is required")
    setting = policy(db, actor.tenant_id, exclusive=True)
    if expected_version != (setting.version if setting else 0):
        raise HTTPException(409, "Reward policy changed; reload before saving")
    with audit._write_savepoint(db):
        if not setting:
            setting = models.TaskWorkflowSettings(
                tenant_id=actor.tenant_id,
                point_policy_version=POLICY,
                enabled=False,
                version=1,
            )
        if enabled:
            other = db.scalar(
                select(models.TaskWorkflowSettings).where(
                    models.TaskWorkflowSettings.tenant_id == actor.tenant_id,
                    models.TaskWorkflowSettings.enabled.is_(True),
                    models.TaskWorkflowSettings.point_policy_version != POLICY,
                )
            )
            if other:
                raise HTTPException(
                    409, "Disable the existing active reward policy first"
                )
        old = dict(setting.reward_policy_data or {})
        data = {
            "algorithm": POLICY,
            "config": rules_snapshot(db) if refresh_rules or not old else old["config"],
            "bonus_enabled": bonus_enabled
            if bonus_enabled is not None
            else old.get("bonus_enabled", True),
            "penalty_enabled": penalty_enabled
            if penalty_enabled is not None
            else old.get("penalty_enabled", True),
        }
        setting.reward_policy_data = data
        setting.enabled = enabled
        if enabled and not setting.activated_at:
            setting.activated_at = models.utc_now()
        if old:
            setting.version += 1
        db.add(setting)
        db.add(
            models.AuditEvent(
                actor_id=actor.id,
                tenant_id=actor.tenant_id,
                event_type="subtask_reward_policy.updated",
                entity_type="subtask_reward_policy",
                entity_id=str(actor.tenant_id),
                payload={
                    "version": setting.version,
                    "enabled": enabled,
                    "bonus_enabled": data["bonus_enabled"],
                    "penalty_enabled": data["penalty_enabled"],
                    "refresh_rules": refresh_rules,
                },
            )
        )
        db.flush()
        ids = list(
            db.scalars(
                select(models.Task.id)
                .where(
                    models.Task.creator.has(models.User.tenant_id == actor.tenant_id),
                    models.Task.subtasks.any(
                        models.Subtask.point_policy_version == POLICY
                    ),
                )
                .order_by(models.Task.id)
                .with_for_update()
            )
        )
        for task_id in ids:
            reconcile(
                db,
                actor_id=actor.id,
                task_id=task_id,
                reason="Tenant reward policy updated",
            )
    return {
        "enabled": setting.enabled,
        "version": setting.version,
        "policy_version": POLICY,
        "activated_at": setting.activated_at,
        "bonus_enabled": data["bonus_enabled"],
        "penalty_enabled": data["penalty_enabled"],
    }
