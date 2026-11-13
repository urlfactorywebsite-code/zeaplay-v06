"""Ticket/task engine service for ticket-linked global tasks."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models
from ..services import notifications as notification_service
from ..services.task_access import apply_task_visibility
from ..services.tenant_users import require_tenant_users
from .models import TicketTaskLink
from .service import get_ticket_for_user


def _now() -> datetime:
    return datetime.utcnow()


def _ensure_ticket_assignee(ticket, user_id: str) -> None:
    if not ticket.assigned_user_id or str(ticket.assigned_user_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned user can create ticket tasks",
        )


def list_ticket_tasks(
    db: Session,
    *,
    tenant_id,
    ticket_id,
    current_user: models.User,
) -> list[models.Task]:
    ticket = get_ticket_for_user(
        db, tenant_id=tenant_id, ticket_id=ticket_id,
        current_user=current_user, roles=[current_user.role.value],
    )
    return (
        db.execute(
            apply_task_visibility(select(models.Task), current_user)
            .where(models.Task.ticket_id == ticket.id)
            .options(selectinload(models.Task.creator), selectinload(models.Task.assignee),
                     selectinload(models.Task.followers), selectinload(models.Task.subtasks),
                     selectinload(models.Task.dependencies).selectinload(models.Task.creator),
                     selectinload(models.Task.dependencies).selectinload(models.Task.assignee),
                     selectinload(models.Task.dependencies).selectinload(models.Task.followers))
            .order_by(models.Task.created_at.asc())
        )
        .scalars()
        .all()
    )


def create_ticket_task(
    db: Session,
    *,
    tenant_id,
    ticket_id,
    current_user: models.User,
    payload,
) -> models.Task:
    ticket = get_ticket_for_user(db, tenant_id=tenant_id, ticket_id=ticket_id,
        current_user=current_user, roles=[current_user.role.value])
    user_id = str(current_user.id)
    _ensure_ticket_assignee(ticket, user_id)

    approver_id = payload.approver_id
    if payload.approval_required and not approver_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approver required when approval is enabled",
        )
    require_tenant_users(db, tenant_id, [approver_id, ticket.assigned_user_id, user_id])

    task = models.Task(
        title=ticket.title,
        description=ticket.description,
        status=models.TaskStatusEnum.TODO,
        priority=payload.priority,
        team="General",
        assigned_to_id=ticket.assigned_user_id or user_id,
        created_by_id=user_id,
        due_at=payload.due_at,
        approval_required=payload.approval_required,
        approval_status=models.TaskApprovalStatusEnum.NONE,
        approver_id=approver_id,
        ticket_id=ticket.id,
    )
    db.add(task)
    db.flush()

    db.add(
        TicketTaskLink(
            tenant_id=tenant_id,
            ticket_id=ticket.id,
            task_id=str(task.id),
            created_at=_now(),
        )
    )

    db.add(
        models.AuditEvent(
            actor_id=user_id,
            event_type="task.created",
            entity_type="task",
            entity_id=str(task.id),
            payload={
                "ticket_id": str(ticket.id),
                "approval_required": payload.approval_required,
                "approver_id": approver_id,
            },
            created_at=_now(),
        )
    )

    recipient_id = (
        approver_id if payload.approval_required and approver_id else ticket.owner_id or ticket.created_by or user_id
    )
    if recipient_id:
        notification_service.create_notification(
            db,
            user_id=str(recipient_id),
            notification_type=(
                models.NotificationTypeEnum.APPROVAL_REQUESTED
                if payload.approval_required
                else models.NotificationTypeEnum.TASK_ASSIGNED
            ),
            message=f"Task created for ticket '{ticket.title}'.",
            title="Ticket task created",
            body=f"Task '{task.title}' was created under ticket '{ticket.title}'.",
            entity_type=models.NotificationEntityTypeEnum.TASK,
            entity_id=str(task.id),
            related_task_id=str(task.id),
        )

    db.commit()
    db.refresh(task)
    return task
