"""Real PostgreSQL/handler tests. Only run through the owning Docker launcher."""
from pathlib import Path
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib.abc
import json
import os
import socket
import sys
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

if not os.environ.get("ZEA_PHASE13_ISOLATED") or len(sys.argv) not in (2, 3):
    raise RuntimeError("Use run_mcp_phase1_3.py")
repository = Path(sys.argv[1]).resolve()
replica = len(sys.argv) == 3 and sys.argv[2] == "replica"
sys.argv = [sys.argv[0]]
sys.path[:0] = [str(repository / "backend"), str(repository)]
if Path.cwd() == repository or list(Path.cwd().glob(".env*")):
    raise RuntimeError("Disposable working directory required")


class ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"app.main", "backend.app.main"} or fullname.startswith("backend.tests"):
            raise RuntimeError("Installed startup and legacy test collection forbidden")


sys.meta_path.insert(0, ImportGuard())
pair_context = threading.local()
original_pair = socket.socketpair


def private_pair(*args, **kwargs):
    pair_context.active = True
    try:
        return original_pair(*args, **kwargs)
    finally:
        pair_context.active = False


socket.socketpair = private_pair


def io_guard(event, args):
    if event in {"socket.bind", "socket.connect"} and getattr(pair_context, "active", False):
        return
    if event.startswith("sqlite3.connect") or event in {
        "socket.bind", "socket.connect", "socket.sendto", "socket.getaddrinfo", "socket.gethostbyname",
        "socket.gethostbyaddr", "socket.getnameinfo", "subprocess.Popen", "os.system"
    }:
        raise RuntimeError("External IO forbidden")


sys.addaudithook(io_guard)
import psycopg2  # noqa: E402
from psycopg2.extensions import parse_dsn  # noqa: E402
from sqlalchemy import create_engine, event, func, inspect, select, text  # noqa: E402
from sqlalchemy.engine import Dialect, make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

expected = make_url(os.environ["VEE_DATABASE_URL"])
assert expected.host == "127.0.0.1" and expected.database == "zea_phase13"
assert expected.port == int(os.environ["ZEA_PHASE13_PORT"])
native_connect = psycopg2.connect


def isolated_connect(dsn=None, *args, **kwargs):
    values = {**(parse_dsn(dsn) if dsn else {}), **kwargs}
    if (values.get("host") != expected.host or str(values.get("port")) != str(expected.port)
            or values.get("dbname") != expected.database or values.get("user") != expected.username
            or values.get("password") != expected.password):
        raise RuntimeError("Only the owned disposable PostgreSQL connection is allowed")
    return native_connect(dsn, *args, **kwargs)


psycopg2.connect = isolated_connect


@event.listens_for(Dialect, "do_connect")
def connection_guard(dialect, record, args, kwargs):
    if dialect.name != "postgresql" or dialect.driver != "psycopg2":
        raise RuntimeError("Only isolated PostgreSQL/psycopg2 allowed")


from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from jose import jwt  # noqa: E402
from app import models as m  # noqa: E402
from app.auth import create_access_token, decode_token_claims, hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import Base, engine, get_db  # noqa: E402
from app.navigation_guard import enforce_navigation_policy  # noqa: E402
from app.routers import auth, notifications, oauth2_server, tasks, users  # noqa: E402
from app.services import audit_logger, auth_sessions, subtask_rewards, task_events  # noqa: E402,F401 -- AST regression globals
from app.services.navigation_sockets import bind_socket, socket_allowed  # noqa: E402
from app.session_models import AuthRefreshToken, AuthSession  # noqa: E402
from app.tickets import models as tm, router as tickets, workflow_router  # noqa: E402
from app.webhooks import service as webhook_service  # noqa: E402
from app.ws import tasks as task_ws  # noqa: E402
import app.backups.models  # noqa: F401,E402

