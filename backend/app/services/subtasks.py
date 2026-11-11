"""Subtask writes for the existing task routes; caller owns the transaction.

No timer or status action writes actual time. Rewards still use parent priority.
"""

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update

from .. import models, schemas
from . import audit_logger as audit
from . import subtask_rewards as rewards

TRANSITIONS = {
    "TODO": {"IN_PROGRESS"},
    "IN_PROGRESS": {"PAUSED", "TESTING", "COMPLETED"},
    "PAUSED": {"IN_PROGRESS"},
    "TESTING": {"IN_PROGRESS", "COMPLETED"},
    "COMPLETED": {"TODO"},
}
ACTION_TARGETS = {
    "START": (("TODO", "TESTING"), "IN_PROGRESS"),
    "PAUSE": ("IN_PROGRESS", "PAUSED"),
    "RESUME": ("PAUSED", "IN_PROGRESS"),
    "SEND_TO_TESTING": ("IN_PROGRESS", "TESTING"),
    "COMPLETE": (("IN_PROGRESS", "TESTING"), "COMPLETED"),
    "REOPEN": ("COMPLETED", "TODO"),
}
EDITABLE = (
    "title",
    "planned_start_date",
    "planned_end_date",
    "actual_start_at",
    "actual_end_at",
    "priority_override",
)


def validated(schema, values):
    try:
        return schema.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(
            422, exc.errors(include_context=False, include_input=False)
        ) from exc


def snapshot(values):
    return {
        key: value.isoformat()
        if hasattr(value, "isoformat")
        else value.value
        if hasattr(value, "value")
        else value
        for key, value in values.items()
    }


def create(db, *, actor_id, task_id, data):
    data = (
        data
        if isinstance(data, schemas.SubtaskCreate)
        else validated(schemas.SubtaskCreate, data)
    )
    actor, task, _ = audit._activity_context(db, actor_id, task_id)
    rewards.lock_scope(db, task_id, tenant_id=actor.tenant_id)
    actor, task, _ = audit._activity_context(db, actor_id, task_id)
    now = models.utc_now()
    setting = db.scalar(
        select(models.TaskWorkflowSettings).where(
            models.TaskWorkflowSettings.tenant_id == actor.tenant_id,
            models.TaskWorkflowSettings.enabled.is_(True),
        )
    )
    policy = (
        setting.point_policy_version
        if setting and setting.activated_at and setting.activated_at <= now
        else "legacy"
    )
    with audit._write_savepoint(db):
        row = models.Subtask(
            task=task,
            title=data.title.strip(),
            completed=False,
            planned_start_date=data.planned_start_date,
            planned_end_date=data.planned_end_date,
            priority_override=data.priority_override,
            workflow_version=2,
            workflow_status="TODO",
            point_policy_version=policy,
            created_at=now,
            reward_timezone=rewards.timezone_name(actor.timezone) if policy == rewards.POLICY else None,
        )
        db.add(row)
        db.flush()
        audit.record_task_activity(
            db,
            actor_id=actor.id,
            task_id=task_id,
            subtask_id=row.id,
            data={
                "event_type": "subtask.created",
                "after": snapshot(
                    {
                        **{key: getattr(row, key) for key in EDITABLE},
                        "status": row.status,
                        "point_policy_version": policy,
                        "workflow_version": 2,
                        "assigned_to_id": task.assigned_to_id,
                    }
                ),
            },
        )
        rewards.reconcile(db, actor_id=actor_id, task_id=task_id)
    return row


def edit(db, *, actor_id, task_id, subtask_id, data):
    data = (
        data
        if isinstance(data, schemas.SubtaskUpdate)
        else validated(schemas.SubtaskUpdate, data)
    )
    actor, _, row = audit._activity_context(db, actor_id, task_id, subtask_id)
    rewards.lock_scope(db, task_id, tenant_id=actor.tenant_id)
    actor, task, row = audit._activity_context(db, actor_id, task_id, subtask_id)
    db.refresh(row)
    previous_status = row.status
    if row.deleted_at and data.deleted is not False:
        raise HTTPException(409, "Restore the subtask before editing it")
    if (row.managed or data.manage) and data.expected_version is None:
        raise HTTPException(422, "expected_version is required for managed subtasks")
    expected = (
        data.expected_version if data.expected_version is not None else row.version
    )
    if row.version != expected:
        raise HTTPException(409, "Subtask changed; reload before saving")
    fields = data.model_dump(exclude_unset=True, include=set(EDITABLE))
    if "title" in fields:
        fields["title"] = fields["title"].strip()
    if data.deleted is not None:
        fields["deleted_at"] = (row.deleted_at or models.utc_now()) if data.deleted else None
    candidate = {name: fields.get(name, getattr(row, name)) for name in EDITABLE}
    validated(
        schemas.SubtaskScheduleUpdate,
        {
            "expected_version": expected,
            **{key: value for key, value in candidate.items() if key != "title"},
        },
    )
    managed = row.managed or data.manage
    target = row.status
    if data.action:
        origins, target = ACTION_TARGETS[data.action]
        origins = (origins,) if isinstance(origins, str) else origins
        if row.status not in origins:
            raise HTTPException(
                409, "This action is not available from the current subtask status"
            )
    elif data.status is not None:
        target = data.status.value
    elif data.completed is not None:
        target = "COMPLETED" if data.completed else "TODO"
    if managed:
        if not candidate["planned_start_date"] or not candidate["planned_end_date"]:
            raise HTTPException(
                422, "Managed subtasks require planned start and end dates"
            )
        if target != row.status and target not in TRANSITIONS[row.status]:
            raise HTTPException(409, "Illegal subtask status transition")
        if target == "COMPLETED" and (
            not candidate["actual_start_at"] or not candidate["actual_end_at"]
        ):
            raise HTTPException(
                422, "Manually enter and confirm actual start and end before completing"
            )
        fields.update(
            workflow_version=2, workflow_status=target, completed=target == "COMPLETED"
        )
    elif target not in {"TODO", "COMPLETED"}:
        raise HTTPException(
            422, "Enter planned dates and enable the managed workflow first"
        )
    elif data.completed is not None or data.status is not None or data.action:
        fields["completed"] = target == "COMPLETED"
    changed = {
        key: value for key, value in fields.items() if getattr(row, key) != value
    }
    if not changed:
        return row
    before = {key: getattr(row, key) for key in changed}
    with audit._write_savepoint(db):
        result = db.execute(
            update(models.Subtask)
            .where(models.Subtask.id == row.id, models.Subtask.version == expected)
            .values(**changed, version=models.Subtask.version + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Subtask changed; reload before saving")
        audit.record_task_activity(
            db,
            actor_id=actor.id,
            task_id=task_id,
            subtask_id=row.id,
            data={
                "event_type": "subtask.status_changed"
                if "completed" in changed or "workflow_status" in changed
                else "subtask.updated",
                "before": snapshot(before),
                "after": snapshot(changed),
                "metadata": {
                    "actual_times_confirmed": data.confirm_actual_times,
                    "action": data.action,
                    "reward_priority_source": "parent_task",
                },
            },
        )
        db.refresh(row)
        from . import task_activity
        task_activity.sync_subtask(db, who=actor, task=task, child=row, previous_status=previous_status)
        rewards.reconcile(db, actor_id=actor_id, task_id=task_id)
    return row
