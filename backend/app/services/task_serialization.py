"""Task response contracts with actor-aware nested task visibility."""

from .. import models, schemas
from . import subtask_rewards
from .task_access import can_read_task


def serialize_task(task: models.Task, status_title_map: dict[str, str], *,
                   current_user: models.User, include_rewards=True) -> schemas.TaskRead:
    payload = schemas.TaskRead.model_validate(task)
    tenant_id = task.creator.tenant_id
    same_assignee = task.assignee is not None and task.assignee.tenant_id == tenant_id
    status_key = getattr(task.status, "value", task.status)
    return payload.model_copy(update={
        "subtask_rewards": subtask_rewards.summary(task) if include_rewards else None,
        "status_title": status_title_map.get(status_key, status_key),
        "assignee": payload.assignee if same_assignee else None,
        "assigned_to_id": task.assigned_to_id if same_assignee else None,
        "dependencies": [schemas.TaskSummary.model_validate(dependency)
                         for dependency in task.dependencies
                         if can_read_task(dependency, current_user)],
        "follower_ids": [follower.id for follower in task.followers
                         if follower.tenant_id == tenant_id],
    })


def serialize_tasks(tasks: list[models.Task], status_title_map: dict[str, str], *,
                    current_user: models.User) -> list[schemas.TaskRead]:
    rewards = subtask_rewards.summary_map(tasks)
    return [serialize_task(task, status_title_map, current_user=current_user,
                           include_rewards=False).model_copy(
                               update={"subtask_rewards": rewards.get(task.id)})
            for task in tasks]
