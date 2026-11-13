"""Disposable navigation DB and identity doubles; no app startup or MCP network.

Session cryptography/real REST regression is covered separately by Phase 2B.
Here the existing active-user and Owner/Admin dependencies are exercised with
controlled principals, alongside actual tenant navigation policy reads.
"""
import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.dependencies import get_current_user
from backend.app.models import NavigationPolicy, RoleEnum, UserStatusEnum
from backend.app.navigation_guard import enforce_navigation_policy
from backend.app.navigation_registry import BY_ID, api_pages, default_rules
from backend.app.routers.mcp_management import TOOLS, router

BASES = ['/mcp-management', '/api/mcp-management']
PAYLOAD = dict(enabled=True, read_only=True, allowed_tool_ids=['zeaplay_list_tasks'],
               allowed_roles=['user'], reason='Isolated policy test')


@pytest.fixture
def harness(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'mcp-policy.db'}", connect_args={'check_same_thread': False})
    NavigationPolicy.__table__.create(engine)
    principal = SimpleNamespace(id='mcp-test-owner', role=RoleEnum.OWNER,
                                tenant_id=uuid.uuid4(), status=UserStatusEnum.ACTIVE)
    app = FastAPI(dependencies=[Depends(enforce_navigation_policy)])
    app.include_router(router)
    app.include_router(router, prefix='/api')
    def session():
        with Session(engine) as db:
            yield db
    async def identity():
        return principal
    async def guarded_identity(token, db):
        return principal
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = identity
    monkeypatch.setattr('backend.app.navigation_guard.get_current_user', guarded_identity)
    statements = []
    event.listen(engine, 'before_cursor_execute', lambda conn, cursor, statement, *args: statements.append(statement))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer isolated-identity-double'
        yield client, principal, engine, statements
    engine.dispose()


@pytest.mark.parametrize('base', BASES)
@pytest.mark.parametrize('role', list(RoleEnum))
def test_existing_owner_admin_policy_on_reads_and_mutations(harness, base, role):
    client, user, _, _ = harness
    user.role = role
    expected = 200 if role in (RoleEnum.OWNER, RoleEnum.ADMIN) else 403
    assert client.get(base).status_code == expected
    for method, path, body in [('PATCH', '/policy', PAYLOAD), ('POST', '/emergency-disable', {'reason': 'Stop'})]:
        response = client.request(method, base + path, json=body)
        assert response.status_code == (503 if expected == 200 else 403)
        if response.status_code == 503:
            assert response.json()['detail']['code'] == 'MCP_POLICY_STORAGE_UNAVAILABLE'


@pytest.mark.parametrize('base', BASES)
def test_safe_snapshot_unknown_health_and_no_persistence(harness, base):
    client, user, _, statements = harness
    response = client.get(base)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    snapshot = response.json()
    assert snapshot['tenant_context'] == str(user.tenant_id)
    assert snapshot['overview'] == dict(service_status='not_configured', health_status='not_monitored',
        last_checked_at=None, total_tools=5, enabled_tools=0, active_connections=None,
        security_mode='Read-only / remote access blocked', endpoint=None, remote_access_enabled=False)
    assert snapshot['configuration']['persisted'] is False
    assert snapshot['configuration']['emergency_disabled'] is None
    assert all(tool['read_only'] and not tool['enabled'] and not tool['available'] for tool in snapshot['tools'])
    for section in ('activity', 'connections'):
        assert snapshot[section]['available'] is False and snapshot[section]['items'] == []
    assert client.patch(base + '/policy', json=PAYLOAD).status_code == 503
    assert client.post(base + '/emergency-disable', json={'reason': 'Stop'}).status_code == 503
    assert client.get(base).json() == snapshot
    assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER')) for s in statements)


@pytest.mark.parametrize('field,value', [
    ('tenant_id', str(uuid.uuid4())), ('actor_id', 'other-user'), ('role', 'owner'),
    ('token', 'synthetic-secret'), ('endpoint', 'https://invalid.example/mcp'),
    ('read_only', False), ('read_only', 1), ('enabled', 'true'),
    ('allowed_tool_ids', ['zeaplay_delete_task']), ('allowed_tool_ids', ['zeaplay_list_tasks'] * 2),
    ('allowed_roles', ['platform_admin']), ('allowed_roles', ['user', 'user']), ('reason', '   '),
])
def test_invalid_or_spoofed_policy_rejected_atomically(harness, field, value):
    client, _, _, _ = harness
    response = client.patch('/mcp-management/policy', json={**PAYLOAD, field: value})
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'no-store'
    assert 'synthetic-secret' not in response.text
    assert client.get('/mcp-management').json()['configuration']['enabled'] is False


