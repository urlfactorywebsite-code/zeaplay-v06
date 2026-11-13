from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_active_user, get_current_user, get_tenant_id, require_roles
from ..models import User
from ..schemas import ApprovalActionPayload, ApprovalRead, TaskRead
from ..services.task_serialization import serialize_tasks
from .schemas import (
    PendingApprovalItemRead,
    TicketApprovalActionPayload,
    TicketApprovalCycleRead,
    TicketApprovalRequestPayload,
    TicketAuditLogPage,
    TicketStatusUpdate,
    TicketLinkedTaskCreate,
    TicketTaskRead,
    TicketTaskUpdate,
)
from .workflow_service import (
    approve_ticket_cycle,
    complete_ticket_task,
    list_pending_approvals,
    list_ticket_logs,
    reject_ticket_cycle,
    request_ticket_approval,
    update_ticket_status,
    update_ticket_task,
)
from .task_engine_service import (
    create_ticket_task as create_ticket_linked_task,
    list_ticket_tasks as list_ticket_linked_tasks,
)
from .approvals_service import act_on_ticket_approval, request_ticket_approvals_sequential
from .models import TicketApprovalTypeEnum


router = APIRouter(prefix="/api", tags=["tickets"])
# Only the repaired reads get canonical aliases for the prefix-stripping proxy.
read_router = APIRouter(tags=["tickets"])


@router.post("/tickets/{ticket_id}/status", response_model=dict, status_code=status.HTTP_200_OK)
def update_ticket_status_handler(
    ticket_id: uuid.UUID,
    payload: TicketStatusUpdate,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    roles: list[str] = Depends(require_roles()),
) -> dict:
    ticket = update_ticket_status(
        db,
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        current_user=current_user,
        roles=roles,
        next_status=payload.status,
    )
    return {"ticket_id": str(ticket.id), "status": ticket.status.value}


@router.post("/tickets/{ticket_id}/approvals/request", response_model=TicketApprovalCycleRead)
def request_ticket_approval_handler(
    ticket_id: uuid.UUID,
    payload: TicketApprovalRequestPayload,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    roles: list[str] = Depends(require_roles()),
) -> TicketApprovalCycleRead:
    request_ticket_approvals_sequential(
        db,
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        current_user=current_user,
        roles=roles,
        approvers=[(item.approver_user_id, item.message) for item in payload.approvers],
    )
    return request_ticket_approval(
        db,
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        current_user=current_user,
        roles=roles,
        approval_type=TicketApprovalTypeEnum.SEQUENTIAL,
        approvers=[(item.approver_user_id, item.message) for item in payload.approvers],
        deadline_utc=payload.deadline_utc,
        notify_approvers=False,
    )


@router.post("/approvals/{approval_id}/act", response_model=ApprovalRead)
def act_on_approval_handler(
    approval_id: str,
    payload: ApprovalActionPayload,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    roles: list[str] = Depends(require_roles()),
) -> ApprovalRead:
    approval = act_on_ticket_approval(
        db,
        tenant_id=tenant_id,
        approval_id=approval_id,
        current_user=current_user,
        roles=roles,
        decision=payload.decision,
        comment=payload.comment,
    )
    db.commit()
    db.refresh(approval)
    return ApprovalRead(
        id=str(approval.id),
        scope_type=approval.scope_type,
        scope_id=str(approval.scope_id),
        status=approval.status,
        order_index=approval.order_index,
        requested_by=str(approval.requested_by),
        approver_id=str(approval.approver_id) if approval.approver_id else None,
        comment=approval.comment,
        sla_hours=approval.sla_hours,
        created_at=approval.created_at,
        acted_at=approval.acted_at,
    )


