from datetime import datetime, timedelta
import json
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, and_, cast, String, select, update
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_admin, get_current_active_user
from ..services import rewards as reward_service
from ..services import audit_logger
from ..services.audit_security import audit_read
from ..services.task_access import apply_task_visibility
from ..tickets.access import ticket_access_predicate
from ..tickets.models import Ticket

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=schemas.RewardLogListResponse)
def list_logs(
    subject_type: str | None = Query(default="reward"),
    subject_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    action_enum = None
    if action:
        try:
            action_enum = models.RewardLogActionEnum(action)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown action filter",
            ) from exc
    return reward_service.list_logs(
        db,
        actor=current_user,
        subject_type=subject_type,
        subject_id=subject_id,
        action=action_enum,
        page=page,
        page_size=page_size,
    )


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_or_create_retention_config(db: Session) -> models.AuditRetentionConfig:
    config = db.get(models.AuditRetentionConfig, 1)
    return config or models.AuditRetentionConfig(id=1, retention_days=90,
        created_at=datetime.utcnow(), updated_at=datetime.utcnow())


def _apply_scope_filters(
    stmt,
    *,
    current_user: models.User,
    db: Session,
):
    stmt = stmt.where(models.AuditLog.tenant_id == current_user.tenant_id)
    if current_user.role in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}:
        return stmt
    task_ids = apply_task_visibility(select(models.Task.id), current_user)
    ticket_ids = select(cast(Ticket.id, String)).where(ticket_access_predicate(current_user))
    approvals = select(models.Approval.id).where(or_(
        and_(models.Approval.scope_type == models.ApprovalScopeTypeEnum.TASK, models.Approval.scope_id.in_(task_ids)),
        and_(models.Approval.scope_type.in_([models.ApprovalScopeTypeEnum.TICKET, models.ApprovalScopeTypeEnum.OVERRIDE_CLOSE]),
             models.Approval.scope_id.in_(ticket_ids)),
    ))
    from ..services.notification_access import resource_predicate
    notices = select(models.Notification.id).where(models.Notification.tenant_id == current_user.tenant_id,
        resource_predicate(current_user))
    resource_scope = or_(
        and_(models.AuditLog.entity_type == "task", models.AuditLog.entity_id.in_(task_ids)),
        and_(models.AuditLog.entity_type == "ticket", models.AuditLog.entity_id.in_(ticket_ids)),
        and_(models.AuditLog.entity_type == "approval", models.AuditLog.entity_id.in_(approvals)),
        and_(models.AuditLog.entity_type == "notification", models.AuditLog.entity_id.in_(notices)),
        and_(models.AuditLog.entity_type == "subtask", models.AuditLog.entity_id.in_(
            select(models.Subtask.id).where(models.Subtask.task_id.in_(task_ids)))),
    )
    subjects = select(models.User.id).where(models.User.tenant_id == current_user.tenant_id)
    if current_user.role == models.RoleEnum.MANAGER and current_user.department_id:
        subjects = subjects.where(models.User.department_id == current_user.department_id)
    else:
        subjects = subjects.where(models.User.id == current_user.id)
    personal = or_(models.AuditLog.actor_id.in_(subjects), models.AuditLog.target_user_id.in_(subjects))
    # Resource history cannot be obtained merely by being the historical actor.
    return stmt.where(or_(resource_scope, and_(
        or_(models.AuditLog.entity_type.is_(None), ~models.AuditLog.entity_type.in_(["task", "ticket", "approval", "notification", "subtask"])), personal)))


def _build_audit_log_query(
    *,
    db: Session,
    current_user: models.User,
    categories: list[str],
    entity_types: list[str],
    actions: list[str],
    actor_ids: list[str],
    severity: list[str],
    source: list[str],
    status_values: list[str],
    start_at: datetime | None,
    end_at: datetime | None,
    include_deleted: bool,
):
    stmt = (
        select(models.AuditLog)
        .options(selectinload(models.AuditLog.actor))
        .order_by(models.AuditLog.created_at.desc())
    )
    if not include_deleted:
        stmt = stmt.where(models.AuditLog.deleted_at.is_(None))
    if categories:
        stmt = stmt.where(models.AuditLog.category.in_(categories))
    if entity_types:
        stmt = stmt.where(models.AuditLog.entity_type.in_(entity_types))
    if actions:
        stmt = stmt.where(models.AuditLog.action.in_(actions))
    if actor_ids:
        stmt = stmt.where(models.AuditLog.actor_id.in_(actor_ids))
    if severity:
        stmt = stmt.where(models.AuditLog.severity.in_(severity))
    if source:
        stmt = stmt.where(models.AuditLog.source.in_(source))
    if status_values:
        stmt = stmt.where(models.AuditLog.status.in_(status_values))
    if start_at:
        stmt = stmt.where(models.AuditLog.created_at >= start_at)
    if end_at:
        stmt = stmt.where(models.AuditLog.created_at <= end_at)
    stmt = _apply_scope_filters(stmt, current_user=current_user, db=db)
    return stmt


