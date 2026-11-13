"""Isolated OAuth code/consent/token authority; no legacy password-grant reuse."""
from datetime import timedelta
import hmac
import ipaddress
import json
import re
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit

from authlib.oauth2.rfc6749.errors import OAuth2Error
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select

from ..database import get_db
from ..dependencies import get_current_active_user, _decode_access_token
from ..models import RoleEnum, User
from ..session_models import AuthSession
from . import authority as a
from .models import Authorization, Credential, Grant, Policy
from .provider import Request as OAuthRequest, Server


async def guard(request: Request):
    cfg = a.configuration()
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = False
    if (not local or request.headers.get('host') != urlsplit(cfg.backend).netloc
            or len(request.headers.getlist('host')) != 1 or len(request.headers.getlist('origin')) > 1
            or len(request.headers.getlist('authorization')) > 1
            or request.headers.get('origin') not in (None, cfg.frontend, cfg.backend)
            or len(request.url.query) > 8192):
        a.fail(403)
    return cfg


class SafeRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                return error()
            except HTTPException as exc:
                if exc.status_code in (400, 413):
                    return error(status=exc.status_code)
                exc.headers = {**(exc.headers or {}), 'Cache-Control': 'no-store'}
                raise
            response.headers['Cache-Control'] = 'no-store'
            return response
        return safe


router = APIRouter(prefix='/mcp-oauth', tags=['mcp-oauth'], dependencies=[Depends(guard)], route_class=SafeRoute)
discovery = APIRouter(tags=['mcp-oauth-discovery'], dependencies=[Depends(guard)], route_class=SafeRoute)


def error(code='invalid_request', status=400):
    return JSONResponse({'error': code, 'error_description': 'OAuth request rejected'}, status_code=status,
                        headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


async def data(request, allowed, *, form=False):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 32768:
            raise HTTPException(413, 'OAuth request too large')
    try:
        if form:
            if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                raise ValueError()
            pairs = parse_qsl(raw.decode('ascii'), keep_blank_values=True, max_num_fields=16)
            value = dict(pairs)
            if len(value) != len(pairs) or any(len(item) > 2048 for item in value.values()):
                raise ValueError()
        else:
            pairs = json.loads(raw, object_pairs_hook=lambda pairs: pairs)
            if not isinstance(pairs, list) or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs):
                raise ValueError()
            value = dict(pairs)
            if len(value) != len(pairs):
                raise ValueError()
        if not isinstance(value, dict) or not set(value) <= allowed:
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise HTTPException(400, 'Invalid OAuth request') from None


def auth_data(row):
    return {'response_type': 'code', 'client_id': row.client_id, 'redirect_uri': row.redirect_uri,
            'resource': row.resource, 'scope': row.scopes, 'state': row.state,
            'code_challenge': row.code_challenge, 'code_challenge_method': 'S256'}


@discovery.get('/.well-known/oauth-authorization-server/mcp-oauth')
@router.get('/.well-known/oauth-authorization-server')
def metadata():
    cfg = a.configuration()
    return JSONResponse({'issuer': cfg.issuer, 'authorization_endpoint': cfg.issuer + '/authorize',
        'token_endpoint': cfg.issuer + '/token', 'revocation_endpoint': cfg.issuer + '/revoke',
        'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported': ['S256'], 'token_endpoint_auth_methods_supported': ['none'],
        'authorization_response_iss_parameter_supported': True, 'scopes_supported': sorted(a.SCOPES)},
        headers={'Cache-Control': 'no-store'})


