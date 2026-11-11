# ruff: noqa: B008
from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, inspect, select
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..auth import hash_password, verify_password
from ..backups.service import assert_isolated
from ..database import get_db
from ..dependencies import get_current_owner
from ..email_utils import (
    EmailDeliveryError,
    resolve_smtp_config,
    send_notification_email,
)
from ..models import task_dependencies
from ..seed import seed_database
from ..services import rewards as reward_service

OTP_EXPIRATION_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

router = APIRouter(prefix="/admin/data", tags=["admin-data"])


def _resolve_tenant_id(employer_id: str | None) -> uuid.UUID:
    if employer_id:
        try:
            return uuid.UUID(str(employer_id))
        except ValueError:
            return uuid.uuid5(uuid.NAMESPACE_URL, f"zea-play-tenant:{employer_id}")
    return uuid.uuid5(uuid.NAMESPACE_URL, "zea-play-tenant:default")


def _serialize_users(users: Iterable[models.User]) -> list[schemas.UserBackup]:
    return [
        schemas.UserBackup(
            id=user.id,
            name=user.name,
            email=user.email,
            employer_id=user.employer_id,
            role=user.role,
            status=user.status,
            department_id=user.department_id,
            manager_id=user.manager_id,
            manager_email=user.manager_email,
            shift_name=user.shift_name,
            shift_start=user.shift_start,
            shift_end=user.shift_end,
            morning_break_start=user.morning_break_start,
            morning_break_end=user.morning_break_end,
            lunch_break_start=user.lunch_break_start,
            lunch_break_end=user.lunch_break_end,
            evening_break_start=user.evening_break_start,
            evening_break_end=user.evening_break_end,
            title=user.title,
            phone=user.phone,
            location=user.location,
            timezone=user.timezone,
            profile_bio=user.profile_bio,
            notes=user.notes,
            skills=list(user.skills or []),
            projects=list(user.projects or []),
            points=user.points,
            tasks_created=user.tasks_created,
            tasks_completed=user.tasks_completed,
            clarity_scores=list(user.clarity_scores or []),
            claimed_reward_ids=list(user.claimed_reward_ids or []),
            unlocked_achievement_ids=list(user.unlocked_achievement_ids or []),
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
        for user in users
    ]


def _build_status_title_map(columns: Iterable[models.KanbanColumn]) -> dict[str, str]:
    return {column.id: column.title for column in columns}


def _serialize_tasks(tasks: Iterable[models.Task], status_title_map: dict[str, str] | None = None) -> list[schemas.TaskBackup]:
    status_title_map = status_title_map or {}
    result: list[schemas.TaskBackup] = []
    for task in tasks:
        status_key = getattr(task.status, "value", task.status)
        status_title = status_title_map.get(status_key, status_key)
        subtasks = [
            schemas.TaskSubtaskBackup(id=sub.id, title=sub.title, completed=sub.completed)
            for sub in task.subtasks
        ]
        comments = [
            schemas.TaskCommentBackup(
                id=comment.id,
                user_id=comment.user_id,
                content=comment.content,
                created_at=comment.created_at,
            )
            for comment in task.comments
        ]
        result.append(
            schemas.TaskBackup(
                id=task.id,
                title=task.title,
                description=task.description,
                status=task.status,
                status_title=status_title,
                priority=task.priority,
                team=task.team,
                assigned_to_id=task.assigned_to_id,
                task_group_id=task.task_group_id,
                created_by_id=task.created_by_id,
                created_at=task.created_at,
                updated_at=task.updated_at,
                due_at=task.due_at,
                completed_at=task.completed_at,
                recurrence_rule=task.recurrence_rule,
                recurring_task_id=task.recurring_task_id,
                clarity_rating=task.clarity_rating,
                attachments=list(task.attachments or []),
                estimated_hours=task.estimated_hours,
                tags=list(task.tags or []),
                subtasks=subtasks,
                comments=comments,
                dependencies=[dependency.id for dependency in task.dependencies],
            )
        )
    return result


def _serialize_notifications(notifications: Iterable[models.Notification]) -> list[schemas.NotificationBackup]:
    return [
        schemas.NotificationBackup(
            id=notif.id,
            user_id=notif.user_id,
            type=notif.type,
            message=notif.message,
            is_read=notif.is_read,
            related_task_id=notif.related_task_id,
            related_reward_id=notif.related_reward_id,
            related_chat_id=notif.related_chat_id,
            created_at=notif.created_at,
        )
        for notif in notifications
    ]


def _serialize_reward_claims(claims: Iterable[models.RewardClaim]) -> list[schemas.UserRewardBackup]:
    return [
        schemas.UserRewardBackup(
            id=claim.id,
            user_id=claim.user_id,
            reward_id=claim.reward_id,
            status=claim.status,
            xp_spent=claim.xp_spent,
            claimed_at=claim.claimed_at,
            resolved_at=claim.resolved_at,
            approver_id=claim.approver_id,
        )
        for claim in claims
    ]


def _serialize_user_achievements(
    user_achievements: Iterable[models.UserAchievement],
) -> list[schemas.UserAchievementBackup]:
    return [
        schemas.UserAchievementBackup(
            user_id=item.user_id,
            achievement_id=item.achievement_id,
            unlocked_at=item.unlocked_at,
        )
        for item in user_achievements
    ]


def _serialize_kanban_columns(
    columns: Iterable[models.KanbanColumn],
) -> list[schemas.KanbanColumnBackup]:
    return [
        schemas.KanbanColumnBackup(id=column.id, title=column.title, order=column.order)
        for column in columns
    ]


@router.get("/export", response_model=schemas.DataExportBundle)
def export_data(
    *,
    scope: schemas.DataExportScope = Query(default=schemas.DataExportScope.ALL),
    current_owner: models.User = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> schemas.DataExportBundle:
    assert_isolated(db, current_owner.tenant_id)

    departments: list[schemas.DepartmentRead] = []
    users: list[schemas.UserBackup] = []
    tasks: list[schemas.TaskBackup] = []
    achievements: list[schemas.AchievementRead] = []
    rewards: list[schemas.RewardRead] = []
    kanban_columns: list[schemas.KanbanColumnBackup] = []
    notifications: list[schemas.NotificationBackup] = []
    user_rewards: list[schemas.UserRewardBackup] = []
    user_achievements: list[schemas.UserAchievementBackup] = []

    if scope in {schemas.DataExportScope.USERS, schemas.DataExportScope.ALL, schemas.DataExportScope.DEPARTMENTS}:
        departments = [
            schemas.DepartmentRead.model_validate(dept)
            for dept in db.execute(select(models.Department)).scalars().all()
        ]
        if scope in {schemas.DataExportScope.USERS, schemas.DataExportScope.ALL}:
            users = _serialize_users(db.execute(select(models.User)).scalars().all())

    if scope in {schemas.DataExportScope.TASKS, schemas.DataExportScope.ALL}:
        task_query = (
            select(models.Task)
            .options(
                joinedload(models.Task.subtasks),
                joinedload(models.Task.comments),
                joinedload(models.Task.dependencies),
            )
        )
        columns: list[models.KanbanColumn] = []
        try:
            inspector = inspect(db.bind)
            if "kanban_columns" in inspector.get_table_names():
                columns = db.execute(select(models.KanbanColumn)).scalars().all()
        except Exception:  # noqa: BLE001 - legacy optional table
            columns = []
        status_title_map = _build_status_title_map(columns)
        tasks = _serialize_tasks(db.execute(task_query).unique().scalars().all(), status_title_map)
        kanban_columns = _serialize_kanban_columns(columns)

    if scope is schemas.DataExportScope.ALL:
        achievements = [
            schemas.AchievementRead.model_validate(achievement)
            for achievement in db.execute(select(models.Achievement)).scalars().all()
        ]
        rewards = [
            reward_service.get_reward_read(db, reward.id)
            for reward in db.execute(select(models.Reward)).scalars().all()
        ]
        notifications = _serialize_notifications(
            db.execute(select(models.Notification)).scalars().all()
        )
        user_rewards = _serialize_reward_claims(
            db.execute(select(models.RewardClaim)).scalars().all()
        )
        user_achievements = _serialize_user_achievements(
            db.execute(select(models.UserAchievement)).scalars().all()
        )
        if scope not in {schemas.DataExportScope.USERS}:
            if not departments:
                departments = [
                    schemas.DepartmentRead.model_validate(dept)
                    for dept in db.execute(select(models.Department)).scalars().all()
                ]
            if not users:
                users = _serialize_users(db.execute(select(models.User)).scalars().all())

    bundle = schemas.DataExportBundle(
        scope=scope,
        generated_at=datetime.now(UTC).replace(tzinfo=None),
        departments=departments,
        users=users,
        tasks=tasks,
        achievements=achievements,
        rewards=rewards,
        kanban_columns=kanban_columns,
        notifications=notifications,
        user_rewards=user_rewards,
        user_achievements=user_achievements,
    )
    return bundle


@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
def import_data(
    payload: schemas.DataImportPayload,
    current_owner: models.User = Depends(get_current_owner),
) -> dict[str, str]:
    raise HTTPException(status_code=409, detail="Legacy backups must be uploaded to /admin/data/manager/imports/validate and explicitly confirmed after preview. No records were changed.")


@router.post("/reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_reset_otp(
    current_owner: models.User = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    assert_isolated(db, current_owner.tenant_id)
    otp = ''.join(secrets.choice('0123456789') for _ in range(6))
    otp_hash = hash_password(otp)
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=OTP_EXPIRATION_MINUTES)

    token = db.get(models.OwnerResetToken, current_owner.id)
    if token:
        token.otp_hash = otp_hash
        token.expires_at = expires_at
        token.attempts = 0
        token.created_at = datetime.now(UTC).replace(tzinfo=None)
    else:
        token = models.OwnerResetToken(
            owner_id=current_owner.id,
            otp_hash=otp_hash,
            expires_at=expires_at,
            attempts=0,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.add(token)
    db.commit()

    smtp_config = resolve_smtp_config(db, "system_alerts", tenant_id=str(current_owner.tenant_id))
    if not smtp_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SMTP configuration is required before requesting a reset.",
        )
    try:
        send_notification_email(
            db=db,
            notification_type="system_alerts",
            to_address=current_owner.email,
            subject="Vee Task Manager reset OTP",
            body=(
                "A full system reset was requested.\n\n"
                f"One Time Passcode: {otp}\n"
                "This code expires in 10 minutes. If you did not request this, please contact support."
            ),
        )
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send verification email: {exc}",
        ) from exc

    return {"status": "otp_sent"}


@router.post("/reset/confirm", status_code=status.HTTP_202_ACCEPTED)
def confirm_reset(
    payload: schemas.ResetConfirmPayload,
    current_owner: models.User = Depends(get_current_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if payload.confirmation != "RESET WORKSPACE":
        raise HTTPException(status_code=422, detail="Explicit workspace reset confirmation is required.")
    assert_isolated(db, current_owner.tenant_id)
    token = db.execute(select(models.OwnerResetToken).where(models.OwnerResetToken.owner_id == current_owner.id).with_for_update()).scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset not requested")

    if datetime.now(UTC).replace(tzinfo=None) > token.expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP expired")

    if token.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")

    if not verify_password(payload.otp, token.otp_hash):
        token.attempts += 1
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP")

    # OTP valid – perform reset
    db.delete(token)

    with db.begin_nested():
        session = db
        session.execute(delete(models.Notification))
        session.execute(delete(models.RewardClaim))
        session.execute(delete(models.UserAchievement))
        session.execute(delete(models.Comment))
        session.execute(delete(models.Subtask))
        session.execute(task_dependencies.delete())
        session.execute(delete(models.Task))
        session.execute(delete(models.KanbanColumn))
        session.execute(delete(models.Reward))
        session.execute(delete(models.Achievement))
        session.execute(delete(models.User))
        session.execute(delete(models.Department))
        session.execute(delete(models.OwnerResetToken))

        session.add(models.AuditEvent(id=str(uuid.uuid4()), actor_id=None, event_type="FULL_WORKSPACE_RESET",
            entity_type="workspace", entity_id=str(current_owner.tenant_id),
            payload={"tenant_id": str(current_owner.tenant_id), "requested_by": current_owner.id}))
    db.commit()
    seed_database()

    return {"status": "reset"}
