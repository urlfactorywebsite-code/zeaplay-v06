"""Authlib grant implementations bound to live ZeaPlay authority."""
from datetime import timedelta
import logging
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from authlib.oauth2.rfc6749 import AuthorizationServer, OAuth2Request
from authlib.oauth2.rfc6749.requests import BasicOAuth2Payload
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant, RefreshTokenGrant
from authlib.oauth2.rfc6749.errors import InvalidGrantError, InvalidRequestError
from authlib.oauth2.rfc7636 import CodeChallenge
from fastapi import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from . import authority as a
from .models import Authorization, Client, Credential, Grant

# Authlib debug token-grant logs contain token dictionaries. Never enable them.
logging.getLogger('authlib.oauth2').disabled = True
for name in ('authlib.oauth2.rfc6749.grants.authorization_code', 'authlib.oauth2.rfc6749.grants.refresh_token'):
    logging.getLogger(name).disabled = True


class PublicClient:
    def __init__(self, row):
        self.row, self.client_id = row, row.id

    def get_client_id(self): return self.client_id
    def get_default_redirect_uri(self): return self.row.redirect_uris[0]
    def check_client_secret(self, secret): return False
    def check_endpoint_auth_method(self, method, endpoint): return method == 'none'
    def check_response_type(self, value): return value == 'code'
    def check_grant_type(self, value): return value in ('authorization_code', 'refresh_token')
    def get_allowed_scope(self, scope):
        return ' '.join(sorted(set((scope or '').split()) & set(self.row.scopes.split()) & a.SCOPES))
    def check_redirect_uri(self, value):
        if value not in self.row.redirect_uris:
            return False
        parsed = urlsplit(value)
        try:
            a.loopback_origin(urlunsplit((parsed.scheme, parsed.netloc, '', '', '')))
        except HTTPException:
            return False
        return not parsed.fragment and not (set(dict(parse_qsl(parsed.query))) & {'code', 'state', 'iss', 'error'})


class Request(OAuth2Request):
    def __init__(self, method, uri, data, headers=None):
        super().__init__(method, uri, headers=headers)
        self.payload = BasicOAuth2Payload(data)
    @property
    def form(self): return self.payload.data
    @property
    def args(self): return self.payload.data


class S256(CodeChallenge):
    SUPPORTED_CODE_CHALLENGE_METHOD = ['S256']
    DEFAULT_CODE_CHALLENGE_METHOD = 'S256'
    def validate_code_challenge(self, grant, redirect_uri):
        data = grant.request.payload.data
        if data.get('code_challenge_method') != 'S256' or len(data.get('code_challenge', '')) != 43:
            raise InvalidRequestError('S256 PKCE is required')
        return super().validate_code_challenge(grant, redirect_uri)


def code_view(row):
    return SimpleNamespace(row=row, code_challenge=row.code_challenge,
        code_challenge_method=row.code_challenge_method,
        get_redirect_uri=lambda: row.redirect_uri, get_scope=lambda: row.scopes)