settings = get_settings()
assert settings.database_url == os.environ["VEE_DATABASE_URL"]
assert not settings.redis_url and not settings.cache_redis_url and not settings.enable_n8n_forwarding
config = Config()
config.set_main_option("script_location", str(repository / "backend/alembic"))
password_hash = hash_password("fixture-password")


def build_app():
    application = FastAPI(dependencies=[Depends(enforce_navigation_policy)])
    for router in (auth.router, users.router, oauth2_server.router, tasks.router, tickets.router,
                   workflow_router.read_router, notifications.router):
        application.include_router(router)
        application.include_router(router, prefix="/api")
    application.include_router(workflow_router.router)

    def connection():
        with Session(engine) as db:
            yield db
    application.dependency_overrides[get_db] = connection
    return application


# Reuse existing business assertions without executing their SQLite guards,
# importing main, or collecting the destructive legacy integration harness.
def load_class(filename, name, namespace):
    tree = ast.parse((repository / "backend/security_tests" / filename).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


namespace = dict(globals())
Fixture = load_class("mcp_phase1_cases.py", "Phase1Authorization", namespace)
namespace.update(Fixture=Fixture, base={"get_db": get_db, "settings": settings,
                                      "datetime": datetime, "timezone": timezone, "repository": repository})
Phase11 = load_class("mcp_phase1_1_cases.py", "Phase11", namespace)


class PGFixture(unittest.TestCase):
    def setUp(self):
        # Rebuild only this owned disposable schema. Existing immutable domain
        # history triggers forbid TRUNCATE; keep those protections enabled.
        engine.dispose()
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.execute(text("CREATE EXTENSION pg_trgm"))
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values() if not t.info.get("alembic_only")])
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users DROP COLUMN auth_epoch"))
        command.stamp(config, "k1a3c5e7f9b1")
        command.upgrade(config, "l2b4d6f8a0c2")
        auth_sessions.require_session_schema(engine)
        self.engine = engine
        self.tenant, self.foreign = uuid.uuid4(), uuid.uuid4()
        self.departments = [str(uuid.uuid4()), str(uuid.uuid4())]
        self.ids = {n: str(uuid.uuid4()) for n in ("owner", "member", "peer", "manager", "outside_manager", "foreign", "watcher", "admin")}
        self.tickets = [uuid.uuid4(), uuid.uuid4()]
        self.audit_rows = []
        for replacement in (patch.object(audit_logger, "queue_log", side_effect=self.audit_rows.append),
                            patch.object(webhook_service, "enqueue_event", return_value=None),
                            patch.object(task_events, "publish_task_event", return_value=None)):
            replacement.start()
            self.addCleanup(replacement.stop)
        with Session(engine) as db:
            db.add_all([m.Department(id=value, name=f"Department {i}") for i, value in enumerate(self.departments)])
            for name, identifier in self.ids.items():
                role = (m.RoleEnum.OWNER if name in {"owner", "foreign"} else m.RoleEnum.ADMIN if name == "admin"
                        else m.RoleEnum.MANAGER if "manager" in name else m.RoleEnum.USER)
                db.add(m.User(id=identifier, tenant_id=self.foreign if name == "foreign" else self.tenant,
                    email=f"{name}@phase1.example.com", name=name, hashed_password=password_hash, role=role,
                    status=m.UserStatusEnum.ACTIVE, department_id=self.departments[1 if name == "outside_manager" else 0]))
            db.flush()
            for task_id, creator, assignee, group in [("assigned", "owner", "member", "shared"),
                    ("sibling", "owner", "peer", "shared"), ("foreign-task", "foreign", "foreign", "foreign-group")]:
                db.add(m.Task(id=task_id, title=task_id, created_by_id=self.ids[creator], assigned_to_id=self.ids[assignee],
                              task_group_id=group, due_at=datetime(2020, 1, 1) if task_id == "assigned" else None))
            db.flush()
            assigned_task = db.get(m.Task, "assigned")
            assigned_task.followers.append(db.get(m.User, self.ids["watcher"]))
            db.add_all([m.Subtask(id="assigned-child", task_id="assigned", title="Visible child"),
                        m.Subtask(id="sibling-child", task_id="sibling", title="Private sibling child")])
            db.add_all([tm.Ticket(id=self.tickets[0], tenant_id=self.tenant, title="Own tenant ticket", description="Synthetic fixture",
                         created_by=self.ids["member"], owner_id=self.ids["member"], department_id=uuid.UUID(self.departments[0])),
                        tm.Ticket(id=self.tickets[1], tenant_id=self.foreign, title="Foreign ticket", description="Synthetic fixture",
                         created_by=self.ids["foreign"], owner_id=self.ids["foreign"])])
            db.flush()
            db.add(m.Task(id="ticket-private", title="Private linked task", ticket_id=self.tickets[0], created_by_id=self.ids["member"],
                          assigned_to_id=self.ids["member"], task_group_id="ticket-only"))
            db.add(tm.TicketAuditLog(tenant_id=self.tenant, ticket_id=self.tickets[0], actor_user_id=self.ids["member"],
                       event_type="fixture.private", created_at_utc=datetime.now(timezone.utc), summary="Synthetic private ticket audit"))
            db.commit()
        self.app = build_app()
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.header_cache = {}
        for name in self.ids:
            self.headers(name)

    def headers(self, name="member", **changes):
        with Session(engine) as db:
            user = db.get(m.User, self.ids[name])
            cached = self.header_cache.get(name)
            if cached and cached[0] == user.auth_epoch:
                token = cached[1]
            else:
                user = auth_sessions.lock_user(db, self.ids[name])
                pair = auth_sessions.issue_login(db, user)
                self.header_cache[name] = (user.auth_epoch, pair.access_token)
                token = pair.access_token
                db.commit()
        if changes:
            claims = decode_token_claims(token)
            claims.update(changes)
            token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        return {"Authorization": "Bearer " + token}

    request = Fixture.request
    rows = Phase11.rows
    change_user = Phase11.change_user

    def login(self, name="member", prefix="", password="fixture-password", form=False):
        body = {"username": f"{name}@phase1.example.com", "password": password}
        response = self.client.post(prefix + "/auth/login", **({"data": body} if form else {"json": body}))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def refresh(self, pair, prefix=""):
        return self.client.post(prefix + "/auth/refresh", json={"refresh_token": pair["refresh_token"]})

    def access(self, pair):
        return self.client.get("/auth/me", headers={"Authorization": "Bearer " + pair["access_token"]})

    def assert_revoked(self, pair):
        self.assertEqual(self.access(pair).status_code, 401)
        self.assertEqual(self.refresh(pair).status_code, 401)


