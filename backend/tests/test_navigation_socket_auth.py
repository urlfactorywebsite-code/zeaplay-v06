"""Real JWT/socket checks against disposable users, tickets and policy storage."""
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from backend.app import models
from backend.app.auth import create_access_token, decode_token_claims
from backend.app.services import navigation_sockets
from backend.app.tickets.models import Ticket, TicketParticipant
from backend.app.ws import ticket_chat
from backend.checks.navigation_fixture_app import PASSWORD, TENANTS, create_fixture_app


@pytest.fixture
def socket_app(tmp_path, monkeypatch):
    app = create_fixture_app(tmp_path / 'socket.db')
    app.include_router(ticket_chat.router)
    engine = app.state.fixture_engine
    models.Base.metadata.create_all(engine, tables=[Ticket.__table__, TicketParticipant.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(ticket_chat, 'SessionLocal', sessions)
    monkeypatch.setattr(navigation_sockets, 'SessionLocal', sessions)
    monkeypatch.setattr(ticket_chat, 'manager', ticket_chat.TicketConnectionManager())
    ticket_id = uuid.UUID('c3333333-3333-4333-8333-333333333333')
    admin_id = str(uuid.uuid5(TENANTS['a'], 'admin'))
    with Session(engine) as db:
        db.add(Ticket(id=ticket_id, tenant_id=TENANTS['a'], created_by=admin_id, owner_id=admin_id, title='Private fixture ticket', description='Isolated security fixture'))
        db.commit()
    yield app, ticket_id
    engine.dispose(); app.state.fixture_cleanup()


@pytest.mark.parametrize('case', ['signed-out', 'wrong-tenant', 'forged-role'])
def test_ticket_socket_rejects_unsigned_cross_tenant_or_escalated_identity(socket_app, case):
    app, ticket_id = socket_app
    query = ''
    if case != 'signed-out':
        role = 'user' if case == 'forged-role' else 'owner'
        with TestClient(app) as client:
            response = client.post('/auth/login', json={'email': f'{role}-a@readiness.example.com', 'password': PASSWORD})
        assert response.status_code == 200
        claims = decode_token_claims(response.json()['token']['access_token'])
        token = create_access_token(claims['sub'], extra_claims={**claims,
            'tenant_id': str(TENANTS['b'] if case == 'wrong-tenant' else TENANTS['a']), 'roles': ['owner']})
        query = f'?token={token}'
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(f'/ws/tickets/{ticket_id}'+query): pass
    assert error.value.code == 1008


def test_connected_socket_closes_when_tenant_module_is_disabled(socket_app):
    from backend.app.navigation_registry import default_rules
    app, ticket_id = socket_app
    with TestClient(app) as client:
        response = client.post('/auth/login', json={'email': 'admin-a@readiness.example.com', 'password': PASSWORD})
        assert response.status_code == 200
        token = response.json()['token']['access_token']
        with client.websocket_connect(f'/ws/tickets/{ticket_id}?token={token}') as socket:
            from datetime import datetime, timezone
            rules = default_rules(); rules['tickets']['enabled'] = False
            with Session(app.state.fixture_engine) as db:
                db.add(models.NavigationPolicy(tenant_id=str(TENANTS['a']), pages=rules, version=1, updated_by=str(uuid.uuid5(TENANTS['a'], 'owner')), updated_at=datetime.now(timezone.utc)))
                db.commit()
            socket.send_json({'type': 'typing'})
            with pytest.raises(WebSocketDisconnect) as error: socket.receive_json()
            assert error.value.code == 1008