class CodeGrant(AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ['none']
    def save_authorization_code(self, code, request):
        row = self.server.pending
        if row is None or row.decided_at is not None:
            raise InvalidGrantError()
        row.code_digest = a.digest(code)
        row.code_expires_at = min(row.expires_at, a.now() + timedelta(seconds=45))
        row.decided_at = a.now()
        self.server.db.flush()
    def query_authorization_code(self, code, client):
        if len(code) > 256:
            return None
        try:
            code_hash = a.digest(code)
        except (UnicodeError, AttributeError):
            return None
        row = self.server.db.scalar(select(Authorization).where(Authorization.code_digest == code_hash,
            Authorization.client_id == client.client_id).with_for_update().execution_options(populate_existing=True))
        if row and row.consumed_at is not None and row.grant_id:
            db = self.server.db
            grant = db.get(Grant, row.grant_id)
            if grant and grant.revoked_at is None:
                from ..models import User
                grant.revoked_at, grant.revocation_reason = a.now(), 'code_reuse'
                a.audit(db, db.get(User, grant.user_id), 'code_reuse_revoked', grant=grant, outcome='denied')
                db.commit()
            return None
        if (not row or row.consumed_at is not None or not row.grant_id or not row.code_expires_at
                or row.code_expires_at <= a.now() or row.resource != self.server.cfg.resource
                or row.code_challenge_method != 'S256'):
            return None
        return code_view(row)
    def delete_authorization_code(self, code):
        code.row.consumed_at = a.now()
    def authenticate_user(self, code):
        try:
            return a.grant_authority(self.server.db, code.row.grant_id, self.server.cfg)
        except HTTPException:
            raise InvalidGrantError() from None


class RefreshGrant(RefreshTokenGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ['none']
    INCLUDE_NEW_REFRESH_TOKEN = True
    def authenticate_refresh_token(self, raw):
        db = self.server.db
        if not isinstance(raw, str) or len(raw) > 128:
            return None
        try:
            record = db.scalar(select(Credential).where(Credential.digest == a.digest(raw))
                .with_for_update().execution_options(populate_existing=True))
        except UnicodeError:
            return None
        if record is None or record.kind != 'refresh':
            return None
        grant = db.get(Grant, record.grant_id, populate_existing=True)
        if not grant or grant.client_id != self.request.client.client_id:
            return None
        if record.consumed_at is not None:
            grant.revoked_at = a.now()
            grant.revocation_reason = 'refresh_reuse'
            from ..models import User
            user = db.get(User, grant.user_id, populate_existing=True)
            a.audit(db, user, 'refresh_reuse_revoked', grant=grant, outcome='denied')
            db.commit()  # Revocation survives the OAuth error response.
            return None
        try:
            authority = a.credential_authority(db, raw, 'refresh', self.server.cfg)
        except HTTPException:
            return None
        return SimpleNamespace(record=record, authority=authority,
            check_client=lambda client: client.client_id == authority.grant.client_id,
            get_scope=lambda: ' '.join(sorted(authority.scopes)))
    def authenticate_user(self, credential): return credential.authority
    def revoke_old_credential(self, credential): credential.record.consumed_at = a.now()


class Server(AuthorizationServer):
    def __init__(self, db, cfg, pending=None):
        super().__init__(scopes_supported=list(a.SCOPES))
        self.db, self.cfg, self.pending = db, cfg, pending
        self.register_grant(CodeGrant, [S256(required=True)])
        self.register_grant(RefreshGrant)
        self.register_token_generator('default', self.generate)
    def query_client(self, client_id):
        row = self.db.get(Client, client_id)
        return PublicClient(row) if row is not None and row.enabled else None
    def create_oauth2_request(self, request): return request
    def send_signal(self, *args, **kwargs): pass
    def generate(self, *, user, scope, include_refresh_token=True, **kwargs):
        user.scopes &= frozenset((scope or '').split())
        token, seconds = a.issue_credential(self.db, user, 'access', self.cfg)
        result = {'access_token': token, 'token_type': 'Bearer', 'expires_in': seconds,
                  'scope': ' '.join(sorted(user.scopes))}
        if include_refresh_token:
            result['refresh_token'] = a.issue_credential(self.db, user, 'refresh', self.cfg)[0]
        return result
    def save_token(self, token, request):
        a.audit(self.db, request.user.user, 'credentials_issued', grant=request.user.grant)
        self.db.flush()
    def handle_response(self, status, body, headers):
        headers = dict(headers)
        headers.update({'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer'})
        if 'Location' in headers:
            location = urlsplit(headers.pop('Location'))
            query = parse_qsl(location.query, keep_blank_values=True) + [('iss', self.cfg.issuer)]
            return RedirectResponse(urlunsplit(location._replace(query=urlencode(query))), status_code=status, headers=headers)
        if isinstance(body, dict) and 'error' in body:
            body = {'error': body['error'], 'error_description': 'OAuth request rejected'}
        return JSONResponse(body, status_code=status, headers=headers)