class SessionTests(PGFixture):
    def test_registration_commits_user_and_session_together(self):
        response = self.client.post("/auth/register", json={"name": "New fixture owner", "email": "new@phase13.example.com",
            "password": "fixture-password", "employer_id": "isolated-" + uuid.uuid4().hex, "role": "owner", "status": "ACTIVE"})
        self.assertEqual(response.status_code, 201, response.text)
        pair = response.json()["token"]
        self.assertEqual(self.access(pair).status_code, 200)
        self.assertEqual(self.refresh(pair).status_code, 200)
        self.client.post("/auth/logout", headers={"Authorization": "Bearer " + pair["access_token"]})
        self.assert_revoked(pair)

    def test_concurrent_logout_cannot_leave_a_surviving_refresh(self):
        pair = self.login()
        barrier = threading.Barrier(2)
        def operation(logout):
            with TestClient(build_app()) as client:
                barrier.wait(timeout=10)
                if logout:
                    return client.post("/auth/logout", headers={"Authorization": "Bearer " + pair["access_token"]})
                return client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        with ThreadPoolExecutor(max_workers=2) as executor:
            logged_out = executor.submit(operation, True)
            refreshed = executor.submit(operation, False)
            self.assertEqual(logged_out.result(timeout=20).status_code, 204)
            response = refreshed.result(timeout=20)
        self.assertIn(response.status_code, (200, 401))
        if response.status_code == 200:
            self.assert_revoked(response.json())
        self.assert_revoked(pair)

    def test_a_migration_upgrade_downgrade_upgrade_preserves_users(self):
        command.downgrade(config, "k1a3c5e7f9b1")
        with engine.connect() as connection:
            self.assertNotIn("auth_sessions", inspect(connection).get_table_names())
            self.assertNotIn("auth_epoch", {c["name"] for c in inspect(connection).get_columns("users")})
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM users")), len(self.ids))
        with self.assertRaises(RuntimeError):
            auth_sessions.require_session_schema(engine)
        command.upgrade(config, "l2b4d6f8a0c2")
        auth_sessions.require_session_schema(engine)
        self.assertEqual(self.access(self.login()).status_code, 200)

    def test_login_form_json_aliases_and_rotation_digest_only(self):
        for prefix in ("", "/api"):
            original = self.login(prefix=prefix, form=bool(prefix))
            response = self.refresh(original, prefix)
            self.assertEqual(response.status_code, 200, response.text)
            rotated = response.json()
            self.assertNotEqual(original["refresh_token"], rotated["refresh_token"])
            self.assertEqual(self.access(rotated).status_code, 200)
            with Session(engine) as db:
                sid = decode_token_claims(original["access_token"])["sid"]
                rows = db.scalars(select(AuthRefreshToken).where(AuthRefreshToken.session_id == sid)).all()
                self.assertEqual(len(rows), 2)
                self.assertEqual(sum(r.consumed_at is not None for r in rows), 1)
                self.assertTrue(all(len(r.digest) == 64 and "." not in r.digest for r in rows))

    def test_replay_revokes_whole_family_but_not_other_login(self):
        original, separate = self.login(), self.login()
        rotated = self.refresh(original).json()
        self.assertEqual(self.refresh(original).status_code, 401)
        self.assert_revoked(rotated)
        self.assertEqual(self.access(separate).status_code, 200)
        with Session(engine) as db:
            self.assertEqual(db.get(AuthSession, decode_token_claims(original["access_token"])["sid"]).revocation_reason, "refresh_reuse")

    def test_concurrent_same_refresh_one_success_one_replay(self):
        original = self.login()
        barrier = threading.Barrier(2)
        def attempt():
            with TestClient(build_app()) as client:
                barrier.wait(timeout=10)
                response = client.post("/auth/refresh", json={"refresh_token": original["refresh_token"]})
                return response.status_code, response.json()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(r[0] for r in results), [200, 401])
        self.assert_revoked(next(body for status, body in results if status == 200))

    def test_logout_and_logout_all(self):
        first, second = self.login(), self.login()
        self.assertEqual(self.client.post("/auth/logout", headers={"Authorization": "Bearer " + first["access_token"]}).status_code, 204)
        self.assert_revoked(first)
        self.assertEqual(self.access(second).status_code, 200)
        self.assertEqual(self.client.post("/auth/logout-all", headers={"Authorization": "Bearer " + second["access_token"]}).status_code, 204)
        self.assert_revoked(second)
        self.assertEqual(self.access(self.login()).status_code, 200)

    def test_tenant_round_trip_cannot_revive_tokens(self):
        pair = self.login()
        self.change_user("member", tenant_id=self.foreign)
        self.assert_revoked(pair)
        foreign_pair = self.login()
        self.change_user("member", tenant_id=self.tenant)
        self.assert_revoked(pair)
        self.assert_revoked(foreign_pair)
        self.assertEqual(self.access(self.login()).status_code, 200)

    def test_deactivate_reactivate_requires_new_login(self):
        pair = self.login()
        self.change_user("member", status=m.UserStatusEnum.DEACTIVATED)
        self.assert_revoked(pair)
        self.assertEqual(self.client.post("/auth/login", json={"email": "member@phase1.example.com", "password": "fixture-password"}).status_code, 403)
        self.change_user("member", status=m.UserStatusEnum.ACTIVE)
        self.assert_revoked(pair)
        self.assertEqual(self.access(self.login()).status_code, 200)

    def test_password_change_and_admin_reset_revoke_all(self):
        pair, other = self.login(), self.login()
        response = self.client.post("/users/me/change-password", headers={"Authorization": "Bearer " + pair["access_token"]},
                                    json={"old_password": "fixture-password", "new_password": "changed-password"})
        self.assertEqual(response.status_code, 204, response.text)
        self.assert_revoked(pair)
        self.assert_revoked(other)
        current = self.login(password="changed-password")
        response = self.client.post(f"/users/{self.ids['member']}/reset-password", headers=self.headers("admin"), json={"new_password": "reset-password"})
        self.assertEqual(response.status_code, 204, response.text)
        self.assert_revoked(current)
        self.assertEqual(self.access(self.login(password="reset-password")).status_code, 200)

    def test_epoch_direct_sql_and_rollback(self):
        pair = self.login()
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("UPDATE users SET tenant_id=:tenant WHERE id=:id"), {"tenant": self.foreign, "id": self.ids["member"]})
            transaction.rollback()
        self.assertEqual(self.access(pair).status_code, 200)
        with engine.begin() as connection:
            connection.execute(text("UPDATE users SET auth_epoch=auth_epoch+1 WHERE id=:id"), {"id": self.ids["member"]})
        self.assert_revoked(pair)
        with self.assertRaises(Exception), engine.begin() as connection:
            connection.execute(text("UPDATE users SET auth_epoch=0 WHERE id=:id"), {"id": self.ids["member"]})

    def test_expired_sessions_legacy_and_malformed_tokens_denied(self):
        pair = self.login()
        with Session(engine) as db:
            session = db.get(AuthSession, decode_token_claims(pair["access_token"])["sid"])
            session.created_at = auth_sessions.now() - timedelta(days=2)
            session.expires_at = auth_sessions.now() - timedelta(seconds=1)
            db.commit()
        self.assert_revoked(pair)
        pair = self.login()
        for key, value in [("exp", None), ("exp", True), ("exp", "9999999999"), ("exp", int(time.time())-1),
                           ("token_type", "refresh"), ("sid", None), ("auth_epoch", True), ("tenant_id", str(self.foreign))]:
            claims = decode_token_claims(pair["access_token"])
            if value is None:
                claims.pop(key)
            else:
                claims[key] = value
            token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
            self.assertEqual(self.access({"access_token": token}).status_code, 401, key)
        legacy = create_access_token(self.ids["member"], extra_claims={"tenant_id": str(self.tenant)})
        self.assertEqual(self.access({"access_token": legacy}).status_code, 401)

    def test_refresh_expiry_type_signature_and_session_claims(self):
        pair = self.login()
        original = decode_token_claims(pair["refresh_token"], refresh=True)
        for key, value in [("exp", None), ("exp", True), ("exp", "9999999999"), ("exp", int(time.time())-1),
                           ("token_type", "access"), ("token_type", None), ("sid", None),
                           ("auth_epoch", True), ("tenant_id", str(self.foreign)), ("scopes", {})]:
            claims = dict(original)
            if value is None:
                claims.pop(key)
            else:
                claims[key] = value
            forged = jwt.encode(claims, settings.jwt_refresh_secret_key, algorithm=settings.jwt_algorithm)
            self.assertEqual(self.refresh({"refresh_token": forged}).status_code, 401, key)
        forged = jwt.encode(original, "isolated-wrong-key", algorithm=settings.jwt_algorithm)
        self.assertEqual(self.refresh({"refresh_token": forged}).status_code, 401)
        self.assertEqual(self.refresh(pair).status_code, 200)

    def test_presence_admission_renewal_and_profile_separation(self):
        pair = self.login()
        headers = {"Authorization": "Bearer " + pair["access_token"]}
        presence = self.client.get("/auth/presence-token", headers=headers).json()["access_token"]
        pheaders = {"Authorization": "Bearer " + presence}
        self.assertEqual(self.client.post("/auth/presence/validate", headers=pheaders).status_code, 204)
        self.assertEqual(self.client.post("/auth/presence/validate", headers=headers).status_code, 401)
        self.assertEqual(self.client.get("/auth/me", headers=pheaders).status_code, 401)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": presence}).status_code, 401)
        self.client.post("/auth/logout", headers=headers)
        self.assertEqual(self.client.get("/auth/presence-token", headers=headers).status_code, 401)
        self.assertEqual(self.client.post("/auth/presence/validate", headers=pheaders).status_code, 401)

    def test_oauth_and_api_mint_are_session_bound(self):
        response = self.client.post("/oauth2/token", data={"username": "member@phase1.example.com", "password": "fixture-password"})
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["access_token"]
        self.assertEqual(self.access({"access_token": token}).status_code, 200)
        self.change_user("member", status=m.UserStatusEnum.DEACTIVATED)
        self.assertEqual(self.access({"access_token": token}).status_code, 401)
        response = self.client.post("/auth/generate-token", headers=self.headers("owner"), json={"scopes": [], "expires_in_minutes": 60000})
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["access_token"]
        self.assertGreater(decode_token_claims(token)["exp"]-int(time.time()), 59999*60)
        self.change_user("owner", hashed_password=hash_password("rotated-owner"))
        self.assertEqual(self.access({"access_token": token}).status_code, 401)

    def test_backend_socket_admission_and_delivery_recheck_session(self):
        pair = self.login()
        socket_fixture = SimpleNamespace(state=SimpleNamespace(auth_claims=decode_token_claims(pair["access_token"])))
        with Session(engine) as db:
            self.assertTrue(bind_socket(socket_fixture, db.get(m.User, self.ids["member"]), db, ("tasks.list",)))
        self.assertTrue(socket_allowed(socket_fixture, ("tasks.list",)))
        self.client.post("/auth/logout", headers={"Authorization": "Bearer " + pair["access_token"]})
        self.assertFalse(socket_allowed(socket_fixture, ("tasks.list",)))

    def test_same_user_socket_sessions_are_authorized_separately(self):
        first, second = self.login(), self.login()
        class Socket:
            def __init__(self, token):
                self.state = SimpleNamespace(auth_claims=decode_token_claims(token))
                self.messages, self.closed = [], False
            async def send_json(self, message):
                self.messages.append(message)
            async def close(self, code):
                self.closed = True
        sockets = [Socket(pair["access_token"]) for pair in (first, second)]
        for socket_fixture in sockets:
            with Session(engine) as db:
                self.assertTrue(bind_socket(socket_fixture, db.get(m.User, self.ids["member"]), db, task_ws.TASK_PAGES))
        manager = task_ws.TaskConnectionManager()
        manager._connections[str(self.tenant)] = set(sockets)
        self.client.post("/auth/logout", headers={"Authorization": "Bearer " + first["access_token"]})
        asyncio.run(manager.broadcast(str(self.tenant), {"type": "task.changed", "task_id": "assigned"}))
        self.assertTrue(sockets[0].closed)
        self.assertEqual(sockets[0].messages, [])
        self.assertFalse(sockets[1].closed)
        self.assertEqual(sockets[1].messages[0]["task_id"], "assigned")

    def test_backup_registry_cannot_export_or_restore_session_state(self):
        from app.backups.registry import EXCLUDED, FIELDS, OMITTED_FIELDS
        from app.backups.service import catalog
        self.assertTrue({"auth_sessions", "auth_refresh_tokens"} <= EXCLUDED)
        self.assertNotIn("auth_epoch", FIELDS["users"].split())
        self.assertIn("auth_epoch", OMITTED_FIELDS["users"])
        with Session(engine) as db:
            unknown = catalog(db, self.tenant)["unregistered_tables"]
        self.assertNotIn("auth_sessions", unknown)
        self.assertNotIn("auth_refresh_tokens", unknown)
        self.assertNotIn("users.auth_epoch", unknown)

    def test_cleanup_preserves_unexpired_replay_evidence(self):
        pair = self.login()
        self.refresh(pair)
        with Session(engine) as db:
            self.assertEqual(auth_sessions.cleanup_expired(db), 0)
            session = db.get(AuthSession, decode_token_claims(pair["access_token"])["sid"])
            session.created_at = auth_sessions.now()-timedelta(days=40)
            session.expires_at = auth_sessions.now()-timedelta(days=31)
            db.commit()
            self.assertEqual(auth_sessions.cleanup_expired(db), 1)
            db.commit()
            self.assertEqual(db.scalar(select(func.count()).select_from(AuthRefreshToken)
                             .where(AuthRefreshToken.session_id == decode_token_claims(pair["access_token"])["sid"])), 0)

    def test_isolation_guards(self):
        with self.assertRaises(RuntimeError):
            psycopg2.connect(host="127.0.0.1", port=7432, dbname="postgres")
        with self.assertRaises(RuntimeError):
            create_engine("sqlite:///:memory:").connect()
        with socket.socket() as connection, self.assertRaises(RuntimeError):
            connection.connect(("127.0.0.1", 7211))


