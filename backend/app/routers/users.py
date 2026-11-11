import logging
from datetime import UTC, datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..auth import hash_password, verify_password
from ..avatar_http import AvatarUploadRoute
from ..avatar_utils import (
    apply_avatar_crop,
    assign_user_avatar,
    load_avatar_image,
    max_avatar_bytes,
    resolve_avatar_asset,
    set_user_avatar_from_data_url,
    set_user_avatar_image,
    user_avatar_url,
)
from ..database import get_db
from ..dependencies import get_current_active_user, get_current_admin
from ..email_utils import send_notification_email
from ..integrations import trigger_n8n_event
from ..services import audit_logger
from ..services import notifications as notification_service

router = APIRouter(prefix="/users", tags=["users"], route_class=AvatarUploadRoute)

# FastAPI inspects these reusable dependency markers for each request.
_db_dependency = Depends(get_db)
_active_dependency = Depends(get_current_active_user)
_admin_dependency = Depends(get_current_admin)


def _check_profile_version(user, payload):
    expected = getattr(payload, "expected_updated_at", None)

    def utc(value):
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )

    if expected and user.updated_at and utc(expected) != utc(user.updated_at):
        raise HTTPException(
            status_code=409, detail="This profile changed. Reload it before saving."
        )


def _validate_manager(db, payload, actor):
    if getattr(payload, "manager_id", None):
        manager = db.get(models.User, payload.manager_id)
        if not manager or manager.tenant_id != actor.tenant_id:
            raise HTTPException(
                status_code=400, detail="Manager not found in this tenant"
            )


def _ensure_avatar_permission(actor: models.User, target: models.User) -> None:
    if not actor.tenant_id or actor.tenant_id != target.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    if actor.id == target.id:
        return
    if actor.role not in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to update this avatar",
        )


def _hydrate_user_avatar(
    user: models.User, viewer: models.User | None = None
) -> schemas.UserRead:
    asset = user.avatar_asset
    resolved_url = user_avatar_url(user)
    if asset:
        asset.url = resolved_url
    result = schemas.UserRead.model_validate(user)
    result._include_private_fields = (
        viewer is None
        or viewer.id == user.id
        or viewer.role in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}
    )
    result._include_internal_notes = (viewer or user).role in {
        models.RoleEnum.ADMIN,
        models.RoleEnum.OWNER,
    }
    result.avatar_url = resolved_url
    result.profile_image_key = None
    result.profile_image_url = None if asset else resolved_url
    # Never mutate mapped legacy columns while serving a read.
    if not result._include_private_fields:
        sensitive = {
            "phone",
            "location",
            "timezone",
            "notes",
            "manager_email",
            "profile_image_key",
            "shift_name",
            "shift_start",
            "shift_end",
            "morning_break_start",
            "morning_break_end",
            "lunch_break_start",
            "lunch_break_end",
            "evening_break_start",
            "evening_break_end",
        }
        for field in sensitive:
            setattr(result, field, None)
        result.model_fields_set.difference_update(sensitive)
    return result


def _get_admin_ids(db: Session, tenant_id) -> list[str]:
    return (
        db.execute(
            select(models.User.id).where(
                models.User.tenant_id == tenant_id,
                models.User.role.in_({models.RoleEnum.ADMIN, models.RoleEnum.OWNER}),
            )
        )
        .scalars()
        .all()
    )


