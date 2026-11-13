"""Durable authentication state. Only Alembic provisions these tables in production."""
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column

from .database import Base
from .models import UTCDateTime


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("auth_epoch >= 0", name="ck_auth_sessions_epoch"),
        CheckConstraint("expires_at > created_at", name="ck_auth_sessions_lifetime"),
        Index("ix_auth_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_auth_sessions_retention", "expires_at", "id"),
        {"info": {"alembic_only": True}},
    )
    # One session is one refresh family; id is also the audit correlation ID.
    id = mapped_column(String(36), primary_key=True)
    user_id = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = mapped_column(UUID(as_uuid=True), nullable=False)
    auth_epoch = mapped_column(BigInteger, nullable=False)
    kind = mapped_column(String(16), nullable=False)
    created_at = mapped_column(UTCDateTime(), nullable=False)
    expires_at = mapped_column(UTCDateTime(), nullable=False)
    last_used_at = mapped_column(UTCDateTime(), nullable=False)
    revoked_at = mapped_column(UTCDateTime())
    revocation_reason = mapped_column(String(64))


class AuthRefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (
        Index("ix_auth_refresh_session", "session_id"),
        {"info": {"alembic_only": True}},
    )
    id = mapped_column(String(36), primary_key=True)
    session_id = mapped_column(String(36), ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False)
    digest = mapped_column(String(64), unique=True, nullable=False)
    created_at = mapped_column(UTCDateTime(), nullable=False)
    expires_at = mapped_column(UTCDateTime(), nullable=False)
    consumed_at = mapped_column(UTCDateTime())
    # Correlation links, not an FK: retain history until the whole family expires.
    replaced_by = mapped_column(String(36))
