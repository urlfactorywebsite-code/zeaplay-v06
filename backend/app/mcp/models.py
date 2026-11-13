"""Phase 4A authority tables; explicit reviewed migration only, never startup DDL."""
from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column

from ..database import Base
from ..models import UTCDateTime
from ..session_models import AuthSession  # registers the existing FK target


class Client(Base):
    __tablename__ = 'mcp_clients'
    __table_args__ = ({'info': {'alembic_only': True}},)
    id = mapped_column(String(128), primary_key=True)
    name = mapped_column(String(128), nullable=False)
    redirect_uris = mapped_column(JSONB, nullable=False)
    scopes = mapped_column(String(128), nullable=False)
    enabled = mapped_column(Boolean, nullable=False, default=False)
    created_at = mapped_column(UTCDateTime(), nullable=False)


class Policy(Base):
    __tablename__ = 'mcp_policies'
    __table_args__ = (CheckConstraint('read_only', name='ck_mcp_policy_read_only'),
                      CheckConstraint('revision > 0', name='ck_mcp_policy_revision'),
                      {'info': {'alembic_only': True}})
    tenant_id = mapped_column(UUID(as_uuid=True), primary_key=True)
    enabled = mapped_column(Boolean, nullable=False, default=False)
    read_only = mapped_column(Boolean, nullable=False, default=True)
    emergency_disabled = mapped_column(Boolean, nullable=False, default=False)
    allowed_tools = mapped_column(JSONB, nullable=False)
    allowed_roles = mapped_column(JSONB, nullable=False)
    revision = mapped_column(Integer, nullable=False)
    updated_by = mapped_column(String(36), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    updated_at = mapped_column(UTCDateTime(), nullable=False)


class Grant(Base):
    __tablename__ = 'mcp_grants'
    __table_args__ = (Index('ix_mcp_grant_tenant_user', 'tenant_id', 'user_id'),
                      CheckConstraint('expires_at > created_at', name='ck_mcp_grant_lifetime'),
                      {'info': {'alembic_only': True}})
    id = mapped_column(String(36), primary_key=True)
    client_id = mapped_column(String(128), ForeignKey('mcp_clients.id', ondelete='RESTRICT'), nullable=False)
    user_id = mapped_column(String(36), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    tenant_id = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id = mapped_column(String(36), ForeignKey('auth_sessions.id', ondelete='RESTRICT'), nullable=False)
    auth_epoch = mapped_column(BigInteger, nullable=False)
    scopes = mapped_column(String(128), nullable=False)
    created_at = mapped_column(UTCDateTime(), nullable=False)
    expires_at = mapped_column(UTCDateTime(), nullable=False)
    revoked_at = mapped_column(UTCDateTime())
    revocation_reason = mapped_column(String(64))


class Authorization(Base):
    __tablename__ = 'mcp_authorizations'
    __table_args__ = (CheckConstraint('expires_at > created_at', name='ck_mcp_authorization_lifetime'),
                      {'info': {'alembic_only': True}})
    id = mapped_column(String(36), primary_key=True)
    client_id = mapped_column(String(128), ForeignKey('mcp_clients.id', ondelete='RESTRICT'), nullable=False)
    redirect_uri = mapped_column(String(512), nullable=False)
    resource = mapped_column(String(512), nullable=False)
    state = mapped_column(String(512), nullable=False)
    scopes = mapped_column(String(128), nullable=False)
    code_challenge = mapped_column(String(43), nullable=False)
    code_challenge_method = mapped_column(String(4), nullable=False)
    browser_digest = mapped_column(String(64), nullable=False, unique=True)
    csrf_digest = mapped_column(String(64))
    user_id = mapped_column(String(36), ForeignKey('users.id', ondelete='RESTRICT'))
    tenant_id = mapped_column(UUID(as_uuid=True))
    session_id = mapped_column(String(36), ForeignKey('auth_sessions.id', ondelete='RESTRICT'))
    grant_id = mapped_column(String(36), ForeignKey('mcp_grants.id', ondelete='RESTRICT'))
    code_digest = mapped_column(String(64), unique=True)
    created_at = mapped_column(UTCDateTime(), nullable=False)
    expires_at = mapped_column(UTCDateTime(), nullable=False)
    code_expires_at = mapped_column(UTCDateTime())
    decided_at = mapped_column(UTCDateTime())
    consumed_at = mapped_column(UTCDateTime())


class Credential(Base):
    __tablename__ = 'mcp_credentials'
    __table_args__ = (CheckConstraint("kind IN ('access','refresh','downstream')", name='ck_mcp_credential_kind'),
                      CheckConstraint("kind <> 'downstream' OR tool_id IS NOT NULL", name='ck_mcp_downstream_tool'),
                      CheckConstraint('expires_at > created_at', name='ck_mcp_credential_lifetime'),
                      Index('ix_mcp_credential_grant', 'grant_id'), {'info': {'alembic_only': True}})
    digest = mapped_column(String(64), primary_key=True)
    grant_id = mapped_column(String(36), ForeignKey('mcp_grants.id', ondelete='RESTRICT'), nullable=False)
    kind = mapped_column(String(16), nullable=False)
    issuer = mapped_column(String(512), nullable=False)
    audience = mapped_column(String(512), nullable=False)
    scopes = mapped_column(String(128), nullable=False)
    tool_id = mapped_column(String(128))
    created_at = mapped_column(UTCDateTime(), nullable=False)
    expires_at = mapped_column(UTCDateTime(), nullable=False)
    consumed_at = mapped_column(UTCDateTime())


class Audit(Base):
    __tablename__ = 'mcp_audit'
    __table_args__ = (Index('ix_mcp_audit_tenant_time', 'tenant_id', 'occurred_at'),
                      {'info': {'alembic_only': True}})
    id = mapped_column(String(36), primary_key=True)
    tenant_id = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id = mapped_column(String(36), ForeignKey('users.id', ondelete='SET NULL'))
    grant_id = mapped_column(String(36), ForeignKey('mcp_grants.id', ondelete='SET NULL'))
    client_id = mapped_column(String(128), ForeignKey('mcp_clients.id', ondelete='SET NULL'))
    tool_id = mapped_column(String(128))
    event = mapped_column(String(64), nullable=False)
    outcome = mapped_column(String(16), nullable=False)
    correlation_id = mapped_column(String(36), nullable=False)
    occurred_at = mapped_column(UTCDateTime(), nullable=False)
