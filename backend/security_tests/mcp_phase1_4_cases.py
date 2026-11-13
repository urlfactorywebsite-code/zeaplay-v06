"""Phase 1.4 HTTP/service and PostgreSQL tests, behind Phase 1.3 IO guards."""
from pathlib import Path
import runpy

base = runpy.run_path(str(Path(__file__).with_name("mcp_phase1_3_cases.py")))
(PGFixture, Session, engine, m, tm, select, func, text, command, config,
 unittest, patch, ThreadPoolExecutor, threading, datetime, timedelta) = (
    base[name] for name in ("PGFixture", "Session", "engine", "m", "tm", "select", "func", "text",
        "command", "config", "unittest", "patch", "ThreadPoolExecutor", "threading", "datetime", "timedelta"))
from fastapi import HTTPException
from app.routers import comments, logs, tasks
from app.services import audit_logger, audit_security, notification_dispatcher as dispatch
from app.tickets import router as tickets, service, workflow_service, approvals_service, schemas as ts
from app.notifications import service as ticket_notices
from sqlalchemy.exc import DBAPIError


class TenantSecurity(PGFixture):
    def setUp(self):
        super().setUp()
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE audit_logs DROP COLUMN tenant_id CASCADE"))
        command.upgrade(config, "m3c5e7f9a1d3")
        for router in (comments.router, logs.router):
            self.app.include_router(router)
            self.app.include_router(router, prefix="/api")

    def req(self, method, path, name="member", **kw):
        return self.client.request(method, path, headers=self.headers(name), **kw)

    def denied(self, response):
        self.assertIn(response.status_code, (400, 403, 404, 409), response.text)

    def transfer(self, name="member", target="peer", task="assigned"):
        return self.req("POST", f"/tasks/{task}/transfer-requests", name,
            json={"to_user_id": self.ids[target], "note": "Fixture transfer"})

    def test_transfers_foreign_inactive_observer_and_department_denied(self):
        for actor in ("member", "owner", "admin", "manager"):
            self.denied(self.transfer(actor, "foreign"))
        for actor in ("watcher", "peer", "outside_manager"):
            self.denied(self.transfer(actor))
        self.change_user("peer", status=m.UserStatusEnum.DEACTIVATED)
        self.denied(self.transfer("owner"))
        self.change_user("manager", department_id=None)
        self.denied(self.transfer("manager", "owner"))
        with Session(engine) as db:
            self.assertEqual(db.get(m.Task, "assigned").assigned_to_id, self.ids["member"])
            self.assertEqual(db.scalar(select(func.count()).select_from(m.TaskTransferRequest)), 0)

    def test_transfer_approval_object_scope_revalidation_and_valid_workflow(self):
        requested = self.transfer()
        self.assertEqual(requested.status_code, 200, requested.text)
        request_id = requested.json()["id"]
        endpoint = f"/tasks/transfer-requests/{request_id}/approve"
        for actor in ("outside_manager", "foreign", "watcher", "peer"):
            self.denied(self.req("POST", endpoint, actor, json={"decision": "approved"}))
        self.change_user("peer", tenant_id=self.foreign)
        self.denied(self.req("POST", endpoint, "owner", json={"decision": "approved"}))
        self.change_user("peer", tenant_id=self.tenant)
        result = self.req("POST", endpoint, "manager", json={"decision": "approved"})
        self.assertEqual(result.status_code, 200, result.text)
        with Session(engine) as db:
            self.assertEqual(db.get(m.Task, "assigned").assigned_to_id, self.ids["peer"])
            self.assertEqual(db.get(m.Task, "sibling").assigned_to_id, self.ids["peer"])
            for notice in db.scalars(select(m.Notification).where(m.Notification.type.in_([m.NotificationTypeEnum.APPROVAL_REQUESTED, m.NotificationTypeEnum.APPROVAL_ACTED]))):
                self.assertEqual(notice.tenant_id, self.tenant)
                self.assertNotIn(notice.user_id, {self.ids["foreign"], self.ids["outside_manager"]})
        self.denied(self.req("POST", endpoint, "owner", json={"decision": "approved"}))

    def test_concurrent_transfer_decisions_only_one_commits(self):
        request_id = self.transfer().json()["id"]
        barrier = threading.Barrier(2)
        def act(actor):
            with Session(engine) as db:
                user = db.get(m.User, self.ids[actor])
                barrier.wait(timeout=10)
                try:
                    tasks.act_on_transfer_request(request_id,
                        base["tasks"].schemas.TaskTransferWorkflowDecision(decision="approved"),
                        None, db, user)
                    return 200
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(act, ["owner", "admin"]))
        self.assertEqual(sorted(results), [200, 409])

    def test_bulk_transfer_preflight_and_staff_success(self):
        endpoint = "/api/tasks/transfer"
        for actor, target in (("owner", "foreign"), ("outside_manager", "peer")):
            self.denied(self.req("POST", endpoint, actor, json={"statuses": ["TODO"], "from_user_id": self.ids["member"], "to_user_id": self.ids[target]}))
        result = self.req("POST", endpoint, "member", json={"statuses": ["TODO"], "from_user_id": self.ids["member"], "to_user_id": self.ids["peer"]})
        self.denied(result)
        # Ticket tasks preserve their stricter creator/assignee writer rule.
        self.denied(self.req("POST", endpoint, "owner", json={"statuses": ["TODO"], "from_user_id": self.ids["member"], "to_user_id": self.ids["peer"]}))
        with Session(engine) as db:
            self.assertEqual(db.get(m.Task, "assigned").assigned_to_id, self.ids["member"])
        result = self.req("POST", endpoint, "admin", json={"statuses": ["TODO"], "from_user_id": self.ids["peer"], "to_user_id": self.ids["member"]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["updated_count"], 1)

    def test_observers_read_but_cannot_edit_delete_or_impersonate(self):
        for prefix in ("", "/api"):
            self.assertEqual(self.req("GET", prefix + "/tasks/assigned", "watcher").status_code, 200)
            self.denied(self.req("PATCH", prefix + "/tasks/assigned", "watcher", json={"description": "forbidden"}))
            self.denied(self.req("DELETE", prefix + "/tasks/assigned", "watcher"))
            for actor in ("owner", "admin", "manager"):
                self.denied(self.req("POST", prefix + "/comments", actor,
                    json={"task_id": "assigned", "user_id": self.ids["member"], "content": "impersonated"}))
            self.denied(self.req("POST", prefix + "/comments", "outside_manager",
                json={"task_id": "assigned", "user_id": self.ids["outside_manager"], "content": "denied"}))
        with patch.object(comments, "trigger_n8n_event"):
            result = self.req("POST", "/comments", "manager", json={"task_id": "assigned", "user_id": self.ids["manager"], "content": "Valid comment"})
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()["user_id"], self.ids["manager"])

    def test_ticket_relationship_create_and_update_reject_all_foreign_fields(self):
        for prefix in ("", "/api"):
            for field in ("owner_id", "assigned_user_id", "followers", "approvers"):
                value = [self.ids["foreign"]] if field in ("followers", "approvers") else self.ids["foreign"]
                response = self.req("POST", prefix + "/tickets", json={"title": "Denied", "description": "Fixture", field: value})
                self.denied(response)
                if field != "followers":
                    self.denied(self.req("PATCH", prefix + f"/tickets/{self.tickets[0]}", json={field: value, "title": "MUST NOT WRITE"}))
        with Session(engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(tm.Ticket)), 2)
            self.assertEqual(db.get(tm.Ticket, self.tickets[0]).title, "Own tenant ticket")

    def test_ticket_participants_approvers_and_active_targets(self):
        ticket_path = f"/tickets/{self.tickets[0]}"
        for actor in ("peer", "outside_manager", "foreign"):
            self.denied(self.req("POST", ticket_path + "/participants", actor,
                json={"add": [{"user_id": self.ids["watcher"], "role": "FOLLOWER"}]}))
        for target in ("foreign", "peer"):
            if target == "peer":
                self.change_user("peer", status=m.UserStatusEnum.DEACTIVATED)
            self.denied(self.req("POST", ticket_path + "/participants", json={"add": [
                {"user_id": self.ids["watcher"], "role": "FOLLOWER"}, {"user_id": self.ids[target], "role": "ASSIGNEE"}]}))
            with Session(engine) as db:
                user = db.get(m.User, self.ids["member"])
                for method in (workflow_service.request_ticket_approval, approvals_service.request_ticket_approvals_sequential):
                    args = dict(tenant_id=self.tenant, ticket_id=self.tickets[0], current_user=user,
                        roles=[user.role.value], approvers=[(self.ids[target], "Review")])
                    if method == workflow_service.request_ticket_approval:
                        args.update(approval_type=tm.TicketApprovalTypeEnum.PARALLEL, deadline_utc=None)
                    with self.assertRaises(HTTPException):
                        method(db, **args)
                    db.rollback()
        self.change_user("peer", status=m.UserStatusEnum.ACTIVE)
        result = self.req("POST", ticket_path + "/participants", json={"add": [{"user_id": self.ids["peer"], "role": "FOLLOWER"}]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.req("GET", ticket_path, "peer").status_code, 200)
        self.assertEqual(self.req("POST", ticket_path + "/participants", json={"remove": [{"user_id": self.ids["peer"], "role": "FOLLOWER"}]}).status_code, 200)
        self.denied(self.req("GET", ticket_path, "peer"))

    def test_default_assignee_is_active_manager_in_ticket_tenant(self):
        self.change_user("foreign", role=m.RoleEnum.MANAGER)
        response = self.req("POST", "/tickets", json={"title": "Default assignment", "description": "Fixture", "department_id": self.departments[0]})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["assigned_user_id"], self.ids["manager"])

    def test_all_approval_entrypoints_reject_foreign_and_valid_cycle_completes(self):
        ticket_path = f"/tickets/{self.tickets[0]}"
        payload = {"approval_type": "PARALLEL", "approvers": [
            {"approver_user_id": self.ids["foreign"], "message": "Review"}]}
        for endpoint in (ticket_path + "/approvals", "/api" + ticket_path + "/approvals/request"):
            self.denied(self.req("POST", endpoint, json=payload))
        with Session(engine) as db:
            user = db.get(m.User, self.ids["member"])
            with self.assertRaises(HTTPException):
                service.request_ticket_approval(db, tenant_id=self.tenant, ticket_id=self.tickets[0], current_user=user,
                    roles=[user.role.value], payload=ts.TicketApprovalRequest(approvers=[self.ids["foreign"]]))
        payload["approvers"][0]["approver_user_id"] = self.ids["manager"]
        requested = self.req("POST", ticket_path + "/approvals", json=payload)
        self.assertEqual(requested.status_code, 201, requested.text)
        cycle_id = requested.json()["id"]
        self.denied(self.req("POST", f"/api/approvals/{cycle_id}/approve", "outside_manager", json={}))
        self.change_user("manager", department_id=self.departments[1])
        self.denied(self.req("POST", f"/api/approvals/{cycle_id}/approve", "manager", json={}))
        self.change_user("manager", department_id=self.departments[0])
        approved = self.req("POST", f"/api/approvals/{cycle_id}/approve", "manager", json={})
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["status"], "APPROVED")

    def test_valid_ticket_edits_and_sequential_approval_preserved(self):
        changed = self.req("PATCH", f"/tickets/{self.tickets[0]}", "owner", json={"title": "Valid edit", "owner_id": self.ids["peer"]})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["assigned_user_id"], self.ids["peer"])
        with Session(engine) as db, patch.object(approvals_service, "get_notifier"):
            member = db.get(m.User, self.ids["member"])
            peer = db.get(m.User, self.ids["watcher"])
            approvals = approvals_service.request_ticket_approvals_sequential(db, tenant_id=self.tenant,
                ticket_id=self.tickets[0], current_user=member, roles=[member.role.value], approvers=[(peer.id, "Review")])
            db.commit()
            service.get_ticket_for_user(db, tenant_id=self.tenant, ticket_id=self.tickets[0], current_user=peer, roles=[peer.role.value])
            acted = approvals_service.act_on_ticket_approval(db, tenant_id=self.tenant, approval_id=approvals[0].id,
                current_user=peer, roles=[peer.role.value], decision="approved", comment=None)
            db.commit()
            self.assertEqual(acted.status, m.ApprovalStatusEnum.APPROVED)

    def test_legacy_ticket_task_observer_write_and_foreign_assignment_denied(self):
        with Session(engine) as db:
            member, watcher = (db.get(m.User, self.ids[name]) for name in ("member", "watcher"))
            db.add(tm.TicketParticipant(tenant_id=self.tenant, ticket_id=self.tickets[0], user_id=watcher.id,
                role=tm.TicketParticipantRoleEnum.FOLLOWER, added_by=member.id))
            db.commit()
            for actor, target in ((watcher, member.id), (member, self.ids["foreign"])):
                with self.assertRaises(HTTPException):
                    workflow_service.create_ticket_task(db, tenant_id=self.tenant, ticket_id=self.tickets[0],
                        current_user=actor, roles=[actor.role.value], payload=ts.TicketTaskCreate(
                            title="Denied", description="Fixture", points=0, assigned_to=target))
                db.rollback()
            task = workflow_service.create_ticket_task(db, tenant_id=self.tenant, ticket_id=self.tickets[0],
                current_user=member, roles=[member.role.value], payload=ts.TicketTaskCreate(
                    title="Valid", description="Fixture", points=0, assigned_to=member.id))
            with self.assertRaises(HTTPException):
                workflow_service.update_ticket_task(db, tenant_id=self.tenant, task_id=task.id, current_user=member,
                    roles=[member.role.value], payload=ts.TicketTaskUpdate(assigned_to=self.ids["foreign"]))
            db.get(tm.TicketTask, task.id).assigned_to = self.ids["foreign"]
            db.commit()
            with self.assertRaises(HTTPException):
                workflow_service.complete_ticket_task(db, tenant_id=self.tenant, task_id=task.id, current_user=member,
                    roles=[member.role.value])
            self.assertEqual(db.get(tm.TicketTask, task.id).status, tm.TicketTaskStatusEnum.OPEN)

    def test_linked_task_approver_and_assignee_tenant_integrity(self):
        from app.tickets import task_engine_service, task_link_service
        with Session(engine) as db:
            user = db.get(m.User, self.ids["member"])
            ticket = db.get(tm.Ticket, self.tickets[0])
            ticket.assigned_user_id = user.id
            db.commit()
            with self.assertRaises(HTTPException):
                task_engine_service.create_ticket_task(db, tenant_id=self.tenant, ticket_id=ticket.id,
                    current_user=user, payload=ts.TicketLinkedTaskCreate(approval_required=True, approver_id=self.ids["foreign"]))
            ticket.owner_id = self.ids["foreign"]
            db.commit()
            with self.assertRaises(HTTPException):
                task_link_service.create_task_for_ticket(db, tenant_id=self.tenant, ticket_id=ticket.id,
                    current_user=user, roles=[user.role.value])

    def test_department_and_role_changes_revoke_cached_ticket_access(self):
        self.assertEqual(len(self.req("GET", "/tickets", "admin").json()["data"]), 1)
        old_headers = self.headers("admin")
        self.change_user("admin", role=m.RoleEnum.USER)
        self.assertEqual(self.client.get("/tickets", headers=old_headers).status_code, 401)
        self.assertEqual(self.req("GET", "/tickets", "admin").json()["data"], [])
        old_headers = self.headers("member")
        self.change_user("member", status=m.UserStatusEnum.DEACTIVATED)
        self.assertEqual(self.client.get("/tickets", headers=old_headers).status_code, 401)

    def test_ticket_cache_never_serves_stale_membership_and_role_payloads(self):
        ticket_path = f"/tickets/{self.tickets[0]}"
        self.req("POST", ticket_path + "/participants", json={"add": [{"user_id": self.ids["peer"], "role": "FOLLOWER"}]})
        self.assertEqual(len(self.req("GET", "/tickets", "peer").json()["data"]), 1)
        with patch.object(tickets, "get_cached_json", create=True, side_effect=AssertionError("payload cache consulted")):
            # Mutation commits in a separate connection, then a concurrent reader
            # must apply the new membership. In-flight authorized reads may finish.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: self.req("POST", ticket_path + "/participants", json={"remove": [{"user_id": self.ids["peer"], "role": "FOLLOWER"}]})).result(timeout=15)
            self.assertEqual(self.req("GET", "/api/tickets", "peer").json()["data"], [])
            self.change_user("manager", department_id=self.departments[1])
            self.assertEqual(self.req("GET", "/tickets", "manager").json()["data"], [])
        with patch.object(tasks, "get_cached_json", side_effect=AssertionError("task cache consulted")):
            for actor in ("owner", "admin", "manager", "member"):
                self.assertEqual(self.req("GET", "/tasks/page", actor).status_code, 200)

    def audit(self, ident, tenant, actor="member", entity="task", entity_id="assigned"):
        return m.AuditLog(id=ident, tenant_id=tenant, actor_id=self.ids[actor], action="FIXTURE_EVENT",
            category=m.AuditLogCategoryEnum.AUTOMATION, entity_type=entity, entity_id=entity_id,
            before={"password": "fixture-secret", "nested": [{"refresh_token": "fixture-token"}]},
            old_value="opaque-fixture-secret")

    def test_audit_list_count_exports_retry_and_retention_are_tenant_scoped(self):
        with Session(engine) as db:
            db.add_all([self.audit("tenant-a", self.tenant), self.audit("tenant-b", self.foreign, "foreign", entity_id="foreign-task"), self.audit("legacy", None)])
            db.commit()
        for actor in ("owner", "admin", "manager"):
            response = self.req("GET", "/logs/audit", actor)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["total"], 1)
            self.assertEqual([item["id"] for item in response.json()["items"]], ["tenant-a"])
            for format in ("json", "csv"):
                export = self.req("GET", f"/api/logs/audit/export?format={format}", actor)
                self.assertEqual(export.status_code, 200, export.text)
                for hidden in ("tenant-b", "legacy", "fixture-secret", "fixture-token"):
                    self.assertNotIn(hidden, export.text)
            self.denied(self.req("POST", "/logs/audit/tenant-b/retry", actor))
        self.assertEqual(self.req("GET", "/logs/audit", "member").status_code, 403)
        self.assertEqual(self.req("GET", "/logs/audit", "outside_manager").json()["total"], 0)
        self.assertEqual(self.req("POST", "/logs/audit/tenant-a/retry", "owner").status_code, 200)
        self.denied(self.req("PATCH", "/logs/retention", "owner", json={"retention_days": 30}))
        with Session(engine) as db:
            for row in db.scalars(select(m.AuditLog)):
                row.created_at = datetime.utcnow() - timedelta(days=365)
            db.commit()
        self.assertEqual(self.req("POST", "/logs/retention/apply", "owner").json()["updated"], 1)
        with Session(engine) as db:
            self.assertIsNone(db.get(m.AuditLog, "tenant-b").deleted_at)
            self.assertIsNone(db.get(m.AuditLog, "legacy").deleted_at)

    def test_audit_attribution_survives_tenant_move_and_cannot_be_overwritten(self):
        with Session(engine) as db:
            user = db.get(m.User, self.ids["member"])
            audit_security.bind_principal(user)
            audit_logger.log_event(audit_logger.AuditLogInput(action="FIXTURE", category=m.AuditLogCategoryEnum.USER,
                actor_id=user.id, metadata={"tenant_id": str(self.foreign), "access_token": "fixture-secret"}))
        payload = self.audit_rows[-1]
        self.assertEqual(payload["tenant_id"], self.tenant)
        self.assertEqual(payload["metadata_payload"]["access_token"], "[REDACTED]")
        self.change_user("member", tenant_id=self.foreign)
        with Session(engine) as db:
            db.add(m.AuditLog(id="immutable", **payload))
            db.commit()
            db.get(m.AuditLog, "immutable").tenant_id = self.foreign
            with self.assertRaises(DBAPIError):
                db.commit()
            db.rollback()
        self.assertEqual(self.req("GET", "/logs/audit", "foreign").json()["total"], 0)
        row = self.req("GET", "/logs/audit", "owner").json()["items"][0]
        self.assertIsNone(row["actor"])

    def test_notifications_hide_legacy_and_currently_unauthorized_resources(self):
        baseline = self.req("GET", "/notifications/inbox").json()
        baseline_ids = {row["id"] for row in baseline["items"]}
        with Session(engine) as db:
            for ident, tenant, kind, obj, task in (
                ("valid", self.tenant, m.NotificationEntityTypeEnum.TICKET, str(self.tickets[0]), None),
                ("foreign", self.foreign, m.NotificationEntityTypeEnum.TICKET, str(self.tickets[1]), None),
                ("forged", self.tenant, m.NotificationEntityTypeEnum.TICKET, str(self.tickets[1]), None),
                ("legacy", None, m.NotificationEntityTypeEnum.TICKET, str(self.tickets[0]), None),
                ("unlinked", self.tenant, None, None, None),
                ("sibling", self.tenant, m.NotificationEntityTypeEnum.TASK, "sibling", None)):
                db.add(m.Notification(id=ident, tenant_id=tenant, user_id=self.ids["member"], type=m.NotificationTypeEnum.TICKET_UPDATED,
                    message="Synthetic sensitive body", entity_type=kind, entity_id=obj, related_task_id=task))
            db.commit()
        response = self.req("GET", "/notifications/inbox")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({row["id"] for row in response.json()["items"]} - baseline_ids, {"valid"})
        self.assertEqual(response.json()["unread_count"], baseline["unread_count"] + 1)
        for ident in ("foreign", "forged", "legacy", "sibling", "unlinked"):
            self.assertEqual(self.req("POST", f"/notifications/{ident}/read").status_code, 404)
            self.assertEqual(self.req("DELETE", f"/notifications/{ident}").status_code, 404)
        self.assertEqual(self.req("POST", "/notifications/valid/read").status_code, 204)

    def test_notifications_require_membership_at_creation_and_delivery(self):
        with Session(engine) as db, patch.object(dispatch, "trigger_n8n_event") as hook, patch.object(dispatch.push_service, "send_push") as push:
            for recipient in ("foreign", "peer", "outside_manager"):
                notice = dispatch.dispatch_notification(db, user_id=self.ids[recipient], actor_id=self.ids["member"],
                    notification_type=m.NotificationTypeEnum.TICKET_UPDATED, message="Private ticket",
                    entity_type=m.NotificationEntityTypeEnum.TICKET, entity_id=str(self.tickets[0]))
                self.assertIsNone(notice)
            hook.assert_not_called()
            push.assert_not_called()
            self.assertIsNone(dispatch.dispatch_notification(db, user_id=self.ids["member"],
                notification_type=m.NotificationTypeEnum.APPROVAL_REQUESTED, message="Unattributed approval"))
            notice = dispatch.dispatch_notification(db, user_id=self.ids["member"], actor_id=self.ids["owner"],
                notification_type=m.NotificationTypeEnum.TICKET_UPDATED, message="Valid ticket",
                entity_type=m.NotificationEntityTypeEnum.TICKET, entity_id=str(self.tickets[0]))
            self.assertIsNotNone(notice)
            self.assertEqual(notice.tenant_id, self.tenant)
            self.assertEqual(hook.call_count, 1)
            db.commit()
            db.get(tm.Ticket, self.tickets[0]).owner_id = self.ids["peer"]
            db.get(tm.Ticket, self.tickets[0]).created_by = self.ids["peer"]
            db.commit()
            dispatch.deliver_stored_notification(db, notice, sound_enabled=False)
            self.assertEqual(hook.call_count, 1)
            context = {"tenant_id": str(self.tenant), "ticket_id": str(self.tickets[0]), "ticket_title": "Private", "actor_name": "Fixture"}
            created = ticket_notices.create_ticket_notifications(db, tenant_id=self.tenant,
                recipient_ids=[self.ids["member"], self.ids["foreign"], self.ids["peer"]], event_type="ticket.updated", context=context, data={})
            self.assertEqual([row.user_id for row in created], [self.ids["peer"]])
            with patch.object(ticket_notices.email_sender, "send_ticket_event_email") as email:
                ticket_notices.send_ticket_emails(db, recipient_ids=[self.ids["member"], self.ids["foreign"], self.ids["peer"]],
                    event_type="ticket.updated", context=context)
                self.assertEqual(email.call_count, 1)
                self.assertEqual(email.call_args.kwargs["to_address"], "peer@phase1.example.com")

    def test_migration_upgrade_downgrade_preserves_legacy_rows_and_user_data(self):
        with Session(engine) as db:
            db.add(self.audit("legacy-preserved", None))
            db.commit()
        command.downgrade(config, "l2b4d6f8a0c2")
        with engine.connect() as conn:
            self.assertEqual(conn.scalar(text("SELECT count(*) FROM audit_logs")), 1)
            self.assertEqual(conn.scalar(text("SELECT count(*) FROM users")), len(self.ids))
        with self.assertRaises(RuntimeError):
            audit_security.require_audit_schema(engine)
        command.upgrade(config, "m3c5e7f9a1d3")
        audit_security.require_audit_schema(engine)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER audit_tenant_immutable"))
        with self.assertRaises(RuntimeError):
            audit_security.require_audit_schema(engine)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER audit_tenant_immutable"))
        with Session(engine) as db:
            self.assertIsNone(db.get(m.AuditLog, "legacy-preserved").tenant_id)
        with engine.connect() as conn:
            self.assertIsNotNone(conn.scalar(text("SELECT to_regclass('ix_audit_logs_tenant_created')")))


class DepartmentBoundaryReview(PGFixture):
    def test_global_department_ownership_is_reproduced_and_blocked(self):
        from app.routers import departments
        self.app.include_router(departments.router)
        first = self.client.get("/departments", headers=self.headers("owner"))
        second = self.client.get("/departments", headers=self.headers("foreign"))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual({row["id"] for row in first.json()}, set(self.departments))
        self.assertEqual(first.json(), second.json())
        print("S04 BLOCKED: both tenants see the global department catalog; diagnostic confirmation is not a security PASS")


if __name__ == "__main__":
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(TenantSecurity),
        unittest.defaultTestLoader.loadTestsFromTestCase(base["BusinessRegressions"]),
        unittest.defaultTestLoader.loadTestsFromTestCase(DepartmentBoundaryReview)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