def _apply_user_updates(
    db: Session, user: models.User, payload: schemas.UserUpdate, actor: models.User
) -> None:
    _check_profile_version(user, payload)
    if actor.role != models.RoleEnum.OWNER and (
        user.role == models.RoleEnum.OWNER or payload.role == models.RoleEnum.OWNER
    ):
        raise HTTPException(
            status_code=403, detail="Only an owner can manage owner accounts"
        )
    if actor.role == models.RoleEnum.MANAGER:
        # Managers retain ordinary user management, never authority over privileges,
        # employment records, private contacts or another employee's credentials.
        protected = {
            "role",
            "employer_id",
            "department_id",
            "manager_id",
            "manager_email",
            "password",
            "phone",
            "location",
            "timezone",
            "notes",
            "shift_name",
            "shift_start",
            "shift_end",
            "morning_break_start",
            "morning_break_end",
            "lunch_break_start",
            "lunch_break_end",
            "evening_break_start",
            "evening_break_end",
        }
        if (
            protected.intersection(payload.model_fields_set)
            or user.role == models.RoleEnum.OWNER
        ):
            raise HTTPException(
                status_code=403,
                detail="Employment and security details require administrator access",
            )
    if {"avatar_asset_id", "avatar_frame"}.intersection(payload.model_fields_set):
        _ensure_avatar_permission(actor, user)
    if "profile_bio" in payload.model_fields_set:
        user.profile_bio = payload.profile_bio
    if payload.name is not None:
        user.name = payload.name
    if "employer_id" in payload.model_fields_set:
        user.employer_id = payload.employer_id
    if payload.role is not None:
        user.role = payload.role
    if payload.status is not None:
        user.status = payload.status
    if "department_id" in payload.model_fields_set:
        user.department_id = payload.department_id
    if "manager_id" in payload.model_fields_set:
        user.manager_id = payload.manager_id
    if "manager_email" in payload.model_fields_set:
        user.manager_email = payload.manager_email
    if "shift_name" in payload.model_fields_set:
        user.shift_name = payload.shift_name
    if "shift_start" in payload.model_fields_set:
        user.shift_start = payload.shift_start
    if "shift_end" in payload.model_fields_set:
        user.shift_end = payload.shift_end
    if "morning_break_start" in payload.model_fields_set:
        user.morning_break_start = payload.morning_break_start
    if "morning_break_end" in payload.model_fields_set:
        user.morning_break_end = payload.morning_break_end
    if "lunch_break_start" in payload.model_fields_set:
        user.lunch_break_start = payload.lunch_break_start
    if "lunch_break_end" in payload.model_fields_set:
        user.lunch_break_end = payload.lunch_break_end
    if "evening_break_start" in payload.model_fields_set:
        user.evening_break_start = payload.evening_break_start
    if "evening_break_end" in payload.model_fields_set:
        user.evening_break_end = payload.evening_break_end
    if "title" in payload.model_fields_set:
        user.title = payload.title
    if "phone" in payload.model_fields_set:
        user.phone = payload.phone
    if "location" in payload.model_fields_set:
        user.location = payload.location
    if "timezone" in payload.model_fields_set:
        user.timezone = payload.timezone
    if "notes" in payload.model_fields_set:
        user.notes = payload.notes
    if "skills" in payload.model_fields_set:
        user.skills = payload.skills or []
    if "projects" in payload.model_fields_set:
        user.projects = payload.projects or []
    if payload.points is not None:
        user.points = payload.points
    if payload.tasks_created is not None:
        user.tasks_created = payload.tasks_created
    if payload.tasks_completed is not None:
        user.tasks_completed = payload.tasks_completed
    if payload.clarity_scores is not None:
        user.clarity_scores = payload.clarity_scores
    if payload.claimed_reward_ids is not None:
        user.claimed_reward_ids = payload.claimed_reward_ids
    if payload.unlocked_achievement_ids is not None:
        user.unlocked_achievement_ids = payload.unlocked_achievement_ids
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)
    if "avatar_asset_id" in payload.model_fields_set:
        assign_user_avatar(db, user, payload.avatar_asset_id, actor)
    if "avatar_frame" in payload.model_fields_set:
        user.avatar_frame = payload.avatar_frame


@router.get(
    "", response_model=list[schemas.UserRead], response_model_exclude_unset=True
)
def list_users(
    db: Session = _db_dependency,
    current_user: models.User = _active_dependency,
) -> list[schemas.UserRead]:
    stmt = (
        select(models.User)
        .options(
            selectinload(models.User.avatar_asset),
            selectinload(models.User.department),
            selectinload(models.User.reward_claims),
        )
        .where(models.User.tenant_id == current_user.tenant_id)
    )
    users = db.execute(stmt).scalars().all()
    return [_hydrate_user_avatar(user, current_user) for user in users]


