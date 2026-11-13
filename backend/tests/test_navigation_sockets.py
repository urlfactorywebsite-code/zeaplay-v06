from types import SimpleNamespace
from contextlib import contextmanager
from copy import deepcopy
import asyncio
import uuid
import pytest
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from backend.app import models
from backend.app.auth import decode_token_claims
from backend.app.navigation_registry import default_rules
from backend.app.services import navigation_sockets
from backend.app.services.auth_sessions import issue_api, now
from backend.app.session_models import AuthSession
from backend.checks.navigation_fixture_app import TENANTS, create_fixture_app


@pytest.fixture
def state(tmp_path, monkeypatch):
    # Exercise the real session validator against owned SQLite storage. The
    # PostgreSQL suite separately covers production invalidation triggers.
    app = create_fixture_app(tmp_path / 'socket-policy.db')
    engine = app.state.fixture_engine
    rules = default_rules()
    @contextmanager
    def session():
        with Session(engine) as db:
            yield db
    monkeypatch.setattr(navigation_sockets, "SessionLocal", session)
    try:
        with Session(engine) as db:
            user = db.get(models.User, str(uuid.uuid5(TENANTS['a'], 'user')))
            db.add(models.NavigationPolicy(tenant_id=str(user.tenant_id), pages=deepcopy(rules),
                                           version=0, updated_by=user.id, updated_at=now()))
            token, _ = issue_api(db, user, minutes=5, scopes=[])
            db.commit()
            socket = SimpleNamespace(state=SimpleNamespace(auth_claims=decode_token_claims(token)))
            yield socket, user, db, rules
    finally:
        engine.dispose()
        app.state.fixture_cleanup()


def persist(state):
    socket, user, db, rules = state
    policy = db.get(models.NavigationPolicy, socket.state.auth_claims['tenant_id'])
    policy.pages = deepcopy(rules)
    flag_modified(policy, 'pages')
    db.commit()


def test_disabled_module_cannot_open_socket(state):
    socket, user, db, rules = state
    rules["tickets"]["enabled"] = False
    persist(state)
    assert not navigation_sockets.bind_socket(socket, user, db, ("tickets",))


def test_active_socket_is_revoked_on_policy_change(state):
    socket, user, db, rules = state
    assert navigation_sockets.bind_socket(socket, user, db, ("chat",))
    assert navigation_sockets.socket_allowed(socket, ("chat",))
    rules["chat"]["allowedRoles"] = ["owner"]
    persist(state)
    assert not navigation_sockets.socket_allowed(socket, ("chat",))


@pytest.mark.parametrize("change", ["inactive", "tenant", "disabled", "revoked", "epoch"])
def test_existing_socket_rechecks_identity_and_availability(state, change):
    socket, user, db, rules = state
    assert navigation_sockets.bind_socket(socket, user, db, ("tickets",))
    if change == "inactive": user.status = models.UserStatusEnum.DEACTIVATED
    if change == "tenant": user.tenant_id = TENANTS['b']
    if change == "disabled": rules["tickets"]["enabled"] = False
    if change == "revoked": db.get(AuthSession, socket.state.auth_claims['sid']).revoked_at = now()
    if change == "epoch": user.auth_epoch += 1
    persist(state)
    assert not navigation_sockets.socket_allowed(socket, ("tickets",))


def test_signed_identity_without_durable_claims_cannot_bind_socket(state):
    socket, user, db, rules = state
    socket.state.auth_claims = {'sub': user.id, 'tenant_id': str(user.tenant_id)}
    assert not navigation_sockets.bind_socket(socket, user, db, ("tickets",))


@pytest.mark.parametrize("kind", ["tasks", "tickets", "chat"])
def test_broadcast_never_sends_payload_after_policy_revocation(monkeypatch, kind):
    from backend.app.ws import tasks, ticket_chat, chat
    module = {"tasks": tasks, "tickets": ticket_chat, "chat": chat}[kind]
    monkeypatch.setattr(module, "socket_allowed", lambda *args: False)
    class Socket:
        state = SimpleNamespace()
        sent = False
        closed = False
        async def send_json(self, value): self.sent = True
        async def close(self, **kwargs): self.closed = True
    socket = Socket()
    async def run():
        if kind == "chat":
            manager = chat.ChatConnectionManager()
            await manager._send_many([socket], "message:new", {"text": "sensitive fixture"}, False)
        else:
            manager = tasks.TaskConnectionManager() if kind == "tasks" else ticket_chat.TicketConnectionManager()
            manager._connections["tenant"] = {socket}
            await manager.broadcast("tenant", {"text": "sensitive fixture"})
    asyncio.run(run())
    assert socket.closed and not socket.sent