@router.post("/approvals/{cycle_id}/approve", response_model=TicketApprovalCycleRead)
def approve_ticket_handler(
    cycle_id: uuid.UUID,
    payload: TicketApprovalActionPayload,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    roles: list[str] = Depends(require_roles()),
) -> TicketApprovalCycleRead:
    return approve_ticket_cycle(
        db,
        tenant_id=tenant_id,
        cycle_id=cycle_id,
        current_user=current_user,
        roles=roles,
        message=payload.message,
    )


@router.post("/approvals/{cycle_id}/reject", response_model=TicketApprovalCycleRead)
def reject_ticket_handler(
    cycle_id: uuid.UUID,
    payload: TicketApprovalActionPayload,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    roles: list[str] = Depends(require_roles()),
) -> TicketApprovalCycleRead:
    return reject_ticket_cycle(
        db,
        tenant_id=tenant_id,
        cycle_id=cycle_id,
        current_user=current_user,
        roles=roles,
        message=payload.message,
    )


@router.get("/approvals/pending", response_model=list[PendingApprovalItemRead])
def list_pending_approvals_handler(
    include_all: bool = Query(default=False, alias="includeAll"),
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    roles: list[str] = Depends(require_roles()),
) -> list[PendingApprovalItemRead]:
    return list_pending_approvals(
        db,
        tenant_id=tenant_id,
        current_user=current_user,
        roles=roles,
        include_all=include_all,
    )


@router.get("/tickets/{ticket_id}/tasks", response_model=list[TaskRead])
@read_router.get("/tickets/{ticket_id}/tasks", response_model=list[TaskRead])
def list_ticket_tasks_handler(
    ticket_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_active_user),
) -> list[TaskRead]:
    tasks = list_ticket_linked_tasks(
        db, tenant_id=tenant_id, ticket_id=ticket_id, current_user=current_user,
    )
    return serialize_tasks(tasks, {}, current_user=current_user)


@router.post("/tickets/{ticket_id}/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_ticket_task_handler(
    ticket_id: uuid.UUID,
    payload: TicketLinkedTaskCreate,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    roles: list[str] = Depends(require_roles()),
) -> TaskRead:
    return create_ticket_linked_task(
        db,
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        current_user=current_user,
        payload=payload,
    )


# Standalone compatibility apps retain these legacy handlers. The combined
# application's router below excludes them in favor of the canonical task API.
@router.patch("/tasks/{task_id}", response_model=TicketTaskRead, include_in_schema=False)
def update_ticket_task_handler(
    task_id: uuid.UUID,
    payload: TicketTaskUpdate,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    roles: list[str] = Depends(require_roles()),
) -> TicketTaskRead:
    return update_ticket_task(
        db,
        tenant_id=tenant_id,
        task_id=task_id,
        current_user=current_user,
        roles=roles,
        payload=payload,
    )


@router.post("/tasks/{task_id}/complete", response_model=TicketTaskRead, include_in_schema=False)
def complete_ticket_task_handler(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    roles: list[str] = Depends(require_roles()),
) -> TicketTaskRead:
    return complete_ticket_task(
        db,
        tenant_id=tenant_id,
        task_id=task_id,
        current_user=current_user,
        roles=roles,
    )


@router.get("/tickets/{ticket_id}/logs", response_model=TicketAuditLogPage)
@read_router.get("/tickets/{ticket_id}/logs", response_model=TicketAuditLogPage)
def list_ticket_logs_handler(
    ticket_id: uuid.UUID,
    page: int = 1,
    page_size: int = 25,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_active_user),
) -> TicketAuditLogPage:
    return list_ticket_logs(
        db,
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        current_user=current_user,
        page=page,
        page_size=page_size,
    )


# The full router remains available to standalone compatibility callers. In
# main.py these two paths are already owned by routers.tasks; registering them
# again would create shadowed dispatch entries with a different payload model.
application_router = APIRouter()
application_router.include_router(router)
application_router.routes[:] = [
    route for route in application_router.routes
    if route.endpoint not in {update_ticket_task_handler, complete_ticket_task_handler}
]
