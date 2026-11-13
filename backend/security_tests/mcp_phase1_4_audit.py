"""Independent adversarial checks; real owned PostgreSQL, no external transports."""
from pathlib import Path
import os
import runpy

scope = runpy.run_path(str(Path(__file__).with_name("mcp_phase1_4_cases.py")))
(TenantSecurity, Session, engine, m, tm, unittest, patch, datetime, HTTPException,
 dispatch, ticket_notices, workflow_service, ts) = (scope[name] for name in (
    "TenantSecurity", "Session", "engine", "m", "tm", "unittest", "patch", "datetime",
    "HTTPException", "dispatch", "ticket_notices", "workflow_service", "ts"))


class IndependentTenantAudit(TenantSecurity):
    setUp = TenantSecurity.setUp
    req = TenantSecurity.req
    denied = TenantSecurity.denied
    transfer = TenantSecurity.transfer

    def test_multiple_ticket_roles_preserve_writer_and_deleted_grants_do_not(self):
        with Session(engine) as db:
            user = db.get(m.User, self.ids["peer"])
            # Insertion order must not turn an ASSIGNEE into a read-only follower.
            follower = tm.TicketParticipant(tenant_id=self.tenant, ticket_id=self.tickets[0],
                user_id=user.id, role=tm.TicketParticipantRoleEnum.FOLLOWER)
            db.add(follower)
            db.commit()
            writer = tm.TicketParticipant(tenant_id=self.tenant, ticket_id=self.tickets[0],
                user_id=user.id, role=tm.TicketParticipantRoleEnum.ASSIGNEE)
            db.add(writer)
            db.commit()
            created = workflow_service.create_ticket_task(db, tenant_id=self.tenant, ticket_id=self.tickets[0],
                current_user=user, roles=[user.role.value], payload=ts.TicketTaskCreate(
                    title="Multiple-role writer", description="Fixture", points=0, assigned_to=user.id))
            self.assertEqual(created.assigned_to, user.id)
            writer.deleted_at = datetime.utcnow()
            db.commit()
            with self.assertRaises(HTTPException) as denied:
                workflow_service.create_ticket_task(db, tenant_id=self.tenant, ticket_id=self.tickets[0],
                    current_user=user, roles=[user.role.value], payload=ts.TicketTaskCreate(
                        title="Revoked writer", description="Fixture", points=0, assigned_to=user.id))
            self.assertEqual(denied.exception.status_code, 403)

    def test_delivery_admission_refreshes_preloaded_demoted_recipient(self):
        with Session(engine, expire_on_commit=False) as db, patch.object(dispatch, "trigger_n8n_event") as hook, \
                patch.object(dispatch.push_service, "send_push") as push:
            user = db.get(m.User, self.ids["admin"])
            notice = dispatch.create_history_notification(db, user_id=user.id, actor_id=self.ids["member"],
                notification_type=m.NotificationTypeEnum.TICKET_UPDATED, message="Synthetic private body",
                entity_type=m.NotificationEntityTypeEnum.TICKET, entity_id=str(self.tickets[0]))
            self.assertIsNotNone(notice)
            db.commit()
            hook.reset_mock()
            self.change_user("admin", role=m.RoleEnum.USER)
            self.assertEqual(user.role, m.RoleEnum.ADMIN)  # The retained ORM snapshot is genuinely stale.
            dispatch.deliver_stored_notification(db, notice, sound_enabled=False)
            hook.assert_not_called()
            push.assert_not_called()

    def test_ticket_email_admission_refreshes_preloaded_demoted_recipient(self):
        with Session(engine) as db, patch.object(ticket_notices.email_sender, "send_ticket_event_email") as email:
            user = db.get(m.User, self.ids["admin"])
            self.change_user("admin", role=m.RoleEnum.USER)
            self.assertEqual(user.role, m.RoleEnum.ADMIN)
            context = {"tenant_id": str(self.tenant), "ticket_id": str(self.tickets[0]), "ticket_title": "Private"}
            ticket_notices.send_ticket_emails(db, recipient_ids=[user.id], event_type="ticket.updated", context=context)
            email.assert_not_called()
            created = ticket_notices.create_ticket_notifications(db, tenant_id=self.tenant,
                recipient_ids=[user.id], event_type="ticket.updated", context=context, data={})
            self.assertEqual(created, [])

    def test_history_admission_refreshes_actor_and_recipient_tenants(self):
        with Session(engine) as db, patch.object(dispatch, "trigger_n8n_event") as hook:
            actor = db.get(m.User, self.ids["owner"])
            recipient = db.get(m.User, self.ids["member"])
            self.change_user("owner", tenant_id=self.foreign)
            self.assertEqual(actor.tenant_id, recipient.tenant_id)
            created = dispatch.create_history_notification(db, user_id=recipient.id, actor_id=actor.id,
                notification_type=m.NotificationTypeEnum.TICKET_UPDATED, message="Foreign actor",
                entity_type=m.NotificationEntityTypeEnum.TICKET, entity_id=str(self.tickets[0]))
            self.assertIsNone(created)
            hook.assert_not_called()

    def test_history_admission_refreshes_deactivated_recipient(self):
        with Session(engine) as db, patch.object(dispatch, "trigger_n8n_event") as hook:
            user = db.get(m.User, self.ids["member"])
            self.change_user("member", status=m.UserStatusEnum.DEACTIVATED)
            self.assertEqual(user.status, m.UserStatusEnum.ACTIVE)
            created = dispatch.create_history_notification(db, user_id=user.id,
                notification_type=m.NotificationTypeEnum.TICKET_UPDATED, message="Inactive recipient",
                entity_type=m.NotificationEntityTypeEnum.TICKET, entity_id=str(self.tickets[0]))
            self.assertIsNone(created)
            hook.assert_not_called()

    def test_transfer_changes_only_selected_assignment_with_distinct_target(self):
        result = self.transfer("manager", "watcher")
        self.assertEqual(result.status_code, 200, result.text)
        with Session(engine) as db:
            task, sibling = db.get(m.Task, "assigned"), db.get(m.Task, "sibling")
            self.assertEqual(task.assigned_to_id, self.ids["watcher"])
            self.assertEqual(sibling.assigned_to_id, self.ids["peer"])
            self.assertEqual(task.task_group_id, sibling.task_group_id)
        self.denied(self.req("GET", "/tasks/sibling", "watcher"))

    def test_delivery_refreshes_navigation_policy_and_module_cache(self):
        from app.services.notification_access import can_deliver
        from app.navigation_registry import default_rules
        with Session(engine, expire_on_commit=False) as db:
            user = db.get(m.User, self.ids["member"])
            policy = m.NavigationPolicy(tenant_id=str(self.tenant), pages=default_rules(), version=1,
                updated_by=self.ids["owner"], updated_at=datetime.utcnow())
            db.add(policy)
            db.commit()
            notice = m.Notification(tenant_id=self.tenant, user_id=user.id,
                type=m.NotificationTypeEnum.TASK_UPDATED, entity_type=m.NotificationEntityTypeEnum.TASK,
                entity_id="assigned", message="Private task")
            self.assertTrue(can_deliver(db, notice, user))
            with Session(engine) as writer:
                changed = writer.get(m.NavigationPolicy, str(self.tenant))
                rules = dict(changed.pages)
                rules["tasks"] = {**rules["tasks"], "enabled": False}
                # Task APIs remain available through the dashboard by contract.
                rules["dashboard"] = {**rules["dashboard"], "enabled": False}
                changed.pages = rules
                writer.commit()
            self.assertTrue(policy.pages["tasks"]["enabled"])
            self.assertFalse(can_deliver(db, notice, user))

    def test_delivery_refreshes_manager_department(self):
        from app.services.notification_access import can_deliver
        with Session(engine) as db:
            user = db.get(m.User, self.ids["manager"])
            notice = m.Notification(tenant_id=self.tenant, user_id=user.id,
                type=m.NotificationTypeEnum.TICKET_UPDATED, entity_type=m.NotificationEntityTypeEnum.TICKET,
                entity_id=str(self.tickets[0]), message="Private ticket")
            self.assertTrue(can_deliver(db, notice, user))
            self.change_user("manager", department_id=self.departments[1])
            self.assertEqual(user.department_id, self.departments[0])
            self.assertFalse(can_deliver(db, notice, user))

    def test_aliases_ignore_forged_tenant_and_role_headers(self):
        for prefix in ("", "/api"):
            for path in ("/tasks/foreign-task", f"/tickets/{self.tickets[1]}/logs",
                         f"/tickets/{self.tickets[1]}/tasks"):
                headers = {**self.headers(), "X-Tenant-ID": str(self.foreign), "X-Role": "OWNER"}
                response = self.client.get(prefix + path, headers=headers)
                self.denied(response)
                self.assertNotIn("Synthetic private ticket audit", response.text)
            for resource in ("logs", "tasks"):
                self.denied(self.req("GET", prefix + f"/tickets/{self.tickets[0]}/{resource}", "peer"))

    def test_task_payload_cache_cannot_preserve_moved_creator_visibility(self):
        self.assertEqual(self.req("GET", "/tasks/assigned", "admin").status_code, 200)
        self.assertEqual(self.req("GET", "/tasks/page", "admin").status_code, 200)
        self.change_user("owner", tenant_id=self.foreign)
        for prefix in ("", "/api"):
            self.denied(self.req("GET", prefix + "/tasks/assigned", "admin"))
            response = self.req("GET", prefix + "/tasks/page", "admin")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn('"assigned"', response.text)


if __name__ == "__main__":
    suite = unittest.TestSuite(IndependentTenantAudit(name) for name in IndependentTenantAudit.__dict__ if name.startswith("test_"))
    if not os.environ.get("ZEA_PHASE14_AUDIT_ONLY"):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(TenantSecurity))
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(scope["base"]["BusinessRegressions"]))
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(scope["DepartmentBoundaryReview"]))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
