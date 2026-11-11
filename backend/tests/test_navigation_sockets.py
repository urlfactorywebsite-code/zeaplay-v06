from types import SimpleNamespace
from contextlib import contextmanager
import asyncio
import pytest
from backend.app import models
from backend.app.navigation_registry import default_rules
from backend.app.services import navigation_sockets


@pytest.fixture
def state(monkeypatch):
    user = SimpleNamespace(id="fixture", tenant_id="tenant", role=models.RoleEnum.USER, status=models.UserStatusEnum.ACTIVE)
    rules = default_rules()
    class DB:
        def get(self, model, id):
            if model is models.User: return user
            return SimpleNamespace(pages=rules)
    db = DB()
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(navigation_sockets, "SessionLocal", session)
    socket = SimpleNamespace(state=SimpleNamespace())
    return socket, user, db, rules


def test_disabled_module_cannot_open_socket(state):
    socket, user, db, rules = state
    rules["tickets"]["enabled"] = False
    assert not navigation_sockets.bind_socket(socket, user, db, ("tickets",))


def test_active_socket_is_revoked_on_policy_change(state):
    socket, user, db, rules = state
    assert navigation_sockets.bind_socket(socket, user, db, ("chat",))
    assert navigation_sockets.socket_allowed(socket, ("chat",))
    rules["chat"]["allowedRoles"] = ["owner"]
    assert not navigation_sockets.socket_allowed(socket, ("chat",))


@pytest.mark.parametrize("change", ["inactive", "tenant", "disabled"])
def test_existing_socket_rechecks_identity_and_availability(state, change):
    socket, user, db, rules = state
    assert navigation_sockets.bind_socket(socket, user, db, ("tickets",))
    if change == "inactive": user.status = models.UserStatusEnum.DEACTIVATED
    if change == "tenant": user.tenant_id = "other"
    if change == "disabled": rules["tickets"]["enabled"] = False
    assert not navigation_sockets.socket_allowed(socket, ("tickets",))


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
