"""Current database authority for OAuth grants and distinct REST delegations."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
from urllib.parse import urlsplit
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import make_url

from ..models import User, UserStatusEnum
from ..session_models import AuthSession
from .models import Audit, Client, Credential, Grant, Policy

SCOPES = frozenset(('tasks:read', 'workload:read'))
TOOLS = {'zeaplay_list_tasks': 'tasks:read', 'zeaplay_get_task': 'tasks:read',
         'zeaplay_list_overdue_tasks': 'tasks:read', 'zeaplay_list_subtasks': 'tasks:read',
         'zeaplay_get_workload_summary': 'workload:read'}


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def identifier():
    return str(uuid.uuid4())


def loopback_origin(value):
    try:
        uri = urlsplit(value)
        if (uri.scheme == 'http' and ipaddress.ip_address(uri.hostname).is_loopback and uri.port
                and not uri.username and not uri.password and not uri.query and not uri.fragment
                and uri.path in ('', '/')):
            return value.rstrip('/')
    except (ValueError, TypeError):
        pass
    raise HTTPException(503, 'Isolated MCP configuration is unavailable')


@dataclass(frozen=True)
class Configuration:
    backend: str
    mcp: str
    frontend: str
    service_secret: str

    @property
    def issuer(self):
        return self.backend + '/mcp-oauth'

    @property
    def resource(self):
        return self.mcp + '/mcp'

    @property
    def rest_audience(self):
        return self.backend + '/mcp-rest'


def configured():
    return os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') == '1'


def configuration():
    if not configured():
        raise HTTPException(503, 'MCP OAuth is not configured')
    secret = os.environ.get('ZEA_MCP_SERVICE_SECRET', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', secret):
        raise HTTPException(503, 'Isolated MCP configuration is unavailable')
    from ..config import get_settings
    target = make_url(get_settings().database_url)
    if (target.host != '127.0.0.1' or target.database != 'zea_phase2b'
            or target.username != 'zea_phase2b'):
        raise HTTPException(503, 'Only owned disposable MCP infrastructure is supported')
    return Configuration(loopback_origin(os.environ.get('ZEA_MCP_BACKEND_ORIGIN', '')),
                         loopback_origin(os.environ.get('ZEA_MCP_RESOURCE_ORIGIN', '')),
                         loopback_origin(os.environ.get('ZEA_MCP_FRONTEND_ORIGIN', '')), secret)


def fail(code=401):
    raise HTTPException(code, 'MCP authority denied', headers={'Cache-Control': 'no-store'})


def policy_valid(policy):
    return (policy is not None and type(policy.enabled) is bool and policy.read_only is True
            and type(policy.emergency_disabled) is bool
            and isinstance(policy.allowed_tools, list) and isinstance(policy.allowed_roles, list)
            and all(isinstance(value, str) for value in policy.allowed_tools + policy.allowed_roles)
            and set(policy.allowed_tools) <= TOOLS.keys()
            and set(policy.allowed_roles) <= {'user', 'manager', 'admin', 'owner'})


def audit(db, user, event, *, grant=None, tool=None, outcome='success'):
    tenant = grant.tenant_id if grant else user.tenant_id
    entry = Audit(id=identifier(), tenant_id=tenant, actor_id=user.id if user.tenant_id == tenant else None,
                  grant_id=grant.id if grant else None, client_id=grant.client_id if grant else None,
                  tool_id=tool, event=event, outcome=outcome, correlation_id=identifier(), occurred_at=now())
    db.add(entry)
    return entry.correlation_id


@dataclass
class Authority:
    user: User
    grant: Grant
    policy: Policy
    scopes: frozenset
    tools: frozenset
    credential: Credential | None = None

    @property
    def id(self):
        return self.user.id


def grant_authority(db, grant_id, cfg=None):
    # One fresh statement binds account, parent session, grant, client and policy.
    row = db.execute(select(Grant, User, AuthSession, Policy, Client)
        .join(User, User.id == Grant.user_id).join(AuthSession, AuthSession.id == Grant.session_id)
        .join(Policy, Policy.tenant_id == Grant.tenant_id).join(Client, Client.id == Grant.client_id)
        .where(Grant.id == grant_id).execution_options(populate_existing=True)).first()
    if not row:
        fail()
    grant, user, session, policy, client = row
    moment = now()
    if (not policy_valid(policy) or not policy.enabled or policy.emergency_disabled or not client.enabled
            or user.status != UserStatusEnum.ACTIVE or user.role.value not in policy.allowed_roles
            or grant.revoked_at is not None or grant.expires_at <= moment
            or user.tenant_id != grant.tenant_id or session.tenant_id != grant.tenant_id
            or session.user_id != user.id or session.revoked_at is not None or session.expires_at <= moment
            or session.auth_epoch != user.auth_epoch or grant.auth_epoch != user.auth_epoch):
        fail()
    scopes = frozenset(grant.scopes.split()) & SCOPES & frozenset(client.scopes.split())
    tools = frozenset(tool for tool in policy.allowed_tools if TOOLS[tool] in scopes)
    return Authority(user, grant, policy, scopes, tools)


def credential_authority(db, raw, kind, cfg=None):
    cfg = cfg or configuration()
    prefix = {'access': 'mcp_at.', 'refresh': 'mcp_rt.', 'downstream': 'mcp_dt.'}[kind]
    if not isinstance(raw, str) or not re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9_-]{43}', raw):
        fail()
    record = db.get(Credential, digest(raw), populate_existing=True)
    audience = cfg.rest_audience if kind == 'downstream' else cfg.resource
    if (not record or record.kind != kind or record.issuer != cfg.issuer or record.audience != audience
            or record.expires_at <= now() or record.consumed_at is not None):
        fail()
    authority = grant_authority(db, record.grant_id, cfg)
    authority.scopes &= frozenset(record.scopes.split())
    authority.tools = frozenset(tool for tool in authority.tools if TOOLS[tool] in authority.scopes)
    if kind == 'downstream' and record.tool_id not in authority.tools:
        fail(403)
    authority.credential = record
    return authority


def issue_credential(db, authority, kind, cfg, *, tool=None):
    lifetime = {'access': 300, 'refresh': 8 * 3600, 'downstream': 30}[kind]
    moment = now()
    expires = min(authority.grant.expires_at, moment + timedelta(seconds=lifetime))
    raw = {'access': 'mcp_at.', 'refresh': 'mcp_rt.', 'downstream': 'mcp_dt.'}[kind] + secrets.token_urlsafe(32)
    scope = TOOLS[tool] if kind == 'downstream' else ' '.join(sorted(authority.scopes))
    db.add(Credential(digest=digest(raw), grant_id=authority.grant.id, kind=kind,
        issuer=cfg.issuer, audience=cfg.rest_audience if kind == 'downstream' else cfg.resource,
        scopes=scope, tool_id=tool, created_at=moment, expires_at=expires))
    return raw, max(0, int((expires - moment).total_seconds()))


def revoke(db, authority, reason='user_revocation'):
    if authority.grant.revoked_at is None:
        authority.grant.revoked_at = now()
        authority.grant.revocation_reason = reason
        audit(db, authority.user, 'grant_revoked', grant=authority.grant)


def downstream_user(db, raw, connection=None):
    authority = credential_authority(db, raw, 'downstream')
    if connection is not None:
        path = connection.url.path.removeprefix('/api')
        pairs = list(connection.query_params.multi_items())
        query = dict(pairs)
        tool = authority.credential.tool_id
        if len(query) != len(pairs) or connection.scope.get('method') != 'GET':
            fail(403)
        allowed = path == '/auth/me' and not query
        if tool in ('zeaplay_list_tasks', 'zeaplay_list_overdue_tasks') and path == '/tasks/page':
            allowed = set(query) <= {'page', 'page_size', 'search', 'status', 'priority', 'quick_filter'}
            allowed &= (query.get('quick_filter') == 'overdue' if tool == 'zeaplay_list_overdue_tasks' else 'quick_filter' not in query)
        if tool == 'zeaplay_get_workload_summary' and path == '/tasks/activity' and not query:
            allowed = True
        if re.fullmatch(r'/tasks/[A-Za-z0-9_-]{1,36}/information', path):
            if tool == 'zeaplay_get_task':
                allowed = query == {'section': 'overview'}
            if tool == 'zeaplay_list_subtasks':
                allowed = set(query) <= {'section', 'page', 'page_size', 'search'} and query.get('section') == 'subtasks'
        if not allowed:
            fail(403)
    return authority.user