class BusinessRegressions(PGFixture):
    pass


# Unchanged domain assertions; obsolete stateless-token assumptions are excluded
# explicitly and replaced by SessionTests. Execute these against PostgreSQL too.
for name, method in vars(Phase11).items():
    if name.startswith("test_") and (name.startswith(("test_group", "test_ordinary", "test_manager", "test_empty",
            "test_nested", "test_foreign", "test_shared", "test_creator", "test_staff", "test_assignee", "test_authorized",
            "test_multi", "test_proxy", "test_subresources")) or name in {
            "test_ticket_subresource_role_matrix", "test_ticket_creation_linked_task_and_status_workflows",
            "test_ticket_task_dependencies_and_foreign_creators_are_filtered", "test_ticket_denial_precedes_linked_task_and_log_queries",
            "test_ticket_participant_access_filters_individually_invisible_tasks", "test_ticket_follower_and_pending_approver_access",
            "test_task_notification_inbox_rechecks_assignment_access"}):
        setattr(BusinessRegressions, name, method)


def main():
    if replica:
        data = json.loads(Path(os.environ["ZEA_PHASE13_INTEROP"]).read_text())
        with TestClient(build_app()) as client:
            for token in data["revoked_access"]:
                assert client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401
            assert client.post("/auth/refresh", json={"refresh_token": data["revoked_refresh"]}).status_code == 401
            assert client.get("/auth/me", headers={"Authorization": "Bearer " + data["access"]}).status_code == 200
        print("PASS: independent fresh backend process observes durable revocation and valid sessions")
        return 0
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(SessionTests),
                               unittest.defaultTestLoader.loadTestsFromTestCase(BusinessRegressions)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    fixture = PGFixture()
    fixture.setUp()
    try:
        revoked = fixture.login()
        refreshed = fixture.refresh(revoked).json()
        fixture.client.post("/auth/logout", headers={"Authorization": "Bearer " + refreshed["access_token"]})
        active = fixture.login()
        presence = fixture.client.get("/auth/presence-token", headers={"Authorization": "Bearer " + active["access_token"]}).json()["access_token"]
        Path(os.environ["ZEA_PHASE13_INTEROP"]).write_text(json.dumps({
            "secret": settings.jwt_secret_key, "presence": presence, "access": active["access_token"],
            "refresh": active["refresh_token"], "revoked_refresh": refreshed["refresh_token"],
            "revoked_access": [revoked["access_token"], refreshed["access_token"]]}))
    finally:
        fixture.doCleanups()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
