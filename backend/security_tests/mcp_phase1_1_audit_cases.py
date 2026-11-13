"""Independent expectations over real handlers; no installed startup or services.

Reuse only fixture setup/helpers, explicitly select these audit tests and isolation
controls. Diagnostic success records observed behavior, not a passing security gate.
"""
from pathlib import Path
import runpy
import unittest

fixture = runpy.run_path(str(Path(__file__).with_name("mcp_phase1_1_cases.py")))

import json  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402
from unittest.mock import patch  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from jose import jwt  # noqa: E402
from backend.app import models as m  # noqa: E402
from backend.app.auth import decode_token, hash_password  # noqa: E402
from backend.app.dependencies import _decode_access_token  # noqa: E402
from backend.app.services import subtask_rewards, subtasks  # noqa: E402
from backend.app.tickets.models import XpLedger  # noqa: E402

observations = []


def observe(criterion, result, evidence):
    observations.append({"criterion": criterion, "result": result, "evidence": evidence})


class IndependentAudit(unittest.TestCase):
    setUp = fixture["Phase11"].setUp
    headers = fixture["Phase11"].headers
    request = fixture["Phase11"].request
    change_user = fixture["Phase11"].change_user
    token = fixture["Phase11"].token

    def test_direct_sibling_mutations_are_denied_without_dml(self):
        writes = []
        def capture(conn, cursor, sql, params, context, many):
            if sql.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")):
                writes.append(sql)
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            for prefix in ("", "/api"):
                for method, suffix, data in [
                    ("PATCH", "", {"title": "denied", "status": "DONE"}),
                    ("POST", "/complete", None),
                    ("DELETE", "", None),
                    ("PATCH", "/subtasks/sibling-child", {"completed": True}),
                ]:
                    response = self.request(method, prefix + "/tasks/sibling" + suffix, json=data)
                    self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual(writes, [])
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

    def test_cross_tenant_group_collision_never_expands_or_updates_foreign_row(self):
        with Session(self.engine) as db:
            db.get(m.Task, "foreign-task").task_group_id = "shared"
            db.commit()
        for prefix in ("", "/api"):
            response = self.request("GET", prefix + "/tasks/assigned/group", name="owner")
            self.assertEqual(response.status_code, 200)
            self.assertEqual({row["id"] for row in response.json()}, {"assigned", "sibling"})
            response = self.request("PATCH", prefix + "/tasks/assigned", name="owner",
                                    json={"title": "permitted shared edit"})
            self.assertEqual(response.status_code, 200, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(m.Task, "foreign-task").title, "foreign-task")

    def test_permission_removal_applies_immediately_to_group_and_ticket_expansions(self):
        with Session(self.engine) as db:
            sibling = db.get(m.Task, "sibling")
            sibling.followers.append(db.get(m.User, self.ids["member"]))
            db.commit()
        self.assertEqual(len(self.request("GET", "/tasks/assigned/group").json()), 2)
        with Session(self.engine) as db:
            sibling = db.get(m.Task, "sibling")
            sibling.followers.clear()
            db.commit()
        self.assertEqual({row["id"] for row in self.request("GET", "/tasks/assigned/group").json()}, {"assigned"})
        self.assertEqual(self.request("GET", "/tasks/sibling").status_code, 403)
        self.assertEqual(self.request("GET", f"/tickets/{self.tickets[0]}/logs", name="admin").status_code, 200)
        self.change_user("admin", role=m.RoleEnum.USER)
        for suffix in ("tasks", "logs"):
            self.assertEqual(self.request("GET", f"/tickets/{self.tickets[0]}/{suffix}", name="admin").status_code, 403)

    def test_signature_algorithm_and_type_confusion_denied_by_both_decoders(self):
        claims = {"sub": self.ids["member"], "tenant_id": str(self.tenant),
                  "token_type": "access", "exp": int(time.time()) + 300}
        settings = fixture["base"]["settings"]
        wrong_key = jwt.encode(claims, "synthetic-untrusted-signing-key", algorithm="HS256")
        wrong_algorithm = jwt.encode(claims, settings.jwt_secret_key, algorithm="HS512")
        for token in (wrong_key, wrong_algorithm, self.token(token_type="refresh"),
                      self.token(exp="OMIT"), self.token(exp=int(time.time())),
                      self.token(exp=float(time.time()) + 300)):
            with self.assertRaises(ValueError):
                decode_token(token)
            with self.assertRaises(HTTPException) as denial:
                _decode_access_token(token)
            self.assertEqual(denial.exception.status_code, 401)
        self.assertEqual(decode_token(self.token()).sub, self.ids["member"])

    def test_form_login_refresh_reuse_and_invalid_credentials(self):
        self.change_user("member", hashed_password=hash_password("independent-fixture-password"))
        for prefix in ("", "/api"):
            self.assertEqual(self.client.post(prefix + "/auth/login", data={
                "username": "member@phase1.example.com", "password": "wrong"}).status_code, 401)
            login = self.client.post(prefix + "/auth/login", data={
                "username": "member@phase1.example.com", "password": "independent-fixture-password"})
            self.assertEqual(login.status_code, 200)
            tokens = login.json()["token"]
            for _ in range(2):
                refresh = self.client.post(prefix + "/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
                self.assertEqual(refresh.status_code, 200)
                response = self.client.get(prefix + "/tasks/assigned/summary",
                    headers={"Authorization": "Bearer " + refresh.json()["access_token"]})
                self.assertEqual(response.status_code, 200)

    def test_logout_and_reactivation_measure_unimplemented_revocation(self):
        access, refresh = self.headers(), self.token(refresh=True)
        self.assertEqual(self.client.post("/auth/logout", headers=access).status_code, 204)
        self.assertEqual(self.client.get("/tasks/assigned/summary", headers=access).status_code, 200)
        self.change_user("member", status=m.UserStatusEnum.DEACTIVATED)
        self.assertEqual(self.client.get("/tasks/assigned/summary", headers=access).status_code, 403)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": refresh}).status_code, 403)
        self.change_user("member", status=m.UserStatusEnum.ACTIVE)
        self.assertEqual(self.client.get("/tasks/assigned/summary", headers=access).status_code, 200)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": refresh}).status_code, 200)
        observe(10, "BLOCKED", "No explicit durable revoke operation exists; logout204 then old access200; inactive403; reactivated old access/refresh200. Explicitly revoked-token test NOT RUN.")

    def test_refresh_token_tenant_binding_after_account_move(self):
        access, refresh = self.headers(), self.token(refresh=True)
        self.change_user("member", tenant_id=self.foreign)
        self.assertEqual(self.client.get("/tasks/assigned/summary", headers=access).status_code, 401)
        for prefix in ("", "/api"):
            response = self.client.post(prefix + "/auth/refresh", json={"refresh_token": refresh})
            self.assertEqual(response.status_code, 200)
            new_access = response.json()["access_token"]
            self.assertEqual(_decode_access_token(new_access)["tenant_id"], str(self.foreign))
            with Session(self.engine) as db:
                # This is legitimate membership in the new tenant, not an arbitrary
                # foreign-row read. The defect is accepting the OLD tenant credential.
                db.get(m.Task, "foreign-task").assigned_to_id = self.ids["member"]
                db.commit()
            self.assertEqual(self.client.get(prefix + "/tasks/foreign-task/summary",
                headers={"Authorization": "Bearer " + new_access}).status_code, 200)
        observe(7, "FAIL", "Old-tenant access rejected401 but old-tenant refresh accepted200 and issues usable new-tenant access, on both aliases.")

    def test_main_task_completion_rewards_once_and_keeps_sibling_unchanged(self):
        with Session(self.engine) as db:
            db.add(m.PointsTableConfig(id=1))
            task = db.get(m.Task, "assigned")
            task.priority = m.TaskPriorityEnum.HIGH
            task.due_at = datetime(2100, 1, 1)
            for name in ("member", "peer"):
                db.get(m.User, self.ids[name]).points = 100
            db.commit()
        for prefix in ("", "/api"):
            response = self.request("POST", prefix + "/tasks/assigned/complete")
            self.assertEqual(response.status_code, 200, response.text)
        with Session(self.engine) as db:
            user = db.get(m.User, self.ids["member"])
            self.assertEqual((user.points, user.tasks_completed), (145, 1))
            self.assertEqual(db.get(m.User, self.ids["peer"]).points, 100)
            self.assertEqual(db.get(m.Task, "sibling").status.value, "TODO")
            self.assertEqual(list(db.scalars(select(XpLedger))), [])

    def test_group_priority_reconciles_only_authorized_reward_balances(self):
        with self.engine.connect() as connection, Session(connection) as db:
            db.add(m.PointsTableConfig(id=1))
            owner = db.get(m.User, self.ids["owner"])
            owner.timezone = "UTC"
            for task_id, name in (("assigned", "member"), ("sibling", "peer")):
                db.get(m.User, self.ids[name]).points = 100
                db.get(m.Task, task_id).priority = m.TaskPriorityEnum.HIGH
            db.commit()
            subtask_rewards.configure(db, actor=owner, enabled=True, expected_version=0)
            db.commit()
            for task_id in ("assigned", "sibling"):
                children = [subtasks.create(db, actor_id=owner.id, task_id=task_id, data={
                    "title": "audit managed child " + str(index), "planned_start_date": "2026-11-02",
                    "planned_end_date": "2026-11-02"}) for index in range(2)]
                child = children[1]
                for data in ({"action": "START"}, {"actual_start_at": "2026-11-02T00:00:00Z",
                             "actual_end_at": "2026-11-02T12:00:00Z", "confirm_actual_times": True},
                             {"action": "COMPLETE"}):
                    child = subtasks.edit(db, actor_id=owner.id, task_id=task_id,
                        subtask_id=child.id, data={"expected_version": child.version, **data})
                db.commit()
            self.assertEqual([db.get(m.User, self.ids[name]).points for name in ("member", "peer")], [145, 145])
        self.assertEqual(self.request("PATCH", "/tasks/assigned", json={"priority": "LOW"}).status_code, 403)
        with Session(self.engine) as db:
            self.assertEqual([db.get(m.User, self.ids[name]).points for name in ("member", "peer")], [145, 145])
            self.assertEqual(len(list(db.scalars(select(XpLedger)))), 4)
        response = self.request("PATCH", "/api/tasks/assigned", name="owner", json={"priority": "LOW"})
        self.assertEqual(response.status_code, 200, response.text)
        with Session(self.engine) as db:
            self.assertEqual([db.get(m.User, self.ids[name]).points for name in ("member", "peer")], [115, 115])
            entries = list(db.scalars(select(XpLedger)))
            self.assertEqual(sum(row.points for row in entries), 30)
            self.assertEqual({row.task_id for row in entries}, {"assigned", "sibling"})

    def test_transfer_request_and_decision_reconcile_only_anchor(self):
        # Both modified transfer call sites execute real reconciliation. This is
        # compatibility coverage, not certification of the unresolved S01 policy.
        with patch.object(subtask_rewards, "reconcile", wraps=subtask_rewards.reconcile) as calls:
            response = self.request("POST", "/tasks/assigned/transfer-requests",
                                    json={"to_user_id": self.ids["watcher"]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "pending")
            request_id = response.json()["id"]
            response = self.request("POST", f"/api/tasks/transfer-requests/{request_id}/approve",
                                    name="owner", json={"decision": "approved"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "approved")
            self.assertEqual([call.kwargs["task_id"] for call in calls.call_args_list],
                             ["assigned", "assigned"])
        with Session(self.engine) as db:
            self.assertEqual(db.get(m.Task, "assigned").assigned_to_id, self.ids["watcher"])
            self.assertEqual(db.get(m.Task, "sibling").assigned_to_id, self.ids["peer"])


if __name__ == "__main__":
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(fixture["IsolationControls"]),
        unittest.defaultTestLoader.loadTestsFromTestCase(IndependentAudit),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for item in observations:
        print("AUDIT_GATE " + json.dumps(item, sort_keys=True))
    raise SystemExit(1 if not result.wasSuccessful() else 2 if any(
        item["result"] in {"FAIL", "BLOCKED"} for item in observations) else 0)