@router.patch("/me", response_model=schemas.UserRead)
def update_current_user(
    payload: schemas.UserProfileUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: models.User = _active_dependency,
    db: Session = _db_dependency,
) -> schemas.UserRead:
    user = db.scalar(
        select(models.User)
        .where(
            models.User.id == current_user.id,
            models.User.tenant_id == current_user.tenant_id,
        )
        .with_for_update()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    _check_profile_version(user, payload)
    protected = {
        "employer_id",
        "department_id",
        "manager_email",
        "shift_name",
        "shift_start",
        "shift_end",
        "morning_break_start",
        "morning_break_end",
        "lunch_break_start",
        "lunch_break_end",
        "evening_break_start",
        "evening_break_end",
    }
    if current_user.role not in {
        models.RoleEnum.ADMIN,
        models.RoleEnum.OWNER,
    } and protected.intersection(payload.model_fields_set):
        raise HTTPException(
            status_code=403,
            detail="Employment details require administrator access",
        )
    for field in ("profile_bio", "phone", "location", "timezone", "skills"):
        if field in payload.model_fields_set:
            setattr(
                user,
                field,
                (payload.skills or [])
                if field == "skills"
                else getattr(payload, field),
            )
    if payload.name is not None:
        user.name = payload.name
    if "employer_id" in payload.model_fields_set:
        user.employer_id = payload.employer_id
    if "department_id" in payload.model_fields_set:
        user.department_id = payload.department_id
    if "manager_email" in payload.model_fields_set:
        user.manager_email = payload.manager_email
    if "shift_name" in payload.model_fields_set:
        user.shift_name = payload.shift_name
    if "shift_start" in payload.model_fields_set:
        user.shift_start = payload.shift_start
    if "shift_end" in payload.model_fields_set:
        user.shift_end = payload.shift_end
    if "morning_break_start" in payload.model_fields_set:
        user.morning_break_start = payload.morning_break_start
    if "morning_break_end" in payload.model_fields_set:
        user.morning_break_end = payload.morning_break_end
    if "lunch_break_start" in payload.model_fields_set:
        user.lunch_break_start = payload.lunch_break_start
    if "lunch_break_end" in payload.model_fields_set:
        user.lunch_break_end = payload.lunch_break_end
    if "evening_break_start" in payload.model_fields_set:
        user.evening_break_start = payload.evening_break_start
    if "evening_break_end" in payload.model_fields_set:
        user.evening_break_end = payload.evening_break_end
    if "avatar_asset_id" in payload.model_fields_set:
        assign_user_avatar(db, user, payload.avatar_asset_id, current_user)
    if "avatar_frame" in payload.model_fields_set:
        user.avatar_frame = payload.avatar_frame

    db.commit()
    db.refresh(user)
    hydrated_user = _hydrate_user_avatar(user, current_user)
    serialized_user = schemas.UserRead.model_validate(hydrated_user).model_dump()
    background_tasks.add_task(trigger_n8n_event, "user.updated", serialized_user)
    update_fields = sorted(payload.model_dump(exclude_unset=True).keys())
    if update_fields:
        audit_logger.log_event(
            audit_logger.AuditLogInput(
                action="USER_PROFILE_UPDATED",
                category=models.AuditLogCategoryEnum.USER,
                actor_id=str(current_user.id),
                actor_role=current_user.role.value if current_user.role else None,
                target_user_id=str(current_user.id),
                entity_type="user",
                entity_id=str(current_user.id),
                source=models.AuditLogSourceEnum.MANUAL,
                metadata={"fields": update_fields},
                request=request,
            )
        )
        db.add(
            models.AuditEvent(
                actor_id=current_user.id,
                event_type="user.updated",
                entity_type="user",
                entity_id=user.id,
                payload={"fields": update_fields},
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        db.commit()
    return hydrated_user


@router.get("/{user_id}/avatar-image")
def legacy_avatar_image(
    user_id: str,
    db: Session = _db_dependency,
    current_user: models.User = _active_dependency,
):
    from contextlib import closing

    from fastapi import Response

    from ..avatar_utils import encode_avatar
    from ..services.minio_media_service import _get_minio_client, _require_bucket

    user = db.scalar(
        select(models.User).where(
            models.User.id == user_id, models.User.tenant_id == current_user.tenant_id
        )
    )
    if (
        not user
        or not user.profile_image_key
        or not user.profile_image_key.startswith(f"avatars/{user.id}/")
        or ".." in user.profile_image_key
    ):
        raise HTTPException(status_code=404, detail="Avatar not found")
    response = _get_minio_client().get_object(
        Bucket=_require_bucket(), Key=user.profile_image_key
    )
    with closing(response["Body"]) as body:
        image = load_avatar_image(body.read(max_avatar_bytes() + 1))
    return Response(
        encode_avatar(image, 512),
        media_type="image/webp",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{user_id}", response_model=schemas.UserRead, response_model_exclude_unset=True
)
def get_user(
    user_id: str,
    db: Session = _db_dependency,
    current_user: models.User = _active_dependency,
) -> schemas.UserRead:
    stmt = (
        select(models.User)
        .options(selectinload(models.User.avatar_asset))
        .where(
            models.User.id == user_id, models.User.tenant_id == current_user.tenant_id
        )
    )
    user = db.execute(stmt).scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return _hydrate_user_avatar(user, current_user)


@router.post("", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.UserCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = _db_dependency,
    current_user: models.User = _admin_dependency,
) -> schemas.UserRead:
    if (
        current_user.role == models.RoleEnum.MANAGER
        and payload.role != models.RoleEnum.USER
    ):
        raise HTTPException(
            status_code=403,
            detail="Managers may only create ordinary employee accounts",
        )
    if (
        current_user.role != models.RoleEnum.OWNER
        and payload.role == models.RoleEnum.OWNER
    ):
        raise HTTPException(
            status_code=403, detail="Only an owner can create owner accounts"
        )
    if db.execute(
        select(models.User).where(models.User.email == payload.email)
    ).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists"
        )
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identifier"
        )
    if payload.department_id:
        department = db.get(models.Department, payload.department_id)
        if not department:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Department not found"
            )

    _validate_manager(db, payload, current_user)
    avatar_asset_id = None
    if payload.avatar_asset_id:
        asset = resolve_avatar_asset(db, payload.avatar_asset_id, current_user)
        avatar_asset_id = asset.id

    user = models.User(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        email=payload.email,
        employer_id=payload.employer_id,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        status=payload.status,
        department_id=payload.department_id,
        manager_id=payload.manager_id,
        manager_email=payload.manager_email,
        shift_name=payload.shift_name,
        shift_start=payload.shift_start,
        shift_end=payload.shift_end,
        morning_break_start=payload.morning_break_start,
        morning_break_end=payload.morning_break_end,
        lunch_break_start=payload.lunch_break_start,
        lunch_break_end=payload.lunch_break_end,
        evening_break_start=payload.evening_break_start,
        evening_break_end=payload.evening_break_end,
        title=payload.title,
        phone=payload.phone,
        location=payload.location,
        timezone=payload.timezone,
        profile_bio=payload.profile_bio,
        notes=payload.notes,
        skills=payload.skills or [],
        projects=payload.projects or [],
        avatar_asset_id=avatar_asset_id,
        avatar_frame=payload.avatar_frame,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to create user. Check required fields and references.",
        ) from exc
    db.refresh(user)
    serialized_user = schemas.UserRead.model_validate(
        _hydrate_user_avatar(user, current_user)
    ).model_dump()
    background_tasks.add_task(trigger_n8n_event, "user.created", serialized_user)
    audit_logger.log_event(
        audit_logger.AuditLogInput(
            action="USER_CREATED",
            category=models.AuditLogCategoryEnum.USER,
            actor_id=str(current_user.id),
            actor_role=current_user.role.value if current_user.role else None,
            target_user_id=str(user.id),
            entity_type="user",
            entity_id=str(user.id),
            source=models.AuditLogSourceEnum.MANUAL,
            metadata={"email": user.email, "role": user.role.value},
            request=request,
        )
    )
    for admin_id in _get_admin_ids(db, current_user.tenant_id):
        if admin_id == current_user.id:
            continue
        notification_service.create_notification(
            db,
            user_id=admin_id,
            actor_id=str(current_user.id),
            notification_type=models.NotificationTypeEnum.USER_CREATED,
            message=f"New user '{user.name}' created.",
            title="User created",
            body=f"User '{user.name}' was created.",
            entity_type=models.NotificationEntityTypeEnum.USER,
            entity_id=str(user.id),
            deep_link=f"/users/{user.id}",
        )
    db.add(
        models.AuditEvent(
            actor_id=current_user.id,
            event_type="user.created",
            entity_type="user",
            entity_id=user.id,
            payload={"name": user.name, "email": user.email, "role": user.role.value},
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    db.commit()

    # Send welcome email if SMTP is configured
    try:
        subject = "Welcome to the Task Management System"
        body = f"""
Hello {user.name},

Welcome to our Task Management System! Your account has been created successfully.

You can now log in with your email: {user.email}

Best regards,
The Task Management Team
"""
        send_notification_email(
            db=db,
            notification_type="welcome_password",
            to_address=user.email,
            subject=subject,
            body=body,
        )
    except Exception:
        # Don't fail user creation if email sending fails
        logging.getLogger(__name__).warning(
            "Welcome email failed after user creation", exc_info=True
        )

    return _hydrate_user_avatar(user, current_user)


@router.patch("/{user_id}", response_model=schemas.UserRead)
def update_user(
    user_id: str,
    payload: schemas.UserUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = _db_dependency,
    current_user: models.User = _admin_dependency,
) -> schemas.UserRead:
    user = db.scalar(
        select(models.User)
        .where(
            models.User.id == user_id, models.User.tenant_id == current_user.tenant_id
        )
        .with_for_update()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    before: dict[str, object] = {}
    after: dict[str, object] = {}
    if payload.role is not None and payload.role != user.role:
        before["role"] = user.role.value
        after["role"] = payload.role.value
    if payload.status is not None and payload.status != user.status:
        before["status"] = user.status.value
        after["status"] = payload.status.value
    if (
        payload.department_id is not None
        and payload.department_id != user.department_id
    ):
        before["department_id"] = (
            str(user.department_id) if user.department_id else None
        )
        after["department_id"] = (
            str(payload.department_id) if payload.department_id else None
        )

    _validate_manager(db, payload, current_user)
    _apply_user_updates(db, user, payload, current_user)
    db.commit()
    db.refresh(user)
    hydrated_user = _hydrate_user_avatar(user, current_user)
    serialized_user = schemas.UserRead.model_validate(hydrated_user).model_dump()
    background_tasks.add_task(trigger_n8n_event, "user.updated", serialized_user)
    update_fields = sorted(payload.model_dump(exclude_unset=True).keys())
    if update_fields:
        audit_logger.log_event(
            audit_logger.AuditLogInput(
                action="USER_UPDATED",
                category=models.AuditLogCategoryEnum.USER,
                actor_id=str(current_user.id),
                actor_role=current_user.role.value if current_user.role else None,
                target_user_id=str(user.id),
                entity_type="user",
                entity_id=str(user.id),
                source=models.AuditLogSourceEnum.MANUAL,
                before=before or None,
                after=after or None,
                metadata={"fields": update_fields},
                request=request,
            )
        )
        for admin_id in _get_admin_ids(db, current_user.tenant_id):
            if admin_id == current_user.id:
                continue
            notification_service.create_notification(
                db,
                user_id=admin_id,
                actor_id=str(current_user.id),
                notification_type=models.NotificationTypeEnum.USER_UPDATED,
                message=f"User '{user.name}' was updated.",
                title="User updated",
                body=f"User '{user.name}' was updated.",
                entity_type=models.NotificationEntityTypeEnum.USER,
                entity_id=str(user.id),
                deep_link=f"/users/{user.id}",
            )
        db.add(
            models.AuditEvent(
                actor_id=current_user.id,
                event_type="user.updated",
                entity_type="user",
                entity_id=user.id,
                payload={"fields": update_fields},
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        db.commit()
    return hydrated_user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = _db_dependency,
    current_user: models.User = _admin_dependency,
) -> None:
    stmt = (
        select(models.User)
        .options(selectinload(models.User.avatar_asset))
        .where(
            models.User.id == user_id, models.User.tenant_id == current_user.tenant_id
        )
        .with_for_update()
    )
    user = db.execute(stmt).scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if current_user.role != models.RoleEnum.OWNER and (
        user.role == models.RoleEnum.OWNER
        or (
            current_user.role == models.RoleEnum.MANAGER
            and user.role != models.RoleEnum.USER
        )
    ):
        raise HTTPException(
            status_code=403, detail="Insufficient permissions to delete this account"
        )
    serialized_user = schemas.UserRead.model_validate(
        _hydrate_user_avatar(user, current_user)
    ).model_dump()
    audit_logger.log_event(
        audit_logger.AuditLogInput(
            action="USER_DELETED",
            category=models.AuditLogCategoryEnum.USER,
            actor_id=str(current_user.id),
            actor_role=current_user.role.value if current_user.role else None,
            target_user_id=str(user.id),
            entity_type="user",
            entity_id=str(user.id),
            source=models.AuditLogSourceEnum.MANUAL,
            metadata={"name": user.name, "email": user.email, "role": user.role.value},
            request=request,
        )
    )
    db.add(
        models.AuditEvent(
            actor_id=current_user.id,
            event_type="user.deleted",
            entity_type="user",
            entity_id=user.id,
            payload={"name": user.name, "email": user.email, "role": user.role.value},
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    for admin_id in _get_admin_ids(db, current_user.tenant_id):
        if admin_id == current_user.id:
            continue
        notification_service.create_notification(
            db,
            user_id=admin_id,
            actor_id=str(current_user.id),
            notification_type=models.NotificationTypeEnum.USER_DELETED,
            message=f"User '{user.name}' was deleted.",
            title="User deleted",
            body=f"User '{user.name}' was deleted.",
            entity_type=models.NotificationEntityTypeEnum.USER,
            entity_id=str(user.id),
            deep_link="/users",
        )
    db.delete(user)
    db.commit()
    background_tasks.add_task(trigger_n8n_event, "user.deleted", serialized_user)


@router.post(
    "/me/avatar",
    response_model=schemas.UserRead,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AvatarUploadPayload"}
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file", "crop"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "crop": {"type": "string"},
                        },
                    }
                },
            }
        }
    },
)
async def upload_current_user_avatar(
    request: Request,
    current_user: models.User = _active_dependency,
    db: Session = _db_dependency,
) -> schemas.UserRead:
    user = db.scalar(
        select(models.User)
        .where(
            models.User.id == current_user.id,
            models.User.tenant_id == current_user.tenant_id,
        )
        .with_for_update()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        from starlette.datastructures import UploadFile

        async with request.form(max_files=1, max_fields=1) as form:
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise HTTPException(
                    status_code=422, detail="An avatar file is required"
                )
            binary = await file.read(max_avatar_bytes() + 1)
            image = load_avatar_image(binary, mime_type=file.content_type)
            try:
                metadata = schemas.AvatarCropMetadata.model_validate_json(
                    form.get("crop", "")
                )
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=422, detail="Invalid avatar crop"
                ) from exc
        set_user_avatar_image(
            db,
            user,
            image=apply_avatar_crop(image, metadata.model_dump()),
            actor=current_user,
        )
    else:
        try:
            payload = schemas.AvatarUploadPayload.model_validate(await request.json())
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422, detail="Invalid avatar upload"
            ) from exc
        set_user_avatar_from_data_url(
            db, user, data_url=payload.data_url, actor=current_user
        )
    db.commit()
    db.refresh(user)
    return _hydrate_user_avatar(user, current_user)


