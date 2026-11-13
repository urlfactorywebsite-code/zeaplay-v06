"""Legacy password endpoint using the current durable-session contract.

Fresh fixtures only; no app.main, shared databases, startup or workers.
Production PostgreSQL triggers are exercised by the session audit launcher.
"""
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.auth import create_access_token, decode_token_claims, hash_password
from backend.app.models import User, UserStatusEnum
from backend.app.routers import oauth2_server
from backend.app.services.auth_sessions import now
from backend.app.session_models import AuthSession
from backend.checks.navigation_fixture_app import TENANTS, create_fixture_app


@pytest.fixture
def api(tmp_path):
    app = create_fixture_app(tmp_path / 'oauth-password.db')
    app.include_router(oauth2_server.router)
    app.include_router(oauth2_server.router, prefix='/api')
    user_id = str(uuid.uuid4())
    with Session(app.state.fixture_engine) as db:
        db.add(User(id=user_id, tenant_id=TENANTS['a'], email='testuser@example.com',
                    name='Isolated password test', hashed_password=hash_password('testpassword'),
                    role='user', status=UserStatusEnum.ACTIVE))
        db.commit()
    try:
        with TestClient(app) as client:
            yield app, client, user_id
    finally:
        app.state.fixture_engine.dispose()
        app.state.fixture_cleanup()


def password_login(client, prefix=''):
    return client.post(prefix + '/oauth2/token', data={
        'username': 'testuser@example.com', 'password': 'testpassword'})


@pytest.mark.parametrize('prefix', ['', '/api'])
def test_login_success(api, prefix):
    app, client, user_id = api
    response = password_login(client, prefix)
    assert response.status_code == 200
    result = response.json()
    assert result['token_type'] == 'bearer'
    claims = decode_token_claims(result['access_token'])
    assert claims['sub'] == user_id
    assert claims['tenant_id'] == str(TENANTS['a'])
    with Session(app.state.fixture_engine) as db:
        session = db.get(AuthSession, claims['sid'])
        assert session and session.user_id == user_id and session.tenant_id == TENANTS['a']
        assert session.kind == 'api' and session.revoked_at is None
        assert claims['auth_epoch'] == session.auth_epoch
    me = client.get(prefix + '/auth/me', headers={'Authorization': 'Bearer ' + result['access_token']})
    assert me.status_code == 200 and me.json()['id'] == user_id


@pytest.mark.parametrize('prefix', ['', '/api'])
@pytest.mark.parametrize('username,password', [
    ('testuser@example.com', 'wrongpassword'), ('missing@example.com', 'testpassword')])
def test_invalid_password_or_user_creates_no_session(api, prefix, username, password):
    app, client, _ = api
    response = client.post(prefix + '/oauth2/token', data={'username': username, 'password': password})
    assert response.status_code == 401
    assert response.json()['detail'] == 'Incorrect username or password'
    with Session(app.state.fixture_engine) as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_inactive_user_cannot_issue_a_session(api):
    app, client, user_id = api
    with Session(app.state.fixture_engine) as db:
        db.get(User, user_id).status = UserStatusEnum.DEACTIVATED
        db.commit()
    assert password_login(client).status_code == 401
    with Session(app.state.fixture_engine) as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0


@pytest.mark.parametrize('change', ['logout', 'expiry', 'tenant', 'missing-session'])
def test_legacy_endpoint_credentials_remain_subject_to_session_authority(api, change):
    app, client, user_id = api
    response = password_login(client)
    assert response.status_code == 200
    token = response.json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get('/auth/me', headers=headers).status_code == 200
    claims = decode_token_claims(token)
    if change == 'logout':
        assert client.post('/auth/logout', headers=headers).status_code == 204
    elif change == 'expiry':
        with Session(app.state.fixture_engine) as db:
            session = db.get(AuthSession, claims['sid'])
            session.created_at = now() - timedelta(hours=2)
            session.expires_at = now() - timedelta(minutes=1)
            db.commit()
    elif change == 'tenant':
        token = create_access_token(user_id, extra_claims={**claims, 'tenant_id': str(TENANTS['b'])})
    else:
        token = create_access_token(user_id)
    assert client.get('/auth/me', headers={'Authorization': 'Bearer ' + token}).status_code == 401