@pytest.mark.parametrize('base', BASES)
def test_no_tenant_selector_in_query_or_emergency_payload(harness, base):
    client, user, _, _ = harness
    other = str(uuid.uuid4())
    assert client.get(base, params={'tenant_id': other}).status_code == 422
    assert client.post(base + '/emergency-disable', json={'reason': 'Stop', 'tenant_id': other}).status_code == 422
    assert client.get(base).json()['tenant_context'] == str(user.tenant_id)


@pytest.mark.parametrize('base', BASES)
def test_tenant_navigation_denial_cannot_be_bypassed_by_alias(harness, base):
    client, user, engine, _ = harness
    tenant_a = user.tenant_id
    rules = default_rules()
    rules['settings.mcp-management']['enabled'] = False
    with Session(engine) as db:
        db.add(NavigationPolicy(tenant_id=str(tenant_a), pages=rules, version=1,
            updated_by=user.id, updated_at=datetime.now(timezone.utc)))
        db.commit()
    assert client.get(base).status_code == 403
    assert client.patch(base + '/policy', json=PAYLOAD).status_code == 403
    assert client.post(base + '/emergency-disable', json={'reason': 'Stop'}).status_code == 403
    user.tenant_id = uuid.uuid4()
    other = client.get(base)
    assert other.status_code == 200 and other.json()['tenant_context'] == str(user.tenant_id)
    assert client.patch(base + '/policy', json=PAYLOAD).status_code == 503
    user.tenant_id = tenant_a
    assert client.get(base).status_code == 403


@pytest.mark.parametrize('base', BASES)
def test_missing_auth_inactive_and_missing_tenant_fail_closed(harness, base):
    client, user, _, _ = harness
    client.headers.pop('Authorization')
    assert client.get(base).status_code == 401
    client.headers['Authorization'] = 'Bearer isolated-identity-double'
    user.status = next(status for status in UserStatusEnum if status != UserStatusEnum.ACTIVE)
    assert client.get(base).status_code == 403
    user.status = UserStatusEnum.ACTIVE
    user.tenant_id = None
    assert client.get(base).status_code == 403


@pytest.mark.parametrize('base', BASES)
def test_invalid_real_bearer_is_denied_before_database_access(base):
    app = FastAPI()
    app.include_router(router)
    app.include_router(router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.get(base, headers={'Authorization': 'Bearer not-a-valid-jwt'}).status_code == 401


def test_catalog_matches_existing_mcp_without_importing_or_changing_runtime():
    source = Path(__file__).resolve().parents[2] / 'mcp-server/src/zeaplay_mcp/catalog.py'
    tree = ast.parse(source.read_text())
    catalog = next(node.value.args[0] for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'CATALOG' for target in node.targets))
    expected = {key.value: contract.args[1].value for key, contract in zip(catalog.keys, catalog.values)}
    assert {tool[0]: tool[3] for tool in TOOLS} == expected
    assert BY_ID['settings.mcp-management']['permittedRoles'] == ['owner', 'admin']
    for base in BASES:
        assert api_pages(base + '/policy', 'PATCH') == ('settings.mcp-management',)


def test_no_connection_or_protocol_creation_endpoint(harness):
    client, _, _, _ = harness
    for path in ('/mcp-management/connections', '/mcp-management/clients', '/mcp'):
        assert client.post(path, json={'api_key': 'synthetic-only'}).status_code == 404


@pytest.mark.parametrize('base', BASES)
@pytest.mark.parametrize('suffix', ['/policy', '/emergency-disable'])
def test_validation_never_reflects_untrusted_field_names_or_values(harness, base, suffix):
    client, _, _, _ = harness
    response = client.request('PATCH' if suffix == '/policy' else 'POST', base + suffix,
        json={'REVIEW_CREDENTIAL_IN_FIELD_NAME': 'REVIEW_CREDENTIAL_IN_VALUE'})
    assert response.status_code == 422
    assert 'REVIEW_CREDENTIAL' not in response.text
    assert response.headers['cache-control'] == 'no-store'
