import copy
import uuid

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.auth import create_access_token, decode_token_claims
from backend.app.config import get_settings
from backend.app.webhooks import dispatcher
from backend.checks.navigation_fixture_app import PASSWORD, TENANTS, create_fixture_app


@pytest.fixture
def app(tmp_path):
    application = create_fixture_app(tmp_path / "readiness.db")
    yield application
    application.state.fixture_engine.dispose()
    application.state.fixture_cleanup()


def login(app, role, tenant="a"):
    client = TestClient(app)
    response = client.post('/auth/login', json={'email': f'{role}-{tenant}@readiness.example.com', 'password': PASSWORD})
    assert response.status_code == 200, response.text
    client.headers['Authorization'] = f"Bearer {response.json()['token']['access_token']}"
    return client


def policy(client):
    response = client.get('/navigation')
    assert response.status_code == 200
    return response.json()


def update(client, **changes):
    current = policy(client)
    rules = {page['id']: {key: page[key] for key in ('enabled', 'hidden', 'allowedRoles')} for page in current['pages']}
    for key, value in changes.items(): rules[key].update(value)
    return client.put('/navigation', json={'version': current['version'], 'pages': rules})


def page(client, id):
    return next(page for page in policy(client)['pages'] if page['id'] == id)


def test_requested_api_scenario_real_logins_jwt_and_persistence(app):
    owner = login(app, 'owner')
    assert update(owner, **{'settings': {'enabled': True}, 'settings.api': {'enabled': True, 'allowedRoles': ['owner', 'admin']}}).status_code == 200
    # Logout and fresh client sessions cannot clear server configuration.
    assert owner.post('/auth/logout').status_code == 204
    for role in ('owner', 'admin', 'manager', 'user'):
        with login(app, role) as client:
            allowed = role in ('owner', 'admin')
            assert page(client, 'settings.api')['visible'] is allowed
            assert client.get('/config/api').status_code == (200 if allowed else 403)
            assert client.get('/api/config/api/').status_code == (200 if allowed else 403)
            assert 'tenant-a-fixture-key' not in policy(client).__str__()
    owner = login(app, 'owner')
    assert update(owner, **{'settings.api': {'enabled': False}}).status_code == 200
    for role in ('owner', 'admin', 'manager', 'user'):
        with login(app, role) as client:
            assert page(client, 'settings.api')['visible'] is False
            assert client.get('/config/api').status_code == 403
    assert update(owner, **{'settings.api': {'enabled': True}}).status_code == 200
    assert page(login(app, 'admin'), 'settings.api')['visible'] is True
    assert page(login(app, 'manager'), 'settings.api')['visible'] is False
    assert page(login(app, 'user'), 'settings.api')['visible'] is False


@pytest.mark.parametrize('role', ['user', 'manager'])
@pytest.mark.parametrize('path', ['/config/api', '/config/smtp', '/config/smtp/multiple', '/config/oauth', '/config/email-templates', '/webhooks', '/webhooks/deliveries'])
def test_members_cannot_read_configuration_through_either_api_alias(app, role, path):
    client = login(app, role)
    for prefix in ('', '/api'):
        response = client.get(prefix + path)
        assert response.status_code == 403
        assert 'fixture-key' not in response.text


def test_hidden_vs_forbidden_roles_are_independent_of_visibility(app):
    owner = login(app, 'owner')
    assert update(owner, **{'settings.api': {'hidden': True}}).status_code == 200
    admin = login(app, 'admin')
    assert not page(admin, 'settings.api')['visible']
    assert page(admin, 'settings.api')['access'] == 'allowed'
    assert admin.get('/config/api').status_code == 200
    assert update(owner, **{'settings.api': {'allowedRoles': ['owner']}}).status_code == 200
    assert admin.get('/config/api').status_code == 403


def test_admin_cannot_bypass_owner_policy_controls_or_protection(app):
    admin = login(app, 'admin')
    assert update(admin, **{'settings.api': {'enabled': False}}).status_code == 403
    assert update(admin, **{'settings.api': {'allowedRoles': ['admin']}}).status_code == 403
    assert update(admin, **{'settings.api': {'hidden': True}}).status_code == 200
    for id in ('settings', 'settings.profile', 'settings.sidebar-management'):
        assert update(admin, **{id: {'enabled': False}}).status_code == 422


