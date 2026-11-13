"""SQL object policy shared by ticket reads, audit and notification queries."""
from sqlalchemy import and_, or_, select, cast, String
from .. import models as m
from . import models as t


def ticket_access_predicate(user, *, include_deleted=False):
    ticket = t.Ticket
    tenant = ticket.tenant_id == user.tenant_id
    live = True if include_deleted else ticket.deleted_at.is_(None)
    if user.role in {m.RoleEnum.ADMIN, m.RoleEnum.OWNER}:
        scope = True
    elif user.role == m.RoleEnum.MANAGER:
        scope = ticket.department_id == user.department_id if user.department_id else False
    else:
        def linked(model, *conditions):
            return select(model.id).where(model.tenant_id == user.tenant_id,
                model.ticket_id == ticket.id, *conditions).correlate(ticket).exists()
        cycle = select(t.TicketApprovalItem.id).join(t.TicketApprovalCycle,
            t.TicketApprovalCycle.id == t.TicketApprovalItem.cycle_id).where(
                t.TicketApprovalCycle.ticket_id == ticket.id,
                t.TicketApprovalCycle.tenant_id == user.tenant_id,
                t.TicketApprovalItem.tenant_id == user.tenant_id,
                t.TicketApprovalItem.approver_user_id == user.id,
                t.TicketApprovalItem.status.in_([t.TicketApprovalItemStatusEnum.PENDING, t.TicketApprovalItemStatusEnum.OVERDUE]),
                t.TicketApprovalCycle.status.in_([t.TicketApprovalCycleStatusEnum.PENDING, t.TicketApprovalCycleStatusEnum.OVERDUE]),
            ).correlate(ticket).exists()
        approval = select(t.TicketApprovalUser.id).join(t.TicketApproval,
            t.TicketApproval.id == t.TicketApprovalUser.approval_id).where(
                t.TicketApproval.ticket_id == ticket.id, t.TicketApproval.tenant_id == user.tenant_id,
                t.TicketApproval.status == t.TicketApprovalStatusEnum.PENDING,
                t.TicketApprovalUser.tenant_id == user.tenant_id, t.TicketApprovalUser.user_id == user.id,
                t.TicketApprovalUser.decision == t.TicketApprovalDecisionEnum.PENDING,
            ).correlate(ticket).exists()
        sequential = select(m.Approval.id).where(
            m.Approval.scope_type == m.ApprovalScopeTypeEnum.TICKET,
            m.Approval.scope_id == cast(ticket.id, String), m.Approval.approver_id == user.id,
            m.Approval.status == m.ApprovalStatusEnum.PENDING,
        ).correlate(ticket).exists()
        scope = or_(ticket.created_by == user.id, ticket.owner_id == user.id,
            linked(t.TicketParticipant, t.TicketParticipant.user_id == user.id, t.TicketParticipant.deleted_at.is_(None)),
            linked(t.TicketFollower, t.TicketFollower.user_id == user.id, t.TicketFollower.deleted_at.is_(None)),
            cycle, approval, sequential)
    return and_(tenant, live, scope)
