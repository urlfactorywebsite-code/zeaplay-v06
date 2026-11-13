"""PostgreSQL is authority; no cached permission or revocation decisions.

Lock order for writers: user, session, refresh row. Callers commit issuance and
revocation before returning credentials. A consumed-token replay commits the
family revocation before raising 401; never wrap rotate() in an outer savepoint.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import uuid

from fastapi import HTTPException
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.orm import Session

from ..auth import create_access_token, create_refresh_token, decode_token_claims
from ..config import get_settings
from ..models import User, UserStatusEnum
from ..schemas import Token, TokenPayload
from ..session_models import AuthRefreshToken, AuthSession

settings = get_settings()


def require_session_schema(engine):
    """Read-only startup gate: fail instead of silently creating partial auth state."""
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Durable authentication requires migrated PostgreSQL")
    with engine.connect() as connection:
        inspector = inspect(connection)
        if (not {"auth_sessions", "auth_refresh_tokens", "users"}.issubset(inspector.get_table_names())
                or "auth_epoch" not in {c["name"] for c in inspector.get_columns("users")}
                or not connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE "
                    "tgrelid = 'users'::regclass AND tgname = 'zea_user_auth_invalidation' "
                    "AND tgenabled IN ('O', 'A'))"))):
            raise RuntimeError("Apply Alembic l2b4d6f8a0c2 before starting authentication")


def now():
    return datetime.now(timezone.utc)


def denied():
    return HTTPException(401, "Invalid or expired session", headers={"WWW-Authenticate": "Bearer"})


def session_claims_valid(claims):
    try:
        for key in ("sub", "sid", "jti", "tenant_id"):
            value = claims[key]
            if not isinstance(value, str) or not value or value.strip() != value:
                return False
            if key != "sub":
                if str(uuid.UUID(value)) != value.lower():
                    return False
        return (len(claims["sub"]) <= 36
                and claims.get("user_id", claims["sub"]) == claims["sub"]
                and type(claims["auth_epoch"]) is int and 0 <= claims["auth_epoch"] <= 9007199254740991
                and type(claims["iat"]) is int and 0 <= claims["iat"] <= int(now().timestamp())
                and type(claims["exp"]) is int and int(now().timestamp()) < claims["exp"] <= 9007199254740991
                and claims["exp"] > claims["iat"])
    except (KeyError, ValueError, TypeError):
        return False


def validate_session(db: Session, claims: dict):
    """Single-statement current snapshot even with an ORM identity map present."""
    if not session_claims_valid(claims):
        raise denied()
    row = db.execute(select(User, AuthSession).join(AuthSession, AuthSession.user_id == User.id)
                     .where(User.id == claims["sub"], AuthSession.id == claims["sid"])
                     .execution_options(populate_existing=True)).first()
    if not row:
        raise denied()
    user, session = row
    if (user.status != UserStatusEnum.ACTIVE or session.revoked_at is not None
            or session.expires_at <= now() or user.auth_epoch != session.auth_epoch
            or claims["auth_epoch"] != session.auth_epoch
            or uuid.UUID(claims["tenant_id"]) != session.tenant_id
            or user.tenant_id != session.tenant_id
            or claims["exp"] > int(session.expires_at.timestamp())):
        raise denied()
    return user, session


def lock_user(db, user_id):
    user = db.scalar(select(User).where(User.id == user_id).with_for_update()
                     .execution_options(populate_existing=True))
    if not user:
        raise denied()
    return user


def claims_for(user, session, token_id=None):
    return {"tenant_id": str(session.tenant_id), "roles": [user.role.value],
            "sid": session.id, "jti": token_id or str(uuid.uuid4()),
            "auth_epoch": session.auth_epoch, "iat": int(now().timestamp())}


def _access(user, session, *, scopes=None, minutes=None):
    expiry = min(session.expires_at, now() + timedelta(minutes=minutes or settings.access_token_expire_minutes))
    return create_access_token(user.id, scopes=scopes,
                               extra_claims={**claims_for(user, session), "exp": int(expiry.timestamp())})


def _pair(db, user, session):
    token_id = str(uuid.uuid4())
    refresh = create_refresh_token(user.id, extra_claims={
        **claims_for(user, session, token_id), "exp": int(session.expires_at.timestamp())})
    db.add(AuthRefreshToken(id=token_id, session_id=session.id,
                           digest=hashlib.sha256(refresh.encode()).hexdigest(),
                           created_at=now(), expires_at=session.expires_at))
    return Token(access_token=_access(user, session), refresh_token=refresh), token_id


def _new_session(db, user, minutes, kind):
    # Caller holds the user lock (or owns the new, uncommitted user row).
    if user.status != UserStatusEnum.ACTIVE or not user.tenant_id:
        raise denied()
    created = now().replace(microsecond=0)
    session = AuthSession(id=str(uuid.uuid4()), user_id=user.id, tenant_id=user.tenant_id,
                          auth_epoch=user.auth_epoch, kind=kind, created_at=created,
                          expires_at=created + timedelta(minutes=minutes), last_used_at=created)
    db.add(session)
    db.flush()
    return session


def issue_login(db, user):
    session = _new_session(db, user, settings.refresh_token_expire_minutes, "login")
    pair, _ = _pair(db, user, session)
    db.flush()
    return pair


def issue_api(db, user, *, minutes, scopes):
    user = lock_user(db, user.id)
    session = _new_session(db, user, minutes, "api")
    return _access(user, session, scopes=scopes, minutes=minutes), session


def revoke(session, reason):
    if session.revoked_at is None:
        session.revoked_at = now()
        session.revocation_reason = reason


def revoke_session(db, claims, reason="logout"):
    lock_user(db, claims["sub"])
    session = db.scalar(select(AuthSession).where(AuthSession.id == claims["sid"],
                        AuthSession.user_id == claims["sub"]).with_for_update()
                        .execution_options(populate_existing=True))
    if not session:
        raise denied()
    revoke(session, reason)


def invalidate_user(db, user_id):
    """Explicit security invalidation; PG trigger revokes every session atomically."""
    lock_user(db, user_id)
    db.execute(update(User).where(User.id == user_id).values(auth_epoch=User.auth_epoch + 1))


def rotate(db, credential):
    try:
        claims = decode_token_claims(credential, refresh=True)
        TokenPayload.model_validate(claims)
    except ValueError as exc:
        raise denied() from exc
    if not session_claims_valid(claims):
        raise denied()
    lock_user(db, claims["sub"])
    # Serialize all family writers before validating a fresh snapshot.
    db.scalar(select(AuthSession).where(AuthSession.id == claims["sid"])
              .with_for_update().execution_options(populate_existing=True))
    user, session = validate_session(db, claims)
    record = db.scalar(select(AuthRefreshToken).where(AuthRefreshToken.id == claims["jti"],
                       AuthRefreshToken.session_id == session.id).with_for_update()
                       .execution_options(populate_existing=True))
    digest = hashlib.sha256(credential.encode()).hexdigest()
    if not record or not hmac.compare_digest(record.digest, digest) or record.expires_at <= now():
        raise denied()
    if record.consumed_at is not None:
        revoke(session, "refresh_reuse")
        db.commit()  # The intentional 401 must not roll back security state.
        raise denied()
    if session.kind != "login":
        raise denied()
    pair, successor = _pair(db, user, session)
    record.consumed_at = now()
    record.replaced_by = successor
    session.last_used_at = now()
    db.commit()
    return pair


def cleanup_expired(db, *, batch_size=500):
    """Operator/job primitive; no background startup mutation. Caller commits.

    Retain the entire family through absolute expiry plus 30 days. Never prune
    users.auth_epoch. SKIP LOCKED permits concurrent bounded cleanup workers.
    """
    ids = select(AuthSession.id).where(AuthSession.expires_at < now() - timedelta(days=30)).order_by(
        AuthSession.expires_at, AuthSession.id).limit(min(max(batch_size, 1), 1000)).with_for_update(skip_locked=True)
    return db.execute(delete(AuthSession).where(AuthSession.id.in_(ids))).rowcount