def test_tenant_and_role_claim_spoofing_are_rejected_by_database_identity(app):
    user_id = str(uuid.uuid5(TENANTS['a'], 'user'))
    member = login(app, 'user')
    claims = decode_token_claims(member.headers['Authorization'].split()[1])
    # Preserve the real session and alter only the claim under test. A bare
    # signed token would be rejected before role/tenant authority is exercised.
    forged_role = create_access_token(user_id, extra_claims={**claims, 'roles': ['owner', 'admin']})
    client = TestClient(app, headers={'Authorization': f'Bearer {forged_role}'})
    assert client.get('/config/api').status_code == 403
    wrong_tenant = create_access_token(user_id, extra_claims={**claims, 'tenant_id': str(TENANTS['b'])})
    assert TestClient(app, headers={'Authorization': f'Bearer {wrong_tenant}'}).get('/navigation').status_code == 401
    valid = login(app, 'owner')
    claims = jwt.decode(valid.headers['Authorization'].split()[1], get_settings().jwt_secret_key, algorithms=[get_settings().jwt_algorithm])
    claims['tenant_id'] = str(TENANTS['b'])
    # Even a correctly signed stale tenant claim is not authoritative over User.
    token = jwt.encode(claims, get_settings().jwt_secret_key, algorithm=get_settings().jwt_algorithm)
    assert TestClient(app, headers={'Authorization': f'Bearer {token}'}).get('/navigation').status_code == 401


def test_configurations_and_policy_cannot_cross_tenants(app):
    a, b = login(app, 'owner', 'a'), login(app, 'admin', 'b')
    assert a.get('/config/api').json()['api_key'] == 'tenant-a-fixture-key'
    assert b.get('/config/api').json()['api_key'] == 'tenant-b-fixture-key'
    assert update(a, **{'settings.api': {'enabled': False}}).status_code == 200
    assert b.get('/config/api').status_code == 200
    assert page(b, 'settings.api')['enabled'] is True
    assert update(a, **{'settings.api': {'enabled': True}}).status_code == 200
    smtp = a.post('/config/smtp/multiple', json={'name': 'Tenant A', 'host': 'smtp.example.test', 'port': 587, 'username': 'fixture', 'password': 'tenant-a-fixture-secret', 'encryption': 'tls', 'notification_types': []})
    assert smtp.status_code == 200, smtp.text
    id = smtp.json()['id']
    assert b.get('/config/smtp/multiple').json() == []
    assert b.patch(f'/config/smtp/multiple/{id}', json={'name': 'stolen'}).status_code == 404
    assert b.delete(f'/config/smtp/multiple/{id}').status_code == 404
    oauth = a.post('/config/oauth', json={'name': 'Tenant A', 'redirect_url': 'https://example.test/callback', 'scopes': [], 'n8n_integration': False})
    assert oauth.status_code == 201, oauth.text
    id = oauth.json()['id']
    assert b.get('/config/oauth').json() == []
    assert b.post(f'/config/oauth/{id}/rotate', json={'rotate_client_secret': True}).status_code == 404
    assert b.delete(f'/config/oauth/{id}').status_code == 404
    assert a.put('/config/email-templates/tenant-note', json={'subject': 'A private subject', 'body': 'Tenant A fixture'}).status_code == 200
    assert all(row['notification_type'] != 'tenant-note' for row in b.get('/config/email-templates').json())


def test_switching_and_resetting_policies_does_not_change_config_data(app):
    owner = login(app, 'owner')
    engine = app.state.fixture_engine
    with Session(engine) as db:
        before = [(row.id, row.api_key, row.tenant_id) for row in db.scalars(select(models.ApiConfig))]
    assert update(owner, **{'settings.api': {'enabled': False}}).status_code == 200
    assert update(owner, **{'settings.api': {'enabled': True, 'allowedRoles': ['owner', 'admin'], 'hidden': False}}).status_code == 200
    with Session(engine) as db:
        assert [(row.id, row.api_key, row.tenant_id) for row in db.scalars(select(models.ApiConfig))] == before


