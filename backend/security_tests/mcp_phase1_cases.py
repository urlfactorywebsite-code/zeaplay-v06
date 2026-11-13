"""Focused real-router checks. Execute through run_mcp_phase1.py only.

Diagnostic observations report current group/ticket/token gaps as FAIL gates,
separately from passing fixture/regression checks. They do not approve business
rules or silently bless current disclosure as the desired authorization policy.
"""
import importlib.abc
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import socket
import sys
import threading
import unittest
import uuid
from unittest.mock import patch


if (os.environ.get("ZEA_PHASE1_ISOLATED") != "memory-only"
        or os.environ.get("VEE_DATABASE_URL") != "sqlite:///:memory:"
        or len(sys.argv) != 2):
    raise RuntimeError("Use run_mcp_phase1.py; isolation must precede application imports")

repository = Path(sys.argv.pop()).resolve()
if list(Path.cwd().iterdir()) or Path.cwd() == repository:
    raise RuntimeError("Expected an empty disposable working directory")
sys.path.insert(0, str(repository))


class DenyUnsafeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if (fullname in {"backend.app.main", "app.main"}
                or fullname.startswith(("backend.tests", "alembic"))):
            raise RuntimeError("Installed startup, legacy tests and migrations are forbidden")


sys.meta_path.insert(0, DenyUnsafeImports())

# Windows asyncio creates a private loopback socketpair for wakeups. Permit
# only connections made synchronously inside Python's socketpair constructor;
# an application connection to any installed loopback service is still denied.
socketpair_context = threading.local()
original_socketpair = socket.socketpair


def event_loop_socketpair(*args, **kwargs):
    socketpair_context.active = True
    try:
        return original_socketpair(*args, **kwargs)
    finally:
        socketpair_context.active = False


socket.socketpair = event_loop_socketpair


def deny_external_io(event, args):
    if event == "sqlite3.connect" and args[0] != ":memory:":
        raise RuntimeError("Only in-memory SQLite connections are allowed")
    if (event == "socket.bind" and getattr(socketpair_context, "active", False)
            and isinstance(args[1], tuple) and args[1][0] in {"127.0.0.1", "::1"}
            and args[1][1] == 0):
        return
    if (event == "socket.connect" and getattr(socketpair_context, "active", False)
            and isinstance(args[1], tuple) and args[1][0] in {"127.0.0.1", "::1"}):
        return
    if event in {"socket.connect", "socket.bind", "socket.sendto", "socket.getaddrinfo",
                 "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
                 "subprocess.Popen", "os.system"}:
        raise RuntimeError("External network/process activity is forbidden in Phase 1 tests")


sys.addaudithook(deny_external_io)

from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.engine import Dialect, Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402


@event.listens_for(Dialect, "do_connect")
def memory_database_only(dialect, record, args, kwargs):
    if dialect.name != "sqlite" or not args or args[0] != ":memory:":
        raise RuntimeError("Only in-memory SQLite connections are allowed")


@event.listens_for(Engine, "connect")
def search_ddl_compatibility(connection, record):
    if not isinstance(connection, sqlite3.Connection):
        raise RuntimeError("Unexpected database connection")
    # DDL compatibility only; no PostgreSQL full-text search certification.
    connection.create_function("to_tsvector", 2, lambda language, value: value, deterministic=True)


# Resolve/verify settings before the first database or router import.
from backend.app.config import get_settings  # noqa: E402

settings = get_settings()
if (settings.database_url != "sqlite:///:memory:" or settings.redis_url
        or settings.cache_redis_url or settings.enable_n8n_forwarding):
    raise RuntimeError("Unsafe fixture settings")
print("ISOLATION PASS: empty scratch cwd; memory DB only; external IO/startup/legacy tests denied", flush=True)

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.exceptions import ResponseValidationError  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from jose import jwt  # noqa: E402
from backend.app import models as m  # noqa: E402
from backend.app.auth import create_access_token  # noqa: E402
from backend.app.database import Base, get_db  # noqa: E402
from backend.app.navigation_guard import enforce_navigation_policy  # noqa: E402
from backend.app.routers import tasks  # noqa: E402
from backend.app.services import audit_logger, task_events  # noqa: E402
from backend.app.tickets import models as tm, router as tickets, workflow_router  # noqa: E402


