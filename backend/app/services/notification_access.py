"""Current resource authorization for inbox, mutation and delivery paths."""
from types import SimpleNamespace
from sqlalchemy import and_, or_, select, cast, String, literal
from .. import models as m
from ..tickets.models import Ticket
from ..tickets.access import ticket_access_predicate
from .task_access import apply_task_visibility


def resource_predicate(user, notice=m.Notification, *, tasks_allowed=True, tickets_allowed=True):
    task_ids = apply_task_visibility(select(m.Task.id), user)
    ticket_ids = select(cast(Ticket.id, String)).where(ticket_access_predicate(user), tickets_allowed)
    deleted_ticket_ids = select(cast(Ticket.id, String)).where(ticket_access_predicate(user, include_deleted=True), tickets_allowed)
    approval_ids = select(m.Approval.id).where(or_(
        and_(m.Approval.scope_type == m.ApprovalScopeTypeEnum.TASK,
             m.Approval.scope_id.in_(task_ids) if tasks_allowed else False),
        and_(m.Approval.scope_type.in_([m.ApprovalScopeTypeEnum.TICKET, m.ApprovalScopeTypeEnum.OVERRIDE_CLOSE]),
             m.Approval.scope_id.in_(ticket_ids)),
    ))
    return and_(
        # A resource-bearing body without a canonical reference is unattributed,
        # even if its recipient/tenant were recorded by an older producer.
        or_(~notice.type.in_([m.NotificationTypeEnum.TICKET_CREATED, m.NotificationTypeEnum.TICKET_UPDATED,
            m.NotificationTypeEnum.TICKET_ASSIGNED, m.NotificationTypeEnum.TICKET_CLOSED, m.NotificationTypeEnum.TICKET_DELETED]),
            and_(notice.entity_type == m.NotificationEntityTypeEnum.TICKET, notice.entity_id.is_not(None))),
        or_(~notice.type.in_([m.NotificationTypeEnum.TASK_CREATED, m.NotificationTypeEnum.TASK_UPDATED,
            m.NotificationTypeEnum.TASK_ASSIGNED, m.NotificationTypeEnum.TASK_COMPLETED, m.NotificationTypeEnum.TASK_DELETED,
            m.NotificationTypeEnum.TASK_OVERDUE]), notice.related_task_id.is_not(None),
            and_(notice.entity_type == m.NotificationEntityTypeEnum.TASK, notice.entity_id.is_not(None))),
        or_(~notice.type.in_([m.NotificationTypeEnum.APPROVAL_REQUESTED, m.NotificationTypeEnum.APPROVAL_ACTED,
            m.NotificationTypeEnum.SLA_BREACH, m.NotificationTypeEnum.COMMENT_ADDED]),
            notice.related_task_id.is_not(None), and_(notice.entity_type.in_([
                m.NotificationEntityTypeEnum.TASK, m.NotificationEntityTypeEnum.TICKET, m.NotificationEntityTypeEnum.APPROVAL]),
                notice.entity_id.is_not(None))),
        or_(notice.related_task_id.is_(None), notice.related_task_id.in_(task_ids) if tasks_allowed else False),
        or_(notice.entity_type.is_(None), notice.entity_type != m.NotificationEntityTypeEnum.TASK,
            and_(tasks_allowed, or_(notice.entity_id.in_(task_ids),
                and_(notice.alert_kind == "task_deleted", notice.related_task_id.is_(None))))),
        or_(notice.entity_type.is_(None), notice.entity_type != m.NotificationEntityTypeEnum.TICKET,
            notice.entity_id.in_(ticket_ids), and_(notice.type == m.NotificationTypeEnum.TICKET_DELETED,
                notice.entity_id.in_(deleted_ticket_ids))),
        or_(notice.entity_type.is_(None), notice.entity_type != m.NotificationEntityTypeEnum.APPROVAL,
            notice.entity_id.in_(approval_ids)),
    )


def ticket_module_allowed(db, user):
    from fastapi import HTTPException
    from ..navigation_registry import api_pages
    from .navigation import enforce_pages
    try:
        enforce_pages(db, user, api_pages("/tickets", "GET"))
        return True
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return False


def current_recipient(db, user):
    """Refresh delivery authority even when a worker retains an ORM identity map."""
    if not user:
        return None
    user = db.get(m.User, user.id, populate_existing=True)
    if user:
        db.get(m.NavigationPolicy, str(user.tenant_id), populate_existing=True)
    db.info.pop("phase6_module_access", None)
    return user


def can_deliver(db, notice, user):
    user = current_recipient(db, user)
    if not user or user.status != m.UserStatusEnum.ACTIVE or notice.tenant_id != user.tenant_id:
        return False
    from .workload_notifications import task_module_allowed
    values = SimpleNamespace(**{name: literal(getattr(notice, name), type_=getattr(m.Notification, name).type)
        for name in ("related_task_id", "entity_type", "entity_id", "alert_kind", "type")})
    return bool(db.scalar(select(literal(True)).where(resource_predicate(user, values,
        tasks_allowed=task_module_allowed(db, user), tickets_allowed=ticket_module_allowed(db, user)))))
