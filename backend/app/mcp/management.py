"""Tenant-scoped management of the approved isolated authority store."""
from sqlalchemy import select, func, and_, or_
from fastapi import HTTPException

from . import authority as a
from .models import Audit, Grant, Policy
from .models import Client
from ..models import User, UserStatusEnum
from ..session_models import AuthSession


def status(db, grant):
    if grant.revoked_at: return 'revoked'
    if grant.expires_at <= a.now(): return 'expired'
    try:
        return 'active' if a.grant_authority(db, grant.id).tools else 'blocked'
    except HTTPException:
        return 'blocked'


def snapshot(db, user, base):
    cfg = a.configuration()
    policy = db.get(Policy, user.tenant_id, populate_existing=True)
    if policy is not None and not a.policy_valid(policy):
        raise HTTPException(503, 'MCP policy requires administrator repair')
    allowed = policy.allowed_tools if policy else []
    effective = bool(policy and policy.enabled and not policy.emergency_disabled)
    base['configuration'] = dict(available=True, persisted=policy is not None, blocker='',
        enabled=bool(policy and policy.enabled), read_only=True, allowed_tool_ids=allowed,
        allowed_roles=policy.allowed_roles if policy else [], emergency_disabled=bool(policy and policy.emergency_disabled),
        revision=policy.revision if policy else 0, isolated=True)
    # This is durable grant status, not a count of open network sockets.
    grants = db.scalars(select(Grant).where(Grant.tenant_id == user.tenant_id)
        .order_by(Grant.created_at.desc()).limit(50)).all()
    states = [(grant, status(db, grant)) for grant in grants]
    total = db.scalar(select(func.count()).select_from(Grant).where(Grant.tenant_id == user.tenant_id))
    active = 0
    if effective and allowed:
        scopes = {a.TOOLS[tool] for tool in allowed}
        active = db.scalar(select(func.count()).select_from(Grant).join(User, User.id == Grant.user_id)
            .join(AuthSession, AuthSession.id == Grant.session_id).join(Client, Client.id == Grant.client_id)
            .where(Grant.tenant_id == user.tenant_id, Grant.revoked_at.is_(None), Grant.expires_at > a.now(),
                User.tenant_id == Grant.tenant_id, User.status == UserStatusEnum.ACTIVE,
                User.role.in_(policy.allowed_roles), User.auth_epoch == Grant.auth_epoch,
                AuthSession.auth_epoch == User.auth_epoch, AuthSession.user_id == User.id,
                AuthSession.tenant_id == Grant.tenant_id, AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > a.now(), Client.enabled.is_(True),
                or_(*(and_(func.strpos(' ' + Grant.scopes + ' ', ' ' + scope + ' ') > 0,
                           func.strpos(' ' + Client.scopes + ' ', ' ' + scope + ' ') > 0) for scope in scopes))))
    base['connections'] = dict(available=True, reason='Isolated OAuth grants; external production integrations remain unavailable.',
        items=[dict(id=grant.id, client_id=grant.client_id, user_id=grant.user_id, scopes=grant.scopes.split(),
                    status=state, created_at=grant.created_at.isoformat(), expires_at=grant.expires_at.isoformat(),
                    revoked_at=grant.revoked_at.isoformat() if grant.revoked_at else None)
               for grant, state in states], total=total)
    base['overview'].update(service_status='isolated_configured', enabled_tools=len(allowed) if effective else 0,
        active_connections=active,
        security_mode='Read-only / isolated OAuth', endpoint=cfg.resource)
    for tool in base['tools']:
        tool.update(enabled=tool['id'] in allowed, available=effective and tool['id'] in allowed)
    base['security'].update(mcp_authentication='Configured for isolated OAuth only',
        oauth_delegation='Authorization code + S256, consent and user-bound REST delegation (isolated)',
        credential_handling='Only credential hashes persisted; token values excluded from management',
        remote_connections='External production connections unavailable')
    events = db.scalars(select(Audit).where(Audit.tenant_id == user.tenant_id)
        .order_by(Audit.occurred_at.desc()).limit(50)).all()
    base['activity'] = dict(available=True, reason='Recent tenant OAuth and delegation events; delegation issuance does not imply tool success.',
        items=[dict(id=item.id, event=item.event, outcome=item.outcome, tool_id=item.tool_id,
                    grant_id=item.grant_id, correlation_id=item.correlation_id,
                    occurred_at=item.occurred_at.isoformat()) for item in events])
    return base


def update(db, user, payload):
    a.configuration()
    # Serialize the first insert as well as later updates and emergency stops.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(user.tenant_id), 0))))
    row = db.scalar(select(Policy).where(Policy.tenant_id == user.tenant_id).with_for_update()
                    .execution_options(populate_existing=True))
    if payload.expected_revision != (row.revision if row else 0):
        raise HTTPException(409, 'MCP policy changed. Reload before saving.')
    if row and row.emergency_disabled and payload.enabled:
        raise HTTPException(409, 'Emergency lock cannot be cleared by a policy update')
    if row is None:
        row = Policy(tenant_id=user.tenant_id, emergency_disabled=False, revision=0)
        db.add(row)
    row.enabled, row.read_only = payload.enabled, True
    row.allowed_tools, row.allowed_roles = list(payload.allowed_tool_ids), list(payload.allowed_roles)
    row.revision += 1
    row.updated_at, row.updated_by = a.now(), user.id
    a.audit(db, user, 'policy_updated')
    db.commit()
    return {'revision': row.revision, 'saved': True, 'remote_access_enabled': False}


def emergency(db, user):
    a.configuration()
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(user.tenant_id), 0))))
    row = db.scalar(select(Policy).where(Policy.tenant_id == user.tenant_id).with_for_update()
                    .execution_options(populate_existing=True))
    if row is None:
        row = Policy(tenant_id=user.tenant_id, revision=0, read_only=True, allowed_tools=[], allowed_roles=[])
        db.add(row)
    row.enabled, row.emergency_disabled = False, True
    row.revision += 1
    row.updated_at, row.updated_by = a.now(), user.id
    a.audit(db, user, 'emergency_disabled')
    db.commit()
    return {'emergency_disabled': True, 'revision': row.revision}
