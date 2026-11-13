from datetime import datetime, timedelta, timezone
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import (
    create_presence_token,
    decode_token_claims,
    decode_presence_claims,
    oauth2_scheme,
    hash_password,
    PRESENCE_TOKEN_MINUTES,
    verify_password,
)
from ..dependencies import get_current_active_user, get_current_api_admin
from ..database import get_db
from ..config import get_settings
from ..services import audit_logger, auth_sessions

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _derive_tenant_id(employer_id: Optional[str]) -> uuid.UUID:
    if not employer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="employer_id is required to register a tenant-scoped user",
        )
    try:
        return uuid.UUID(str(employer_id))
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"zea-play-tenant:{employer_id}")


def _build_token_claims(user: models.User) -> dict[str, object]:
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is missing tenant assignment",
        )
    return {
        "tenant_id": str(user.tenant_id),
        "roles": [user.role.value],
    }


@router.post("/register", response_model=schemas.AuthResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: schemas.UserCreate, db: Session = Depends(get_db)) -> schemas.AuthResponse:
    existing_user = db.execute(select(models.User).where(models.User.email == payload.email)).scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    tenant_id = _derive_tenant_id(payload.employer_id)
    # Public registration provisions a new workspace. Joining an existing one
    # uses the authenticated, role-scoped /users API. Serialize the empty-tenant
    # check too: row locks cannot protect a tenant that has no user rows yet.
    from ..services.subtask_rewards import tenant_lock

    with audit_logger._write_savepoint(db):
        tenant_lock(db, tenant_id)
        if db.scalar(select(models.User.id).where(models.User.tenant_id == tenant_id).limit(1)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Use authorized user management to join an existing workspace",
            )
        user = models.User(
            tenant_id=tenant_id,
            name=payload.name,
            email=payload.email,
            hashed_password=hash_password(payload.password),
            role=payload.role,
            status=payload.status,
            department_id=payload.department_id,
            employer_id=payload.employer_id,
        )
        db.add(user)
        db.flush()
    token = auth_sessions.issue_login(db, user)
    db.commit()
    db.refresh(user)

    audit_logger.log_event(
        audit_logger.AuditLogInput(
            tenant_id=user.tenant_id if user else None,
            action="USER_REGISTERED",
            category=models.AuditLogCategoryEnum.USER,
            actor_id=str(user.id),
            actor_role=user.role.value if user.role else None,
            target_user_id=str(user.id),
            entity_type="user",
            entity_id=str(user.id),
            source=models.AuditLogSourceEnum.API,
            metadata={"email": user.email},
        )
    )

    return schemas.AuthResponse(token=token, user=user)


async def _extract_credentials(request: Request) -> tuple[str, str]:
    content_type = (request.headers.get("content-type") or "").lower()
    username: Optional[str] = None
    password: Optional[str] = None

    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        username = form.get("username") or form.get("email")
        password = form.get("password")
    else:
        try:
            body = await request.json()
        except Exception:  # JSON decode error or empty body
            body = {}
        if isinstance(body, dict):
            username = body.get("email") or body.get("username")
            password = body.get("password")

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Email/username and password are required",
        )

    return username, password


