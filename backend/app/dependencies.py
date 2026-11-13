"""Common FastAPI dependencies."""

import uuid
import os
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from .auth import decode_token_claims, oauth2_scheme
from .config import get_settings
from .database import get_db
from .models import RoleEnum, User, UserStatusEnum
from .permissions import API_ADMIN_ROLES
from .services.auth_sessions import validate_session

settings = get_settings()


def _decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = decode_token_claims(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return payload


def _extract_user_id(payload: dict[str, Any]) -> str:
    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return str(user_id)


async def credential_for_request(connection: HTTPConnection, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    if token.startswith('mcp_dt.'):
        if os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') != '1':
            raise HTTPException(401, 'Invalid or expired credential')
        from .mcp.authority import downstream_user
        downstream_user(db, token, connection)
    return token


async def get_current_user(
    token: str = Depends(credential_for_request),
    db: Session = Depends(get_db),
) -> User:
    """Return the authenticated user from the JWT bearer token."""
    if token.startswith('mcp_dt.'):
        if os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') != '1':
            raise HTTPException(401, 'Invalid or expired credential')
        from .mcp.authority import downstream_user
        user = downstream_user(db, token)
    else:
        payload = _decode_access_token(token)
        user, _ = validate_session(db, payload)
    from .services.audit_security import bind_principal
    bind_principal(user)
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.status != UserStatusEnum.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    return current_user


async def get_current_admin(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.role not in {RoleEnum.ADMIN, RoleEnum.MANAGER, RoleEnum.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user


async def get_current_owner(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.role != RoleEnum.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner privileges required")
    return current_user


async def get_current_api_admin(current_user: User = Depends(get_current_active_user)) -> User:
    # get_current_admin intentionally includes Managers for other application
    # operations. Credential administration is a narrower capability.
    if current_user.role not in API_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="API administration requires Owner or Admin access")
    return current_user


def get_tenant_id(current_user: User = Depends(get_current_active_user)) -> uuid.UUID:
    return current_user.tenant_id


def require_roles(*required_roles: str):
    required = {role for role in required_roles if role}

    def _dependency(current_user: User = Depends(get_current_active_user)) -> list[str]:
        # JWT role claims can outlive a demotion. The database role is authority.
        roles = [current_user.role.value]
        if required and not (required & set(roles)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role privileges",
            )
        return roles

    return _dependency


def apply_tenant_filter(query, tenant_id: uuid.UUID):
    conditions = []
    if hasattr(query, "column_descriptions"):
        for desc in query.column_descriptions:
            entity = desc.get("entity")
            if entity is not None and hasattr(entity, "tenant_id"):
                conditions.append(entity.tenant_id == tenant_id)
    if not conditions:
        raise ValueError("Query does not include a tenant-aware entity")

    if hasattr(query, "where"):
        return query.where(*conditions)
    return query.filter(*conditions)