SECURITY_GATES = []


def record_security_gate(identifier, target, *, gap_observed, evidence):
    SECURITY_GATES.append({"finding": identifier, "target": target,
                           "result": "FAIL" if gap_observed else "PASS",
                           "evidence": evidence})


class IsolationControls(unittest.TestCase):
    def test_direct_sqlite_connections_cannot_bypass_engine_guard(self):
        with self.assertRaisesRegex(RuntimeError, "Only in-memory"):
            sqlite3.connect("direct-must-not-exist.db")
        self.assertFalse(Path("direct-must-not-exist.db").exists())

    def test_file_database_connection_is_refused_before_creation(self):
        engine = create_engine("sqlite:///must-not-exist.db")
        try:
            with self.assertRaisesRegex(RuntimeError, "Only in-memory"):
                engine.connect()
            self.assertFalse(Path("must-not-exist.db").exists())
        finally:
            engine.dispose()

    def test_application_network_connections_are_refused(self):
        with socket.socket() as connection:
            with self.assertRaisesRegex(RuntimeError, "External network"):
                connection.connect(("127.0.0.1", 7211))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            with self.assertRaisesRegex(RuntimeError, "External network"):
                connection.sendto(b"fixture", ("127.0.0.1", 7379))
        with socket.socket() as connection:
            with self.assertRaisesRegex(RuntimeError, "External network"):
                connection.bind(("127.0.0.1", 0))

    def test_installed_startup_and_legacy_test_imports_are_refused(self):
        for name in ("backend.app.main", "backend.tests.test_ticket_tenant_permissions"):
            with self.assertRaisesRegex(RuntimeError, "forbidden"):
                __import__(name)


