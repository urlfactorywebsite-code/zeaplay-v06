"""Independent Phase 1.1 assertions; reuse the unchanged isolation/fixture setup.

Run through run_mcp_phase1_1.py. No startup, real services, file DBs or secrets.
Expected sets/statuses are fixture policy, never computed with production guards.
"""
from pathlib import Path
import runpy
import unittest

# Establish the original import, SQL, network and process guards FIRST.
base = runpy.run_path(str(Path(__file__).with_name("mcp_phase1_cases.py")))
Fixture = base["Phase1Authorization"]
IsolationControls = base["IsolationControls"]

import asyncio  # noqa: E402
import ast  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402
from sqlalchemy import event, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from jose import jwt  # noqa: E402
from backend.app import models as m  # noqa: E402
from backend.app.auth import create_refresh_token, hash_password  # noqa: E402
from backend.app.routers import auth, notifications  # noqa: E402
from backend.app.services import audit_logger  # noqa: E402
from backend.app.services import subtask_rewards  # noqa: E402
from backend.app.tickets import models as tm, workflow_router  # noqa: E402
from backend.app.ws import tasks as task_ws  # noqa: E402
from backend.app.webhooks import service as webhook_service  # noqa: E402


class Phase11(unittest.TestCase):
    headers = Fixture.headers
    request = Fixture.request

    def setUp(self):
        Fixture.setUp(self)
        # Bind request Sessions to their connection: SQLAlchemy introspection in
        # existing services must not close a second handle to StaticPool's one
        # SQLite connection and roll back the request's uncommitted writes.
        def session():
            with self.engine.connect() as connection, Session(connection) as db:
                yield db
        self.app.dependency_overrides[base["get_db"]] = session
        self.app.include_router(workflow_router.read_router)
        for router in (auth.router, notifications.router):
            self.app.include_router(router)
            self.app.include_router(router, prefix="/api")
        self.audit_rows = []
        # Capture the asynchronous general audit sink; domain history remains real.
        # Webhook transport is a sink; it must not open a second Session on the
        # SQLite fixture's single connection during an uncommitted domain write.
        for replacement in (
            patch.object(audit_logger, "queue_log", side_effect=self.audit_rows.append),
            patch.object(webhook_service, "enqueue_event", return_value=None),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.ids["admin"] = str(uuid.uuid4())
        with Session(self.engine) as db:
            db.add(m.User(id=self.ids["admin"], tenant_id=self.tenant,
                          name="admin", email="admin@phase11.example.com",
                          role=m.RoleEnum.ADMIN, status=m.UserStatusEnum.ACTIVE,
                          hashed_password="unused-fixture-hash"))
            db.commit()

    def rows(self, path, *, name="member", expected=200):
        response = self.request("GET", path, name=name)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def change_user(self, name, **values):
        with Session(self.engine) as db:
            user = db.get(m.User, self.ids[name])
            for key, value in values.items():
                setattr(user, key, value)
            db.commit()

    def token(self, *, refresh=False, **changes):
        claims = {"sub": self.ids["member"], "tenant_id": str(self.tenant),
                  "exp": int(time.time()) + 300, "token_type": "refresh" if refresh else "access"}
        for key, value in changes.items():
            if value == "OMIT":
                claims.pop(key, None)
            else:
                claims[key] = value
        settings = base["settings"]
        return jwt.encode(claims, settings.jwt_refresh_secret_key if refresh else settings.jwt_secret_key,
                          algorithm=settings.jwt_algorithm)

    def assert_access_denied(self, token):
        for prefix in ("", "/api"):
            response = self.client.get(f"{prefix}/tasks/assigned/summary",
                                       headers={"Authorization": "Bearer " + token})
            self.assertEqual(response.status_code, 401)

    def test_group_role_matrix_and_independent_direct_denials(self):
        for prefix in ("", "/api"):
            for name, expected in [("member", {"assigned"}), ("watcher", {"assigned"}),
                                   ("owner", {"assigned", "sibling"}),
                                   ("admin", {"assigned", "sibling"}),
                                   ("manager", {"assigned", "sibling"})]:
                with self.subTest(prefix=prefix, name=name):
                    rows = self.rows(f"{prefix}/tasks/assigned/group", name=name)
                    self.assertEqual({row["id"] for row in rows}, expected)
            self.rows(f"{prefix}/tasks/assigned/group", name="outside_manager", expected=403)
            self.rows(f"{prefix}/tasks/assigned/group", name="foreign", expected=404)
            self.rows(f"{prefix}/tasks/sibling/group", expected=403)
            self.rows(f"{prefix}/tasks/sibling", expected=403)

    def test_ordinary_creator_retains_consolidated_group(self):
        self.change_user("owner", role=m.RoleEnum.USER)
        for prefix in ("", "/api"):
            rows = self.rows(f"{prefix}/tasks/assigned/group", name="owner")
            self.assertEqual({row["id"] for row in rows}, {"assigned", "sibling"})

    def test_manager_cannot_expand_outside_department_sibling(self):
        self.change_user("peer", department_id=self.departments[1])
        for prefix in ("", "/api"):
            self.rows(f"{prefix}/tasks/sibling/summary", name="manager", expected=403)
            self.assertEqual({row["id"] for row in self.rows(
                f"{prefix}/tasks/assigned/group", name="manager")}, {"assigned"})

    def test_empty_group_does_not_merge_independent_tasks(self):
        with Session(self.engine) as db:
            for identifier in ("assigned", "sibling"):
                db.get(m.Task, identifier).task_group_id = ""
            db.commit()
        for prefix in ("", "/api"):
            self.assertEqual([r["id"] for r in self.rows(
                f"{prefix}/tasks/assigned/group", name="owner")], ["assigned"])

    def test_nested_dependencies_do_not_disclose_denied_siblings(self):
        with Session(self.engine) as db:
            db.get(m.Task, "assigned").dependencies = [db.get(m.Task, "sibling"), db.get(m.Task, "foreign-task")]
            db.commit()
        for prefix in ("", "/api"):
            for suffix in ("", "/group"):
                data = self.rows(f"{prefix}/tasks/assigned{suffix}")
                own = data[0] if suffix else data
                self.assertEqual(own["dependencies"], [])
                self.assertNotIn("sibling-child", str(data))
                self.assertNotIn(self.ids["peer"], str(data))
                self.assertNotIn("hashed_password", str(data))
            owner = self.rows(f"{prefix}/tasks/assigned", name="owner")
            self.assertEqual([r["id"] for r in owner["dependencies"]], ["sibling"])

    def test_foreign_nested_user_and_followers_are_hidden(self):
        with Session(self.engine) as db:
            task = db.get(m.Task, "assigned")
            task.assigned_to_id = self.ids["foreign"]
            task.followers.append(db.get(m.User, self.ids["foreign"]))
            db.commit()
        data = self.rows("/tasks/assigned/group", name="owner")
        own = next(row for row in data if row["id"] == "assigned")
        self.assertIsNone(own["assignee"])
        self.assertIsNone(own["assigned_to_id"])
        self.assertNotIn(self.ids["foreign"], own["follower_ids"])

    def test_shared_edit_denied_atomically_before_any_write(self):
        statements = []
        def capture(conn, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE ")):
                statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            for prefix in ("", "/api"):
                for fields in ({"title": "Denied", "status": "IN_PROGRESS"},
                               {"description": "Denied"}, {"priority": "HIGH"}):
                    response = self.request("PATCH", f"{prefix}/tasks/assigned", json=fields)
                    self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual(statements, [], "Denied shared edits must precede DML")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        with Session(self.engine) as db:
            self.assertEqual(db.get(m.Task, "assigned").title, "assigned")
            self.assertEqual(db.get(m.Task, "sibling").title, "sibling")

    def test_manager_shared_edit_denied_when_one_peer_is_outside_scope(self):
        self.change_user("peer", department_id=self.departments[1])
        response = self.request("PATCH", "/tasks/assigned", name="manager", json={"title": "Denied"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_creator_shared_edit_preserves_ids_children_and_group(self):
        self.change_user("owner", role=m.RoleEnum.USER)
        for prefix in ("", "/api"):
            response = self.request("PATCH", f"{prefix}/tasks/assigned", name="owner",
                                    json={"title": "Shared title", "description": "Shared description", "priority": "HIGH"})
            self.assertEqual(response.status_code, 200, response.text)
        with Session(self.engine) as db:
            for identifier in ("assigned", "sibling"):
                task = db.get(m.Task, identifier)
                self.assertEqual((task.title, task.description, task.task_group_id),
                                 ("Shared title", "Shared description", "shared"))
                self.assertEqual(task.priority, m.TaskPriorityEnum.HIGH)
                self.assertEqual([child.id for child in task.subtasks], [identifier + "-child"])

    def test_staff_read_does_not_override_ticket_peer_write_restriction(self):
        with Session(self.engine) as db:
            sibling = db.get(m.Task, "sibling")
            sibling.ticket_id = self.tickets[0]
            sibling.created_by_id = self.ids["peer"]
            db.commit()
        self.rows("/tasks/sibling", name="owner")
        response = self.request("PATCH", "/tasks/assigned", name="owner", json={"title": "Denied"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_assignee_status_change_does_not_mutate_sibling(self):
        # A sibling requiring reward-policy reconciliation would fail without a
        # configured policy. An independent status change must never touch it.
        with Session(self.engine) as db:
            db.add(m.TaskWorkflowSettings(tenant_id=self.tenant, enabled=False,
                point_policy_version=subtask_rewards.POLICY, reward_policy_data={},
                activated_at=base["datetime"](2000, 1, 1, tzinfo=base["timezone"].utc)))
            db.flush()
            db.add(m.Subtask(id="sibling-managed", task_id="sibling", title="Archived policy child",
                            point_policy_version=subtask_rewards.POLICY, workflow_version=2,
                            workflow_status="TODO", reward_timezone="UTC",
                            planned_start_date=base["datetime"](2026, 11, 11).date(),
                            planned_end_date=base["datetime"](2026, 11, 12).date()))
            db.commit()
        response = self.request("PATCH", "/api/tasks/assigned", json={"status": "IN_PROGRESS"})
        self.assertEqual(response.status_code, 200, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(m.Task, "assigned").status.value, "IN_PROGRESS")
            self.assertEqual(db.get(m.Task, "sibling").status.value, "TODO")
        history = self.rows("/tasks/assigned/information?section=timeline")
        self.assertNotIn("sibling-child", str(history))

    def test_authorized_staff_shared_edits_still_work(self):
        for name in ("owner", "admin", "manager"):
            response = self.request("PATCH", "/api/tasks/assigned", name=name, json={"title": name})
            self.assertEqual(response.status_code, 200, response.text)
            with Session(self.engine) as db:
                self.assertEqual(db.get(m.Task, "sibling").title, name)

    def test_group_append_requires_write_access_to_all_existing_assignments(self):
        response = self.request("POST", "/tasks", json={"title": "Denied append", "task_group_id": "shared",
                                                        "assigned_to_id": self.ids["member"]})
        self.assertEqual(response.status_code, 403, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(m.Task)), 4)

    def test_multi_assignment_creation_and_task_view_contracts(self):
        response = self.request("POST", "/api/tasks", name="watcher",
                                json={"title": "New group", "assigned_to_ids": [self.ids["member"], self.ids["peer"]]})
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()
        self.assertEqual(len(created), 2)
        self.assertEqual(len({row["id"] for row in created}), 2)
        self.assertEqual(len({row["task_group_id"] for row in created}), 1)
        own = next(row for row in created if row["assigned_to_id"] == self.ids["member"])
        self.assertEqual(len(self.rows(f"/tasks/{own['id']}/group", name="watcher")), 2)
        self.assertEqual(len(self.rows(f"/tasks/{own['id']}/group")), 1)
        for prefix in ("", "/api"):
            page = self.rows(f"{prefix}/tasks/page")
            self.assertIn(own["id"], {row["id"] for row in page["items"]})
            self.assertNotIn("sibling", {row["id"] for row in page["items"]})
            kanban = self.rows(f"{prefix}/tasks/kanban")
            self.assertNotIn('"sibling"', str(kanban).replace("'", '"'))
            self.rows(f"{prefix}/tasks/{own['id']}")

    def test_ticket_subresource_role_matrix(self):
        for prefix in ("", "/api"):
            for suffix in ("tasks", "logs"):
                for name, status in [("member", 200), ("owner", 200), ("admin", 200), ("manager", 200),
                                     ("peer", 403), ("outside_manager", 403), ("foreign", 404)]:
                    with self.subTest(prefix=prefix, suffix=suffix, name=name):
                        self.rows(f"{prefix}/tickets/{self.tickets[0]}/{suffix}", name=name, expected=status)

    def test_ticket_creation_linked_task_and_status_workflows(self):
        for prefix in ("", "/api"):
            created = self.request("POST", f"{prefix}/tickets", json={
                "title": "Workflow fixture", "description": "Ticket creation regression",
                "owner_id": self.ids["member"], "assigned_user_id": self.ids["member"],
                "department_id": self.departments[0]})
            self.assertEqual(created.status_code, 201, created.text)
            ticket_id = created.json()["id"]
            linked = self.request("POST", f"/api/tickets/{ticket_id}/tasks", json={"priority": "MEDIUM"})
            self.assertEqual(linked.status_code, 201, linked.text)
            rows = self.rows(f"{prefix}/tickets/{ticket_id}/tasks")
            self.assertEqual([row["id"] for row in rows], [linked.json()["id"]])
            moved = self.request("POST", f"/api/tickets/{ticket_id}/status", json={"status": "IN_PROGRESS"})
            self.assertEqual(moved.status_code, 200, moved.text)
            self.assertEqual(moved.json()["status"], "IN_PROGRESS")
            blocked = self.request("POST", f"/api/tickets/{ticket_id}/status", json={"status": "RESOLVED"})
            self.assertEqual(blocked.status_code, 400, blocked.text)
            self.assertEqual(blocked.json()["detail"], "TASKS_PENDING")
            logs = self.rows(f"{prefix}/tickets/{ticket_id}/logs")
            self.assertTrue(any(row["event_type"] == "ticket.status_changed" for row in logs["items"]))

    def test_ticket_task_dependencies_and_foreign_creators_are_filtered(self):
        with Session(self.engine) as db:
            task = db.get(m.Task, "ticket-private")
            task.dependencies = [db.get(m.Task, "sibling")]
            db.get(m.Task, "foreign-task").ticket_id = self.tickets[0]
            db.commit()
        for prefix in ("", "/api"):
            rows = self.rows(f"{prefix}/tickets/{self.tickets[0]}/tasks")
            self.assertEqual([row["id"] for row in rows], ["ticket-private"])
            self.assertEqual(rows[0]["dependencies"], [])
            owner_rows = self.rows(f"{prefix}/tickets/{self.tickets[0]}/tasks", name="owner")
            self.assertNotIn("foreign-task", str(owner_rows))

    def test_ticket_denial_precedes_linked_task_and_log_queries(self):
        protected = []
        def capture(conn, cursor, statement, parameters, context, many):
            sql = " ".join(statement.lower().split())
            if "from tasks" in sql or "from ticket_audit_logs" in sql:
                protected.append(sql)
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            for prefix in ("", "/api"):
                for name, expected in [("peer", 403), ("foreign", 404)]:
                    for suffix in ("tasks", "logs"):
                        self.rows(f"{prefix}/tickets/{self.tickets[0]}/{suffix}", name=name, expected=expected)
            self.assertEqual(protected, [])
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

    def test_ticket_participant_access_filters_individually_invisible_tasks(self):
        with Session(self.engine) as db:
            db.add(tm.TicketParticipant(tenant_id=self.tenant, ticket_id=self.tickets[0],
                                        user_id=self.ids["peer"], role=tm.TicketParticipantRoleEnum.ASSIGNEE))
            db.add(m.Task(id="peer-linked", title="Peer linked", created_by_id=self.ids["owner"],
                          assigned_to_id=self.ids["peer"], ticket_id=self.tickets[0]))
            db.commit()
        for prefix in ("", "/api"):
            data = self.rows(f"{prefix}/tickets/{self.tickets[0]}/tasks", name="peer")
            self.assertEqual([row["id"] for row in data], ["peer-linked"])
            self.assertEqual(data[0]["ticket_id"], str(self.tickets[0]))
            self.rows(f"{prefix}/tasks/ticket-private", name="peer", expected=403)
            logs = self.rows(f"{prefix}/tickets/{self.tickets[0]}/logs", name="peer")
            self.assertEqual(logs["total"], 1)
            self.assertEqual(logs["items"][0]["summary"], "Synthetic private ticket audit")

    def test_ticket_follower_and_pending_approver_access(self):
        with Session(self.engine) as db:
            db.add(tm.TicketFollower(tenant_id=self.tenant, ticket_id=self.tickets[0], user_id=self.ids["watcher"]))
            cycle = tm.TicketApprovalCycle(tenant_id=self.tenant, ticket_id=self.tickets[0],
                requested_by=self.ids["member"], status=tm.TicketApprovalCycleStatusEnum.PENDING,
                approval_type=tm.TicketApprovalTypeEnum.SEQUENTIAL, attempts_left=3,
                requested_at_utc=base["datetime"].now(base["timezone"].utc))
            db.add(cycle)
            db.flush()
            db.add(tm.TicketApprovalItem(tenant_id=self.tenant, cycle_id=cycle.id,
                approver_user_id=self.ids["peer"], order_index=1, status=tm.TicketApprovalItemStatusEnum.PENDING))
            db.commit()
        for name in ("watcher", "peer"):
            self.assertEqual(self.rows(f"/api/tickets/{self.tickets[0]}/tasks", name=name), [])
            self.rows(f"/api/tickets/{self.tickets[0]}/logs", name=name)

    def test_ticket_inactive_missing_and_deleted_denials(self):
        self.change_user("member", status=m.UserStatusEnum.DEACTIVATED)
        for prefix in ("", "/api"):
            for suffix in ("tasks", "logs"):
                path = f"{prefix}/tickets/{self.tickets[0]}/{suffix}"
                self.rows(path, expected=403)
                self.assertEqual(self.client.get(path).status_code, 401)
                self.rows(f"{prefix}/tickets/{uuid.uuid4()}/{suffix}", name="owner", expected=404)
        with Session(self.engine) as db:
            db.get(tm.Ticket, self.tickets[0]).deleted_at = base["datetime"].now(base["timezone"].utc)
            db.commit()
        for suffix in ("tasks", "logs"):
            self.rows(f"/tickets/{self.tickets[0]}/{suffix}", name="owner", expected=404)

    def test_subresources_enforce_auth_without_global_navigation_guard(self):
        isolated_app = FastAPI()
        isolated_app.include_router(workflow_router.router)
        isolated_app.dependency_overrides.update(self.app.dependency_overrides)
        client = TestClient(isolated_app)
        self.addCleanup(client.close)
        for suffix in ("tasks", "logs"):
            path = f"/api/tickets/{self.tickets[0]}/{suffix}"
            self.assertEqual(client.get(path).status_code, 401)
            self.assertEqual(client.get(path, headers=self.headers("peer")).status_code, 403)

    def test_proxy_prefix_rewrite_resolves_same_authorized_handlers(self):
        repo = base["repository"]
        nginx = (repo / "frontend/nginx.conf").read_text()
        self.assertIn("location /api/", nginx)
        self.assertIn("proxy_pass http://backend:7211/;", nginx)
        main = ast.parse((repo / "backend/app/main.py").read_text(encoding="utf-8-sig"))
        registrations = [ast.unparse(node) for node in ast.walk(main) if isinstance(node, ast.Call)]
        self.assertIn("app.include_router(tickets_workflow_router.read_router)", registrations)
        # In-process model of this exact proxy URI replacement; no live Nginx claim.
        for suffix in ("tasks", "logs"):
            public = f"/api/tickets/{self.tickets[0]}/{suffix}"
            upstream = public.removeprefix("/api")
            for name in ("member", "peer", "foreign"):
                direct = self.request("GET", public, name=name)
                rewritten = self.request("GET", upstream, name=name)
                self.assertEqual((direct.status_code, direct.json()), (rewritten.status_code, rewritten.json()))

    def test_access_requires_expiration(self):
        self.assert_access_denied(self.token(exp="OMIT"))

    def test_access_rejects_expired_and_malformed_expiration(self):
        for expiry in (1, int(time.time()), None, True, "invalid", "9999999999", [], {}):
            with self.subTest(kind=type(expiry).__name__):
                self.assert_access_denied(self.token(exp=expiry))

    def test_access_requires_exact_type(self):
        for kind in ("OMIT", None, "", "refresh", "bearer", "ACCESS", [], {}):
            self.assert_access_denied(self.token(token_type=kind))

    def test_refresh_rejects_missing_expired_malformed_and_wrong_type(self):
        tokens = [self.token(refresh=True, exp=value) for value in ("OMIT", 1, None, "invalid")]
        tokens += [self.token(refresh=True, token_type=value) for value in ("OMIT", "access", None, "")]
        for token in tokens:
            for prefix in ("", "/api"):
                response = self.client.post(f"{prefix}/auth/refresh", json={"refresh_token": token})
                self.assertEqual(response.status_code, 401)

    def test_real_login_and_refresh_remain_usable(self):
        self.change_user("member", hashed_password=hash_password("phase11-fixture-password"))
        for prefix in ("", "/api"):
            login = self.client.post(f"{prefix}/auth/login", json={"email": "member@phase1.example.com",
                                                                 "password": "phase11-fixture-password"})
            self.assertEqual(login.status_code, 200)  # Never include token responses in failure output.
            token = login.json()["token"]
            refreshed = self.client.post(f"{prefix}/auth/refresh", json={"refresh_token": token["refresh_token"]})
            self.assertEqual(refreshed.status_code, 200)
            for access in (token["access_token"], refreshed.json()["access_token"]):
                resource = self.client.get(f"{prefix}/tasks/assigned/summary", headers={"Authorization": "Bearer " + access})
                self.assertEqual(resource.status_code, 200)

    def test_current_minted_and_presence_tokens_keep_valid_profile(self):
        for prefix in ("", "/api"):
            for method, path, name, body in [("POST", "/auth/generate-token", "owner", {"scopes": ["tasks:read"]}),
                                              ("GET", "/auth/presence-token", "member", None)]:
                response = self.request(method, prefix + path, name=name, json=body)
                self.assertEqual(response.status_code, 200)
                from backend.app.auth import decode_token_claims
                claims = decode_token_claims(response.json()["access_token"])
                self.assertEqual(claims["token_type"], "access")
                self.assertGreater(claims["exp"], time.time())

    def test_task_notification_inbox_rechecks_assignment_access(self):
        with Session(self.engine) as db:
            for task_id in ("assigned", "sibling"):
                db.add(m.Notification(id="notice-" + task_id, user_id=self.ids["member"],
                    tenant_id=self.tenant, type=m.NotificationTypeEnum.TASK_UPDATED,
                    message="Fixture " + task_id, related_task_id=task_id))
            db.commit()
        for prefix in ("", "/api"):
            rows = self.rows(f"{prefix}/notifications")
            self.assertIn("notice-assigned", {row["id"] for row in rows})
            self.assertNotIn("notice-sibling", {row["id"] for row in rows})
            self.assertNotIn("sibling", {row["related_task_id"] for row in rows})

    def test_inactive_user_cannot_login_refresh_or_use_existing_access(self):
        access = self.headers()
        refresh = create_refresh_token(self.ids["member"], extra_claims={"tenant_id": str(self.tenant)})
        self.change_user("member", status=m.UserStatusEnum.DEACTIVATED,
                         hashed_password=hash_password("phase11-fixture-password"))
        for prefix in ("", "/api"):
            self.assertEqual(self.client.get(f"{prefix}/tasks/assigned/summary", headers=access).status_code, 403)
            self.assertEqual(self.client.post(f"{prefix}/auth/refresh", json={"refresh_token": refresh}).status_code, 403)
            self.assertEqual(self.client.post(f"{prefix}/auth/login", json={"email": "member@phase1.example.com",
                             "password": "phase11-fixture-password"}).status_code, 403)

    def test_reactivation_gap_is_explicit_not_claimed_revoked(self):
        access = self.headers()
        refresh = create_refresh_token(self.ids["member"], extra_claims={"tenant_id": str(self.tenant)})
        self.change_user("member", status=m.UserStatusEnum.DEACTIVATED)
        self.assertEqual(self.client.get("/tasks/assigned/summary", headers=access).status_code, 403)
        self.change_user("member", status=m.UserStatusEnum.ACTIVE)
        self.assertEqual(self.client.get("/tasks/assigned/summary", headers=access).status_code, 200)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": refresh}).status_code, 200)
        print("OPEN_RISK S07: reactivation still accepts prior unexpired tokens; durable revocation deferred")

    def test_socket_group_ids_are_filtered_independently_at_delivery(self):
        class Socket:
            def __init__(inner, name):
                inner.state = SimpleNamespace(navigation_identity=(self.ids[name], str(self.tenant)))
                inner.sent = []
            async def send_json(inner, value):
                inner.sent.append(value)
            async def close(inner, **kwargs):
                inner.sent.append("closed")
        member, owner = Socket("member"), Socket("owner")
        manager = task_ws.TaskConnectionManager()
        manager._connections[str(self.tenant)] = {member, owner}
        with patch.object(task_ws, "SessionLocal", lambda: Session(self.engine)), \
             patch.object(task_ws, "socket_allowed", return_value=True):
            for primary, batch in [("assigned", ["assigned", "sibling", "foreign-task"]),
                                    ("sibling", ["assigned", "sibling"])]:
                asyncio.run(manager.broadcast(str(self.tenant), {"type": "task.changed", "task_id": primary,
                    "task_ids": batch, "tenant_id": str(self.tenant), "action": "update"}))
                data = member.sent[-1]
                self.assertEqual(data["task_ids"], ["assigned"])
                self.assertNotIn("sibling", str(data))
                self.assertNotIn("foreign-task", str(owner.sent[-1]))
                self.assertIn("sibling", owner.sent[-1]["task_ids"])


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    for observation in base["SECURITY_GATES"]:
        print("SECURITY_GATE " + json.dumps(observation, sort_keys=True))
    if not result.result.wasSuccessful():
        raise SystemExit(1)
    raise SystemExit(2 if any(item["result"] == "FAIL" for item in base["SECURITY_GATES"]) else 0)