@router.get('/authorize')
def authorize(request: Request, db=Depends(get_db)):
    cfg = a.configuration()
    fields = dict(request.query_params)
    if (len(fields) != len(request.query_params.multi_items()) or set(fields) != {
            'client_id', 'response_type', 'redirect_uri', 'scope', 'state', 'resource', 'code_challenge', 'code_challenge_method'}
            or fields.get('resource') != cfg.resource or not re.fullmatch(r'[A-Za-z0-9_-]{32,512}', fields.get('state', ''))
            or not fields.get('scope') or not set(fields['scope'].split()) <= a.SCOPES):
        return error()
    oauth = OAuthRequest('GET', cfg.issuer + '/authorize', fields)
    server = Server(db, cfg)
    try:
        server.get_consent_grant(oauth)
    except OAuth2Error:
        # Never redirect an unvalidated authorization request.
        return error()
    client = server.query_client(fields['client_id'])
    if client is None or not set(fields['scope'].split()) <= set(client.row.scopes.split()):
        return error('invalid_scope')
    browser = secrets.token_urlsafe(32)
    row = Authorization(id=a.identifier(), client_id=fields['client_id'], redirect_uri=fields['redirect_uri'],
        resource=cfg.resource, state=fields['state'], scopes=' '.join(sorted(set(fields['scope'].split()))),
        code_challenge=fields['code_challenge'], code_challenge_method='S256', browser_digest=a.digest(browser),
        created_at=a.now(), expires_at=a.now() + timedelta(minutes=5))
    db.add(row)
    db.commit()
    response = RedirectResponse(cfg.frontend + '/#/mcp/consent?' + urlencode({'request': row.id}), status_code=302,
        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
    response.set_cookie('mcp_auth_' + row.id.replace('-', ''), browser, httponly=True,
                        secure=False, samesite='lax', max_age=300, path='/')
    return response


def pending(db, request, request_id, user):
    if not re.fullmatch(r'[a-f0-9-]{36}', request_id):
        a.fail(404)
    row = db.scalar(select(Authorization).where(Authorization.id == request_id).with_for_update()
                    .execution_options(populate_existing=True))
    cookie = request.cookies.get('mcp_auth_' + request_id.replace('-', ''), '')
    if (not row or not re.fullmatch(r'[A-Za-z0-9_-]{43}', cookie)
            or not hmac.compare_digest(row.browser_digest, a.digest(cookie))
            or row.expires_at <= a.now() or row.decided_at is not None):
        a.fail(403)
    fields = request.headers.get('authorization', '').split()
    bearer = fields[1] if len(fields) == 2 else ''
    claims = _decode_access_token(bearer)
    session = db.get(AuthSession, claims['sid'], populate_existing=True)
    if session is None or session.kind != 'login':
        a.fail(403)
    if row.user_id and (row.user_id != user.id or row.tenant_id != user.tenant_id or row.session_id != session.id):
        a.fail(403)
    policy = db.get(Policy, user.tenant_id, populate_existing=True)
    if (not a.policy_valid(policy) or not policy.enabled or policy.emergency_disabled
            or user.role.value not in policy.allowed_roles):
        a.fail(403)
    scopes = {a.TOOLS[tool] for tool in policy.allowed_tools}
    if not set(row.scopes.split()) <= scopes:
        a.fail(403)
    row.user_id, row.tenant_id, row.session_id = user.id, user.tenant_id, session.id
    return row, session


@router.post('/requests/{request_id}/preview')
def preview(request_id: str, request: Request, db=Depends(get_db), user=Depends(get_current_active_user)):
    row, _ = pending(db, request, request_id, user)
    csrf = secrets.token_urlsafe(32)
    row.csrf_digest = a.digest(csrf)
    client = Server(db, a.configuration()).query_client(row.client_id)
    if client is None:
        a.fail(403)
    db.commit()
    return JSONResponse({'request_id': row.id, 'client_name': client.row.name, 'tenant_context': str(user.tenant_id),
        'scopes': row.scopes.split(), 'expires_at': row.expires_at.isoformat(), 'csrf': csrf,
        'tools': [tool for tool, scope in a.TOOLS.items() if scope in row.scopes.split()
                  and tool in db.get(Policy, user.tenant_id).allowed_tools]},
        headers={'Cache-Control': 'no-store'})


@router.post('/requests/{request_id}/decision')
async def consent(request_id: str, request: Request, db=Depends(get_db), user=Depends(get_current_active_user)):
    body = await data(request, {'approve', 'csrf'})
    row, session = pending(db, request, request_id, user)
    csrf = body.get('csrf', '')
    if (type(body.get('approve')) is not bool or not isinstance(csrf, str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{43}', csrf) or not row.csrf_digest
            or not hmac.compare_digest(row.csrf_digest, a.digest(csrf))):
        a.fail(403)
    cfg = a.configuration()
    server = Server(db, cfg, row)
    oauth = OAuthRequest('GET', cfg.issuer + '/authorize', auth_data(row))
    try:
        grant_handler = server.get_consent_grant(oauth)
    except OAuth2Error:
        return error()
    authority = None
    if body['approve']:
        grant = Grant(id=a.identifier(), client_id=row.client_id, user_id=user.id, tenant_id=user.tenant_id,
            session_id=session.id, auth_epoch=user.auth_epoch, scopes=row.scopes, created_at=a.now(),
            expires_at=min(session.expires_at, a.now() + timedelta(hours=8)))
        db.add(grant)
        db.flush()
        row.grant_id = grant.id
        authority = a.grant_authority(db, grant.id, cfg)
    response = server.create_authorization_response(oauth, grant_user=authority, grant=grant_handler)
    if response.status_code != 302 or not response.headers.get('location'):
        db.rollback()
        return error()
    row.decided_at = row.decided_at or a.now()
    a.audit(db, user, 'consent_approved' if authority else 'consent_denied', grant=authority.grant if authority else None)
    db.commit()
    result = JSONResponse({'redirect_uri': response.headers['location']}, headers={'Cache-Control': 'no-store'})
    result.delete_cookie('mcp_auth_' + request_id.replace('-', ''), path='/')
    return result


@router.post('/token')
async def token(request: Request, db=Depends(get_db)):
    cfg = a.configuration()
    fields = await data(request, {'grant_type', 'client_id', 'code', 'code_verifier', 'redirect_uri', 'resource', 'refresh_token', 'scope'}, form=True)
    if fields.get('resource') != cfg.resource or 'authorization' in request.headers:
        return error('invalid_target')
    oauth = OAuthRequest('POST', cfg.issuer + '/token', fields)
    server = Server(db, cfg)
    response = server.create_token_response(oauth)
    if response.status_code == 200:
        db.commit()
    else:
        db.rollback()
    return response


@router.post('/revoke')
async def revoke_token(request: Request, db=Depends(get_db)):
    fields = await data(request, {'token', 'client_id', 'token_type_hint'}, form=True)
    raw = fields.get('token', '')
    cfg = a.configuration()
    # Known credential possession permits revocation even after policy disable
    # or expiry. An inactive policy must never turn a disconnect into a no-op.
    if isinstance(raw, str) and re.fullmatch(r'mcp_(at|rt)\.[A-Za-z0-9_-]{43}', raw):
        credential = db.get(Credential, a.digest(raw))
        if credential and credential.kind in ('access', 'refresh') and credential.issuer == cfg.issuer and credential.audience == cfg.resource:
            grant = db.scalar(select(Grant).where(Grant.id == credential.grant_id).with_for_update())
            if grant and grant.client_id == fields.get('client_id') and grant.revoked_at is None:
                grant.revoked_at, grant.revocation_reason = a.now(), 'user_revocation'
                a.audit(db, db.get(User, grant.user_id), 'grant_revoked', grant=grant)
                db.commit()
    return JSONResponse({}, headers={'Cache-Control': 'no-store'})


@router.post('/delegate')
@router.post('/validate')
async def delegate(request: Request, db=Depends(get_db)):
    cfg = a.configuration()
    provided = request.headers.getlist('x-mcp-service')
    if (len(provided) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', provided[0])
            or not hmac.compare_digest(provided[0], cfg.service_secret)):
        a.fail()
    body = await data(request, {'token', 'tool_id'})
    authority = a.credential_authority(db, body.get('token'), 'access', cfg)
    tool = body.get('tool_id')
    if tool is not None and (not isinstance(tool, str) or tool not in authority.tools):
        a.fail(403)
    result = {'user_id': authority.user.id, 'tenant_id': str(authority.user.tenant_id),
        'role': authority.user.role.value, 'department_id': authority.user.department_id,
        'client_id': authority.grant.client_id, 'grant_id': authority.grant.id,
        'scopes': sorted(authority.scopes), 'tools': sorted(authority.tools), 'policy_revision': str(authority.policy.revision)}
    if request.url.path.endswith('/delegate'):
        if tool is None:
            a.fail(403)
        result['credential'] = a.issue_credential(db, authority, 'downstream', cfg, tool=tool)[0]
        a.audit(db, authority.user, 'delegation_issued', grant=authority.grant, tool=tool)
        db.commit()
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})


@router.post('/grants/{grant_id}/revoke')
def revoke_grant(grant_id: str, db=Depends(get_db), user=Depends(get_current_active_user)):
    row = db.scalar(select(Grant).where(Grant.id == grant_id, Grant.tenant_id == user.tenant_id).with_for_update())
    if not row or (row.user_id != user.id and user.role not in (RoleEnum.OWNER, RoleEnum.ADMIN)):
        a.fail(404)
    row.revoked_at, row.revocation_reason = a.now(), 'user_revocation'
    a.audit(db, user, 'grant_revoked', grant=row)
    db.commit()
    return {'revoked': True}