class Phase1Authorization(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                                    connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.tenant, self.foreign = uuid.uuid4(), uuid.uuid4()
        self.departments = [str(uuid.uuid4()), str(uuid.uuid4())]
        self.ids = {name: str(uuid.uuid4()) for name in
                    ("owner", "member", "peer", "manager", "outside_manager", "foreign", "watcher")}
        self.tickets = [uuid.uuid4(), uuid.uuid4()]
        # Only transport publication is suppressed. Identity, navigation, object
        # checks, ORM queries and serialization all use production code.
        self.publication = patch.object(task_events, "publish_task_event", return_value=None)
        self.publication.start()
        self.addCleanup(self.publication.stop)
        with Session(self.engine) as db:
            db.add_all([m.Department(id=value, name=f"Department {i}")
                        for i, value in enumerate(self.departments)])
            for name, identifier in self.ids.items():
                role = (m.RoleEnum.OWNER if name in {"owner", "foreign"} else
                        m.RoleEnum.MANAGER if "manager" in name else m.RoleEnum.USER)
                db.add(m.User(id=identifier, tenant_id=self.foreign if name == "foreign" else self.tenant,
                              email=f"{name}@phase1.example.com", name=name,
                              hashed_password="unused-fixture-hash", role=role,
                              status=m.UserStatusEnum.ACTIVE,
                              department_id=self.departments[1 if name == "outside_manager" else 0]))
            db.flush()
            for task_id, creator, assignee, group in [
                ("assigned", "owner", "member", "shared"),
                ("sibling", "owner", "peer", "shared"),
                ("foreign-task", "foreign", "foreign", "foreign-group"),
            ]:
                db.add(m.Task(id=task_id, title=task_id, created_by_id=self.ids[creator],
                              assigned_to_id=self.ids[assignee], task_group_id=group,
                              due_at=datetime(2020, 1, 1) if task_id == "assigned" else None))
            db.flush()
            assigned_task = db.get(m.Task, "assigned")
            assigned_task.followers.append(db.get(m.User, self.ids["watcher"]))
            db.add_all([m.Subtask(id="assigned-child", task_id="assigned", title="Visible child"),
                        m.Subtask(id="sibling-child", task_id="sibling", title="Private sibling child")])
            db.add_all([tm.Ticket(id=self.tickets[0], tenant_id=self.tenant,
                                 title="Own tenant ticket", description="Synthetic fixture", created_by=self.ids["member"],
                                 owner_id=self.ids["member"], department_id=uuid.UUID(self.departments[0])),
                        tm.Ticket(id=self.tickets[1], tenant_id=self.foreign,
                                  title="Foreign ticket", description="Synthetic fixture", created_by=self.ids["foreign"],
                                  owner_id=self.ids["foreign"])])
            db.flush()
            db.add(m.Task(id="ticket-private", title="Private linked task", ticket_id=self.tickets[0],
                          created_by_id=self.ids["member"], assigned_to_id=self.ids["member"],
                          task_group_id="ticket-only"))
            db.add(tm.TicketAuditLog(tenant_id=self.tenant, ticket_id=self.tickets[0],
                                     actor_user_id=self.ids["member"], event_type="fixture.private",
                                     created_at_utc=datetime.now(timezone.utc),
                                     summary="Synthetic private ticket audit"))
            db.commit()
        self.app = FastAPI(dependencies=[Depends(enforce_navigation_policy)])
        for router in (tasks.router, tickets.router):
            self.app.include_router(router)
            self.app.include_router(router, prefix="/api")
        # Match main.py's registration order without importing its lifecycle.
        self.app.include_router(workflow_router.router)

        def session():
            with Session(self.engine) as db:
                yield db

        self.app.dependency_overrides[get_db] = session
        # No TestClient context manager: no lifespan/startup execution.
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def headers(self, name="member", **claims):
        tenant = self.foreign if name == "foreign" else self.tenant
        return {"Authorization": "Bearer " + create_access_token(
            self.ids[name], expires_minutes=5,
            extra_claims={"tenant_id": str(tenant), **claims})}

    def request(self, method, path, *, name="member", **kwargs):
        return self.client.request(method, path, headers=self.headers(name), **kwargs)

    def test_cross_tenant_task_read_and_write_denied_on_both_aliases(self):
        for prefix in ("", "/api"):
            for method, suffix, body in [("GET", "/summary", None), ("PATCH", "", {"title": "Denied"})]:
                with self.subTest(prefix=prefix, method=method):
                    response = self.request(method, f"{prefix}/tasks/foreign-task{suffix}", json=body)
                    self.assertEqual(response.status_code, 404, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(m.Task, "foreign-task").title, "foreign-task")

    def test_cross_tenant_assignment_denied_on_both_aliases(self):
        for prefix in ("", "/api"):
            response = self.request("PATCH", f"{prefix}/tasks/assigned", name="owner",
                                    json={"assigned_to_id": self.ids["foreign"]})
            self.assertEqual(response.status_code, 404, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(m.Task, "assigned").assigned_to_id, self.ids["member"])

    def test_group_id_does_not_grant_direct_or_list_sibling_access(self):
        for prefix in ("", "/api"):
            own = self.request("GET", f"{prefix}/tasks/assigned/summary")
            sibling = self.request("GET", f"{prefix}/tasks/sibling/summary")
            listing = self.request("GET", f"{prefix}/tasks/page")
            self.assertEqual(own.status_code, 200, own.text)
            self.assertEqual(sibling.status_code, 403, sibling.text)
            self.assertEqual(listing.status_code, 200, listing.text)
            self.assertEqual({row["id"] for row in listing.json()["items"]}, {"assigned", "ticket-private"})
        # /group's broader behavior is S05, deliberately not asserted as policy.

    def test_manager_department_scope_and_ordinary_user_boundary(self):
        for prefix in ("", "/api"):
            for name, expected in [("member", 403), ("manager", 200), ("outside_manager", 403)]:
                with self.subTest(prefix=prefix, name=name):
                    response = self.request("GET", f"{prefix}/tasks/sibling/summary", name=name)
                    self.assertEqual(response.status_code, expected, response.text)

    def test_unrelated_user_cannot_patch_even_with_group_id(self):
        for prefix in ("", "/api"):
            response = self.request("PATCH", f"{prefix}/tasks/sibling", json={"title": "Denied"})
            self.assertEqual(response.status_code, 403, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(m.Task, "sibling").title, "sibling")

    def test_ticket_tenant_and_membership_authorization(self):
        for prefix in ("", "/api"):
            for ticket_id, name, expected in [(self.tickets[0], "member", 200),
                                               (self.tickets[0], "peer", 403),
                                               (self.tickets[1], "member", 404)]:
                response = self.request("GET", f"{prefix}/tickets/{ticket_id}", name=name)
                self.assertEqual(response.status_code, expected, response.text)

    def test_deactivation_denies_an_existing_token_while_inactive(self):
        headers = self.headers()
        self.assertEqual(self.client.get("/tasks/assigned/summary", headers=headers).status_code, 200)
        with Session(self.engine) as db:
            db.get(m.User, self.ids["member"]).status = m.UserStatusEnum.DEACTIVATED
            db.commit()
        for prefix in ("", "/api"):
            self.assertEqual(self.client.get(f"{prefix}/tasks/assigned/summary", headers=headers).status_code, 403)
        # This is a live status gate, not persistent token/grant revocation.
        with Session(self.engine) as db:
            db.get(m.User, self.ids["member"]).status = m.UserStatusEnum.ACTIVE
            db.commit()
        self.assertEqual(self.client.get("/tasks/assigned/summary", headers=headers).status_code, 200)

    def test_database_role_overrides_stale_manager_claim(self):
        headers = self.headers("manager", roles=["manager"])
        self.assertEqual(self.client.get("/tasks/sibling/summary", headers=headers).status_code, 200)
        with Session(self.engine) as db:
            db.get(m.User, self.ids["manager"]).role = m.RoleEnum.USER
            db.commit()
        for prefix in ("", "/api"):
            self.assertEqual(self.client.get(f"{prefix}/tasks/sibling/summary", headers=headers).status_code, 403)

    def test_forged_tenant_claim_is_rejected(self):
        headers = self.headers(tenant_id=str(self.foreign))
        for prefix in ("", "/api"):
            self.assertEqual(self.client.get(f"{prefix}/tasks/assigned/summary", headers=headers).status_code, 401)

    def test_observer_cannot_write_activity(self):
        # Explicit service policy already says observers cannot write activity.
        # General parent PATCH/delete are intentionally unresolved S10 cases.
        from fastapi import HTTPException
        with Session(self.engine) as db:
            with self.assertRaises(HTTPException) as caught:
                audit_logger._activity_context(db, self.ids["watcher"], "assigned", write=True)
            self.assertEqual(caught.exception.status_code, 403)
            self.assertEqual(db.scalar(select(m.AuditEvent.id)), None)

    def test_missing_and_expired_bearer_rejected_on_both_aliases(self):
        expired = jwt.encode({"sub": self.ids["member"], "tenant_id": str(self.tenant),
                              "token_type": "access", "exp": 1},
                             settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        for prefix in ("", "/api"):
            path = f"{prefix}/tasks/assigned/summary"
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, headers={"Authorization": "Bearer " + expired}).status_code, 401)

    def test_first_read_candidates_preserve_resource_scope(self):
        for prefix in ("", "/api"):
            for section in ("overview", "subtasks"):
                response = self.request("GET", f"{prefix}/tasks/assigned/information?section={section}")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn("sibling-child", response.text)
                denied = self.request("GET", f"{prefix}/tasks/sibling/information?section={section}")
                self.assertEqual(denied.status_code, 403, denied.text)
                foreign = self.request("GET", f"{prefix}/tasks/foreign-task/information?section={section}")
                self.assertEqual(foreign.status_code, 404, foreign.text)
            overdue = self.request("GET", f"{prefix}/tasks/page?quick_filter=overdue")
            self.assertEqual(overdue.status_code, 200, overdue.text)
            self.assertEqual({row["id"] for row in overdue.json()["items"]}, {"assigned"})

    def test_workload_subject_requires_current_reporting_authority(self):
        for prefix in ("", "/api"):
            self.assertEqual(self.request("GET", f"{prefix}/tasks/activity").status_code, 200)
            for name, target, expected in [("member", "peer", 403),
                                            ("manager", "member", 403),
                                            ("owner", "foreign", 404)]:
                response = self.request("GET", f"{prefix}/tasks/activity?user_id={self.ids[target]}", name=name)
                self.assertEqual(response.status_code, expected, response.text)
        with Session(self.engine) as db:
            db.get(m.User, self.ids["member"]).manager_id = self.ids["manager"]
            db.commit()
        response = self.request("GET", f"/tasks/activity?user_id={self.ids['member']}", name="manager")
        self.assertEqual(response.status_code, 200, response.text)

    def test_group_expansion_diagnostic_records_current_security_gate(self):
        for prefix in ("", "/api"):
            direct = self.request("GET", f"{prefix}/tasks/sibling/summary")
            self.assertEqual(direct.status_code, 403, direct.text)
            path = f"{prefix}/tasks/assigned/group"
            group = self.request("GET", path)
            self.assertIn(group.status_code, (200, 403), group.text)
            returned_ids = {item["id"] for item in group.json()} if group.status_code == 200 else set()
            self.assertNotIn("foreign-task", returned_ids)
            record_security_gate("S05", path, gap_observed="sibling" in returned_ids,
                                 evidence={"direct_sibling_status": direct.status_code,
                                           "group_status": group.status_code,
                                           "denied_sibling_returned": "sibling" in returned_ids})

    def test_ticket_subresources_diagnostic_records_current_security_gate(self):
        ticket_id = self.tickets[0]
        denied = self.request("GET", f"/api/tickets/{ticket_id}", name="peer")
        self.assertEqual(denied.status_code, 403, denied.text)
        for suffix in ("tasks", "logs"):
            path = f"/api/tickets/{ticket_id}/{suffix}"
            if suffix == "tasks":
                # Observe the real query and serializer; do not replace either
                # to manufacture a successful disclosure from a broken route.
                with patch.object(workflow_router, "list_ticket_linked_tasks",
                                  wraps=workflow_router.list_ticket_linked_tasks) as query:
                    try:
                        response = self.request("GET", path, name="peer")
                    except ResponseValidationError as exc:
                        self.assertTrue(any(error["loc"][-1] == "ticket_id" for error in exc.errors()))
                        self.assertEqual(query.call_count, 1)
                        record_security_gate("S03", path, gap_observed=True,
                                             evidence={"parent_status": denied.status_code,
                                                       "subresource_status": 500,
                                                       "unauthorized_query_executed": True,
                                                       "response_validation_error": True,
                                                       "content_disclosure_confirmed": False})
                        continue
            else:
                response = self.request("GET", path, name="peer")
            self.assertIn(response.status_code, (200, 403, 404), response.text)
            leaked = False
            if response.status_code == 200:
                leaked = ("ticket-private" in {row["id"] for row in response.json()}
                          if suffix == "tasks" else
                          any(row["summary"] == "Synthetic private ticket audit"
                              for row in response.json()["items"]))
            record_security_gate("S03", path, gap_observed=leaked,
                                 evidence={"parent_status": denied.status_code,
                                           "subresource_status": response.status_code,
                                           "private_fixture_returned": leaked})

    def test_missing_expiry_diagnostic_records_current_security_gate(self):
        token = jwt.encode({"sub": self.ids["member"], "tenant_id": str(self.tenant),
                            "token_type": "access"},
                           settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        for prefix in ("", "/api"):
            path = f"{prefix}/tasks/assigned/summary"
            response = self.client.get(path, headers={"Authorization": "Bearer " + token})
            self.assertIn(response.status_code, (200, 401), response.text)
            record_security_gate("S07", path, gap_observed=response.status_code == 200,
                                 evidence={"missing_exp_status": response.status_code})


if __name__ == "__main__":
    execution = unittest.main(verbosity=2, exit=False)
    for observation in SECURITY_GATES:
        print("SECURITY_GATE " + json.dumps(observation, sort_keys=True), flush=True)
    if not execution.result.wasSuccessful():
        raise SystemExit(1)
    raise SystemExit(2 if any(item["result"] == "FAIL" for item in SECURITY_GATES) else 0)