def test_webhook_admin_and_delivery_tenant_isolation(app, monkeypatch):
    a, b = login(app, 'admin', 'a'), login(app, 'admin', 'b')
    created = a.post('/webhooks', json={'name': 'A hook', 'url': 'https://example.test/hook', 'subscribed_events': ['user.created'], 'is_enabled': True})
    assert created.status_code == 201, created.text
    id = created.json()['id']
    assert b.get('/webhooks').json() == []
    assert b.put(f'/webhooks/{id}', json={'is_enabled': False}).status_code == 404
    assert b.post(f'/webhooks/{id}/test', json={'event_name': 'user.created'}).status_code == 404
    assert b.delete(f'/webhooks/{id}').status_code == 404
    with Session(app.state.fixture_engine) as db:
        assert dispatcher.queue_webhook_deliveries(db, event_type='user.created', payload={}) == []
        assert dispatcher.queue_webhook_deliveries(db, event_type='user.created', payload={}, tenant_id=TENANTS['b']) == []
        logs = dispatcher.queue_webhook_deliveries(db, event_type='user.created', payload={'fixture': True}, tenant_id=TENANTS['a'])
        assert len(logs) == 1 and logs[0].tenant_id == TENANTS['a']
        db.commit()
    assert b.get('/webhooks/deliveries').json()['total'] == 0
    assert a.get('/webhooks/deliveries').json()['total'] == 1


@pytest.mark.parametrize('existing', [False, True])
def test_real_concurrent_authenticated_saves_only_commit_one_version(app, monkeypatch, existing):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from backend.app.routers import navigation
    first, second = login(app, 'owner'), login(app, 'owner')
    if existing:
        assert update(first, **{'tickets': {'hidden': True}}).status_code == 200
    current = policy(first)
    base = {'version': current['version'], 'pages': {page['id']: {key: page[key] for key in ('enabled', 'hidden', 'allowedRoles')} for page in current['pages']}}
    one, two = copy.deepcopy(base), copy.deepcopy(base)
    one['pages']['reports']['hidden'] = True
    two['pages']['settings.api']['hidden'] = True
    original, barrier = navigation.load_policy, Barrier(2, timeout=10)
    def overlap(db, tenant):
        value = original(db, tenant)
        barrier.wait()
        return value
    monkeypatch.setattr(navigation, 'load_policy', overlap)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.put, '/navigation', json=value) for client, value in ((first, one), (second, two))]
        responses = [future.result() for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert policy(first)['version'] == current['version'] + 1


def test_corrupt_persisted_policy_fails_closed(app):
    owner = login(app, 'owner')
    assert update(owner, **{'settings.api': {'hidden': True}}).status_code == 200
    with Session(app.state.fixture_engine) as db:
        row = db.get(models.NavigationPolicy, str(TENANTS['a']))
        broken = copy.deepcopy(row.pages)
        broken['settings.api']['enabled'] = 'false'
        row.pages = broken
        db.commit()
    assert owner.get('/navigation').status_code == 503
    assert owner.get('/config/api').status_code == 503


def test_common_role_dependency_ignores_forged_or_stale_token_roles(app):
    from fastapi import Depends
    from backend.app.dependencies import require_roles
    from backend.app.services.auth_sessions import invalidate_user
    @app.get('/review/owner-only', dependencies=[Depends(require_roles('owner'))])
    def owner_only(): return {'ok': True}
    owner = login(app, 'owner')
    assert owner.get('/review/owner-only').status_code == 200
    with Session(app.state.fixture_engine) as db:
        user = db.get(models.User, str(uuid.uuid5(TENANTS['a'], 'owner')))
        user.role = models.RoleEnum.USER
        # SQLite does not execute the production PostgreSQL invalidation
        # trigger. Explicitly invalidate this fixture's session with the same
        # canonical authority; the real trigger is tested in the PG suite.
        invalidate_user(db, user.id)
        db.commit()
    assert owner.get('/review/owner-only').status_code == 401
    assert owner.get('/config/api').status_code == 401
    signed_in_again = login(app, 'owner')
    assert signed_in_again.get('/review/owner-only').status_code == 403
    assert signed_in_again.get('/config/api').status_code == 403


@pytest.mark.parametrize('kind', ['api_configuration', 'webhook_configuration'])
def test_configuration_audit_metadata_does_not_cross_tenants(app, kind):
    from backend.app.routers.logs import _apply_scope_filters
    with Session(app.state.fixture_engine) as db:
        for tenant in TENANTS.values():
            db.add(models.AuditLog(tenant_id=tenant, action='FIXTURE', category=models.AuditLogCategoryEnum.SYSTEM, entity_type=kind, entity_id=str(tenant)))
        db.add(models.AuditLog(action='API_CONFIG_UPDATED', category=models.AuditLogCategoryEnum.SYSTEM, entity_type=None))
        db.commit()
        user = db.get(models.User, str(uuid.uuid5(TENANTS['a'], 'admin')))
        records = db.scalars(_apply_scope_filters(select(models.AuditLog), current_user=user, db=db)).all()
        assert len(records) == 1 and records[0].entity_id == str(TENANTS['a'])