@router.post("/login", response_model=schemas.AuthResponse)
async def login(request: Request, db: Session = Depends(get_db)) -> schemas.AuthResponse:
    username, password = await _extract_credentials(request)
    user = db.execute(select(models.User).where(models.User.email == username).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        audit_logger.log_event(
            audit_logger.AuditLogInput(
                tenant_id=user.tenant_id if user else None,
                action="USER_LOGIN_FAILED",
                category=models.AuditLogCategoryEnum.SECURITY,
                actor_id=str(user.id) if user else None,
                actor_role=user.role.value if user and user.role else None,
                target_user_id=str(user.id) if user else None,
                entity_type="user",
                entity_id=str(user.id) if user else None,
                source=models.AuditLogSourceEnum.MANUAL,
                severity=models.AuditLogSeverityEnum.WARNING,
                status=models.AuditLogStatusEnum.FAILED,
                reason="Invalid credentials",
                metadata={"email": username},
                request=request,
            )
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.status != models.UserStatusEnum.ACTIVE:
        audit_logger.log_event(
            audit_logger.AuditLogInput(
                tenant_id=user.tenant_id if user else None,
                action="USER_LOGIN_BLOCKED",
                category=models.AuditLogCategoryEnum.SECURITY,
                actor_id=str(user.id),
                actor_role=user.role.value if user.role else None,
                target_user_id=str(user.id),
                entity_type="user",
                entity_id=str(user.id),
                source=models.AuditLogSourceEnum.MANUAL,
                severity=models.AuditLogSeverityEnum.WARNING,
                status=models.AuditLogStatusEnum.FAILED,
                reason="Account deactivated",
                request=request,
            )
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is deactivated")

    token = auth_sessions.issue_login(db, user)
    db.commit()
    audit_logger.log_event(
        audit_logger.AuditLogInput(
            tenant_id=user.tenant_id if user else None,
            action="USER_LOGIN",
            category=models.AuditLogCategoryEnum.USER,
            actor_id=str(user.id),
            actor_role=user.role.value if user.role else None,
            target_user_id=str(user.id),
            entity_type="user",
            entity_id=str(user.id),
            source=models.AuditLogSourceEnum.MANUAL,
            request=request,
        )
    )
    return schemas.AuthResponse(token=token, user=user)


@router.post("/refresh", response_model=schemas.Token)
def refresh_token(
    payload: schemas.RefreshRequest,
    db: Session = Depends(get_db),
) -> schemas.Token:
    return auth_sessions.rotate(db, payload.refresh_token)


@router.get("/me", response_model=schemas.UserRead)
def get_me(current_user=Depends(get_current_active_user)):
    from .users import _hydrate_user_avatar
    return _hydrate_user_avatar(current_user)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    payload: schemas.LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Mock password reset - in production integrate with email service."""
    user = db.execute(select(models.User).where(models.User.email == payload.email)).scalar_one_or_none()
    # Intentionally do not reveal whether user exists
    if user and user.status == models.UserStatusEnum.ACTIVE:
        # TODO: integrate with email service
        pass
    audit_logger.log_event(
        audit_logger.AuditLogInput(
            tenant_id=user.tenant_id if user else None,
            action="USER_PASSWORD_RESET_REQUESTED",
            category=models.AuditLogCategoryEnum.USER,
            actor_id=str(user.id) if user else None,
            actor_role=user.role.value if user and user.role else None,
            target_user_id=str(user.id) if user else None,
            entity_type="user",
            entity_id=str(user.id) if user else None,
            source=models.AuditLogSourceEnum.MANUAL,
            metadata={"email": payload.email},
            request=request,
        )
    )
    return {"message": "If an account exists, reset instructions have been sent."}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    credential: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> None:
    claims = decode_token_claims(credential)
    auth_sessions.revoke_session(db, claims)
    db.commit()
    audit_logger.log_event(
        audit_logger.AuditLogInput(
            tenant_id=current_user.tenant_id,
            action="USER_LOGOUT",
            category=models.AuditLogCategoryEnum.USER,
            actor_id=str(current_user.id),
            actor_role=current_user.role.value if current_user.role else None,
            target_user_id=str(current_user.id),
            entity_type="user",
            entity_id=str(current_user.id),
            source=models.AuditLogSourceEnum.MANUAL,
            request=request,
        )
    )


@router.post("/generate-token", response_model=schemas.TokenMintResponse)
def generate_scoped_token(
    payload: schemas.TokenMintRequest,
    current_user: models.User = Depends(get_current_api_admin),
    credential: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> schemas.TokenMintResponse:
    """Issue a separately revocable API session with the requested lifetime."""
    normalized_scopes = sorted(set(payload.scopes))
    expires_minutes = payload.expires_in_minutes or settings.access_token_expire_minutes
    auth_sessions.lock_user(db, current_user.id)
    current_user, _ = auth_sessions.validate_session(db, decode_token_claims(credential))
    access_token, session = auth_sessions.issue_api(db, current_user, minutes=expires_minutes, scopes=normalized_scopes)
    issued_at, expires_at = session.created_at, session.expires_at
    db.commit()
    return schemas.TokenMintResponse(
        access_token=access_token,
        token_type="bearer",
        scopes=normalized_scopes,
        issued_at=issued_at,
        expires_at=expires_at,
        subject=current_user.id,
        label=payload.label or current_user.name,
    )


@router.get("/presence-token", response_model=schemas.TokenMintResponse)
def issue_presence_token(
    current_user: models.User = Depends(get_current_active_user),
    credential: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> schemas.TokenMintResponse:
    """Bind presence to the same revocable session as the requesting access JWT."""
    current_user, session = auth_sessions.validate_session(db, decode_token_claims(credential))
    issued_at = datetime.now(timezone.utc)
    expires_at = min(session.expires_at, issued_at + timedelta(minutes=PRESENCE_TOKEN_MINUTES))
    access_token = create_presence_token(current_user.id, tenant_id=str(current_user.tenant_id),
        roles=[current_user.role.value], sid=session.id, auth_epoch=session.auth_epoch,
        jti=str(uuid.uuid4()), expires_at=expires_at)
    return schemas.TokenMintResponse(
        access_token=access_token,
        token_type="bearer",
        scopes=["presence"],
        issued_at=issued_at,
        expires_at=expires_at,
        subject=current_user.id,
        label="Presence socket",
    )


@router.post("/presence/validate", status_code=status.HTTP_204_NO_CONTENT)
def validate_presence_session(credential: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Read-only presence admission/revalidation. A presence JWT grants only this check."""
    try:
        claims = decode_presence_claims(credential)
    except ValueError as exc:
        raise auth_sessions.denied() from exc
    auth_sessions.validate_session(db, claims)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(current_user: models.User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    auth_sessions.invalidate_user(db, current_user.id)
    db.commit()
