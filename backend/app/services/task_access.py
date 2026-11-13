"""Canonical task object policy, shared by task and ticket expansions."""

from fastapi import HTTPException, status
from sqlalchemy import or_, select

from .. import models


def ensure_task_tenant(task: models.Task, user: models.User) -> None:
    if not task.creator or task.creator.tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


def ensure_task_access(task: models.Task, user: models.User) -> None:
    ensure_task_tenant(task, user)
    if user.role in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}:
        return
    if user.role == models.RoleEnum.MANAGER:
        if task.created_by_id == user.id or task.assigned_to_id == user.id:
            return
        if any(follower.id == user.id for follower in task.followers):
            return
        if user.department_id:
            assignee_department_id = task.assignee.department_id if task.assignee else None
            if assignee_department_id == user.department_id:
                return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this task")
    if (
        task.created_by_id != user.id
        and task.assigned_to_id != user.id
        and not any(follower.id == user.id for follower in task.followers)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this task")


def ensure_task_update_access(task: models.Task, user: models.User) -> None:
    ensure_task_tenant(task, user)
    if task.ticket_id:
        if task.created_by_id != user.id and task.assigned_to_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the task creator or assignee can update this ticket task",
            )
        return
    if task.created_by_id == user.id or task.assigned_to_id == user.id:
        return
    if user.role in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}:
        return
    if (
        user.role == models.RoleEnum.MANAGER
        and user.department_id
        and task.assignee
        and task.assignee.tenant_id == user.tenant_id
        and task.assignee.department_id == user.department_id
    ):
        return
    raise HTTPException(status_code=403, detail="Insufficient permissions to modify this task")


def ensure_task_delete_access(task: models.Task, user: models.User) -> None:
    """Deletion requires the existing editor policy, never follower visibility."""
    ensure_task_update_access(task, user)


def apply_task_visibility(stmt: select, current_user: models.User) -> select:
    stmt = stmt.where(models.Task.creator.has(models.User.tenant_id == current_user.tenant_id))
    if current_user.role == models.RoleEnum.MANAGER:
        visibility_filters = [
            models.Task.created_by_id == current_user.id,
            models.Task.assigned_to_id == current_user.id,
            models.Task.followers.any(models.User.id == current_user.id),
        ]
        if current_user.department_id:
            visibility_filters.append(
                models.Task.assignee.has(models.User.department_id == current_user.department_id)
            )
        return stmt.where(or_(*visibility_filters))
    if current_user.role not in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}:
        return stmt.where(
            or_(
                models.Task.created_by_id == current_user.id,
                models.Task.assigned_to_id == current_user.id,
                models.Task.followers.any(models.User.id == current_user.id),
            )
        )
    return stmt


def can_read_task(task: models.Task, user: models.User) -> bool:
    try:
        ensure_task_access(task, user)
    except HTTPException as exc:
        if exc.status_code not in (403, 404):
            raise
        return False
    return True