@router.post("/{user_id}/avatar", response_model=schemas.UserRead)
def upload_avatar_for_user(
    user_id: str,
    payload: schemas.AvatarUploadPayload,
    current_user: models.User = _active_dependency,
    db: Session = _db_dependency,
) -> schemas.UserRead:
    stmt = (
        select(models.User)
        .options(selectinload(models.User.avatar_asset))
        .where(
            models.User.id == user_id, models.User.tenant_id == current_user.tenant_id
        )
        .with_for_update()
    )
    user = db.execute(stmt).scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    _ensure_avatar_permission(current_user, user)
    set_user_avatar_from_data_url(
        db, user, data_url=payload.data_url, actor=current_user
    )

    db.commit()
    db.refresh(user)
    return _hydrate_user_avatar(user, current_user)


@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_current_user_password(
    payload: schemas.UserPasswordChange,
    current_user: models.User = _active_dependency,
    db: Session = _db_dependency,
) -> None:
    user = db.scalar(
        select(models.User)
        .where(
            models.User.id == current_user.id,
            models.User.tenant_id == current_user.tenant_id,
        )
        .with_for_update()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect password"
        )

    user.hashed_password = hash_password(payload.new_password)
    db.commit()


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_user_password(
    user_id: str,
    payload: schemas.UserResetPassword,
    current_user: models.User = _admin_dependency,
    db: Session = _db_dependency,
) -> None:
    if current_user.role not in {models.RoleEnum.ADMIN, models.RoleEnum.OWNER}:
        raise HTTPException(
            status_code=403, detail="Password resets require administrator access"
        )
    user = db.scalar(
        select(models.User)
        .where(
            models.User.id == user_id, models.User.tenant_id == current_user.tenant_id
        )
        .with_for_update()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if (
        user.role == models.RoleEnum.OWNER
        and current_user.role != models.RoleEnum.OWNER
    ):
        raise HTTPException(
            status_code=403, detail="Only an owner can reset an owner password"
        )
    user.hashed_password = hash_password(payload.new_password)
    db.commit()


@router.get(
    "/by-employer-id/{employer_id}",
    response_model=schemas.UserRead,
    response_model_exclude_unset=True,
)
def get_user_by_employer_id(
    employer_id: str,
    db: Session = _db_dependency,
    current_user: models.User = _active_dependency,
) -> schemas.UserRead:
    user = db.execute(
        select(models.User).where(
            models.User.employer_id == employer_id,
            models.User.tenant_id == current_user.tenant_id,
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return _hydrate_user_avatar(user, current_user)