@router.get("/audit", response_model=schemas.AuditLogListResponse)
def list_audit_logs(
    category: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    source: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> schemas.AuditLogListResponse:
    categories = _parse_csv(category)
    entity_types = _parse_csv(entity_type)
    actions = _parse_csv(action)
    actor_ids = _parse_csv(actor_id)
    severity_values = _parse_csv(severity)
    source_values = _parse_csv(source)
    status_values = _parse_csv(status_filter)

    stmt = _build_audit_log_query(
        db=db,
        current_user=current_user,
        categories=categories,
        entity_types=entity_types,
        actions=actions,
        actor_ids=actor_ids,
        severity=severity_values,
        source=source_values,
        status_values=status_values,
        start_at=start_at,
        end_at=end_at,
        include_deleted=include_deleted,
    )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = (
        db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        .scalars()
        .all()
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return schemas.AuditLogListResponse(
        items=[audit_read(item, current_user) for item in items],
        page=page,
        total=total,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/audit/export")
def export_audit_logs(
    format: str = Query(default="csv"),
    category: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    source: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> Response:
    if format not in {"csv", "json"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported export format")

    stmt = _build_audit_log_query(
        db=db,
        current_user=current_user,
        categories=_parse_csv(category),
        entity_types=_parse_csv(entity_type),
        actions=_parse_csv(action),
        actor_ids=_parse_csv(actor_id),
        severity=_parse_csv(severity),
        source=_parse_csv(source),
        status_values=_parse_csv(status_filter),
        start_at=start_at,
        end_at=end_at,
        include_deleted=include_deleted,
    )
    items = db.execute(stmt).scalars().all()

    if format == "json":
        payload = [audit_read(item, current_user).model_dump() for item in items]
        return Response(
            content=json.dumps(payload, default=str),
            media_type="application/json",
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "created_at",
            "actor_id",
            "actor_role",
            "action",
            "category",
            "entity_type",
            "entity_id",
            "target_user_id",
            "severity",
            "source",
            "status",
            "ip_address",
            "user_agent",
            "old_value",
            "new_value",
        ]
    )
    for row in items:
        item = audit_read(row, current_user)
        writer.writerow(
            [
                item.id,
                item.created_at.isoformat(),
                item.actor_id or "",
                item.actor_role or "",
                item.action,
                item.category.value if item.category else "",
                item.entity_type or "",
                item.entity_id or "",
                item.target_user_id or "",
                item.severity.value if item.severity else "",
                item.source.value if item.source else "",
                item.status.value if item.status else "",
                item.ip_address or "",
                item.user_agent or "",
                item.old_value or "",
                item.new_value or "",
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit-logs.csv"},
    )


@router.get("/retention", response_model=schemas.AuditRetentionConfigRead)
def get_retention_config(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
) -> schemas.AuditRetentionConfigRead:
    config = _get_or_create_retention_config(db)
    return schemas.AuditRetentionConfigRead.model_validate(config)


@router.patch("/retention", response_model=schemas.AuditRetentionConfigRead)
def update_retention_config(
    payload: schemas.AuditRetentionConfigUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
) -> schemas.AuditRetentionConfigRead:
    if current_user.role not in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    raise HTTPException(409, "Global retention configuration requires an approved tenancy migration")


@router.post("/retention/apply", response_model=schemas.AuditRetentionApplyResponse)
def apply_retention_policy(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
) -> schemas.AuditRetentionApplyResponse:
    if current_user.role not in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    config = _get_or_create_retention_config(db)
    cutoff = datetime.utcnow() - timedelta(days=config.retention_days)
    stmt = (
        update(models.AuditLog)
        .where(models.AuditLog.tenant_id == current_user.tenant_id,
               models.AuditLog.created_at < cutoff, models.AuditLog.deleted_at.is_(None))
        .values(deleted_at=datetime.utcnow())
    )
    result = db.execute(stmt)
    db.commit()
    return schemas.AuditRetentionApplyResponse(
        updated=result.rowcount or 0,
        cutoff_at=cutoff,
        retention_days=config.retention_days,
    )


@router.post("/audit/{log_id}/retry")
def retry_audit_log(
    log_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    log = db.scalar(_apply_scope_filters(select(models.AuditLog).where(
        models.AuditLog.id == log_id, models.AuditLog.deleted_at.is_(None)), current_user=current_user, db=db))
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found")
    if log.category != models.AuditLogCategoryEnum.AUTOMATION:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Retry supported for automation logs only")
    if current_user.role not in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER, models.RoleEnum.MANAGER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")

    audit_logger.log_event(
        audit_logger.AuditLogInput(
            action="AUTOMATION_RETRY_REQUESTED",
            category=models.AuditLogCategoryEnum.AUTOMATION,
            actor_id=str(current_user.id),
            actor_role=current_user.role.value if current_user.role else None,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            source=models.AuditLogSourceEnum.MANUAL,
            metadata={"retry_log_id": log_id, "original_action": log.action},
        )
    )
    return {"status": "queued"}
    def parse_csv(value: str | None) -> list[str]:
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    entity_types = parse_csv(entity_type)
    event_types = parse_csv(event_type)

    stmt = (
        select(models.AuditEvent)
        .options(selectinload(models.AuditEvent.actor))
        .order_by(models.AuditEvent.created_at.desc())
    )
    if entity_types:
        stmt = stmt.where(models.AuditEvent.entity_type.in_(entity_types))
    if event_types:
        stmt = stmt.where(models.AuditEvent.event_type.in_(event_types))
    if actor_id:
        stmt = stmt.where(models.AuditEvent.actor_id == actor_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = (
        db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        .scalars()
        .all()
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return schemas.AuditEventListResponse(
        items=[schemas.AuditEventRead.model_validate(item) for item in items],
        page=page,
        total=total,
        page_size=page_size,
        total_pages=total_pages,
    )
