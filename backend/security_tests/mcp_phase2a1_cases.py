"""PostgreSQL media regressions, restricted to the owned Phase 1.5 fixture DB.

Storage calls are spies, not a real S3 service. Authentication/proxy/browser
coverage is recorded separately. Every method rolls back its synthetic rows.
"""
import asyncio
import io
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

import mcp_phase1_5_backend as fixture
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session
from app import models as m
from app.services import media_service as legacy, minio_media_service as media
from app.routers import media as routes
from app.tickets import attachments_router, service as tickets

fixture.verify()


class MediaSecurity(unittest.TestCase):
    def setUp(self):
        self.conn = fixture.engine.connect()
        self.transaction = self.conn.begin()
        self.db = Session(self.conn, join_transaction_mode="create_savepoint")
        self.a = self.db.get(m.User, fixture.ident("owner"))
        self.b = self.db.get(m.User, fixture.ident("foreign"))
        self.member = self.db.get(m.User, fixture.ident("member"))
        self.manager = self.db.get(m.User, fixture.ident("manager"))
        self.files, self.items = {}, {}
        for name, user in (("a", self.a), ("b", self.b), ("member", self.member)):
            item = m.MediaItem(id=fixture.ident("p21-item-"+name), owner_id=user.id,
                filename=name+".txt", ext="txt", mime_type="text/plain", size_bytes=8,
                category=m.MediaCategoryEnum.DOCUMENT, storage_provider=m.StorageProviderEnum.LOCAL,
                storage_path="uploads/"+user.id+"/synthetic.txt", public_url="/uploads/synthetic.txt",
                checksum_sha256="0"*64)
            file = m.MediaFile(id=fixture.ident("p21-file-"+name), user_id=user.id,
                department_id=user.department_id, media_type=m.MediaFileTypeEnum.IMAGE,
                bucket="phase2a1-fixture", object_key="synthetic/"+name,
                original_filename=name+".png", content_type="image/png", size_bytes=8,
                status=m.MediaFileStatusEnum.CONFIRMED)
            self.db.add_all([item, file]); self.items[name] = item; self.files[name] = file
        self.db.flush()

    def tearDown(self):
        self.db.close(); self.transaction.rollback(); self.conn.close()

    def denied(self, work, code=404):
        with self.assertRaises(HTTPException) as failure: work()
        self.assertEqual(failure.exception.status_code, code)

    def test_legacy_staff_list_is_tenant_scoped(self):
        for actor in (self.a, self.manager):
            with self.subTest(role=actor.role):
                rows, total = legacy.list_media_items(self.db, user=actor)
                self.assertNotIn(self.items["b"].id, {r.id for r in rows})
                self.assertEqual(total, 2)

    def test_legacy_foreign_owner_filter_cannot_enumerate(self):
        rows, total = legacy.list_media_items(self.db, user=self.a, owner_id=self.b.id)
        self.assertEqual((rows, total), ([], 0))

    def test_legacy_staff_cannot_read_foreign_object(self):
        for actor in (self.a, self.manager):
            with self.subTest(role=actor.role):
                self.denied(lambda: legacy.get_media_item(self.db, user=actor, media_id=self.items["b"].id))

    def test_legacy_foreign_rename_denied(self):
        self.denied(lambda: legacy.rename_media_item(self.db, user=self.a, media_id=self.items["b"].id, filename="changed.txt"))

    def test_legacy_foreign_delete_denied_before_storage(self):
        with patch.object(legacy, "get_adapter") as storage:
            self.denied(lambda: legacy.delete_media_item(self.db, user=self.a, media_id=self.items["b"].id, hard=True))
            storage.assert_not_called()

    def test_legacy_foreign_version_link_denied_before_storage(self):
        with patch.object(legacy, "get_default_adapter") as storage:
            storage.return_value.provider = "local"
            storage.return_value.save.return_value = SimpleNamespace(path="synthetic.txt", size=8, mime_type="text/plain", public_url="/uploads/synthetic.txt")
            self.denied(lambda: asyncio.run(legacy.create_media_item(self.db, owner=self.a,
                upload=UploadFile(io.BytesIO(b"synthetic"), filename="fixture.txt"), original_id=self.items["b"].id)))
            storage.assert_not_called()

    def test_legacy_same_tenant_staff_and_owner_behavior_preserved(self):
        self.assertEqual(legacy.get_media_item(self.db, user=self.a, media_id=self.items["member"].id).id, self.items["member"].id)
        self.assertEqual(legacy.get_media_item(self.db, user=self.member, media_id=self.items["member"].id).id, self.items["member"].id)
        self.denied(lambda: legacy.get_media_item(self.db, user=self.member, media_id=self.items["a"].id), 403)

    def test_minio_owner_list_is_tenant_scoped(self):
        rows, total = media.list_media_files(self.db, user=self.a, tab="images", search=None, from_date=None, to_date=None, page=1, page_size=24)
        self.assertEqual({r.id for r in rows}, {self.files["a"].id, self.files["member"].id})
        self.assertEqual(total, 2)

    def test_minio_manager_shared_department_cannot_cross_tenant(self):
        rows, total = media.list_media_files(self.db, user=self.manager, tab="images", search=None, from_date=None, to_date=None, page=1, page_size=24)
        self.assertNotIn(self.files["b"].id, {r.id for r in rows})
        self.assertEqual(total, 2)

    def test_minio_user_stays_self_only(self):
        rows, total = media.list_media_files(self.db, user=self.member, tab="images", search=None, from_date=None, to_date=None, page=1, page_size=24)
        self.assertEqual([r.id for r in rows], [self.files["member"].id]); self.assertEqual(total, 1)

    def test_minio_foreign_confirm_denied_before_object_io(self):
        with patch.object(media, "_get_minio_client") as storage:
            self.denied(lambda: media.confirm_media_upload(self.db, user=self.a, file_id=self.files["b"].id))
            storage.assert_not_called()

    def test_minio_foreign_delete_denied_before_object_io(self):
        with patch.object(media, "delete_media_file") as storage:
            self.denied(lambda: routes.delete_media(self.files["b"].id, hard=False, db=self.db, current_user=self.a))
            storage.assert_not_called()

    def test_minio_same_tenant_owner_delete_preserved(self):
        with patch.object(media, "delete_media_file") as storage:
            routes.delete_media(self.files["member"].id, hard=False, db=self.db, current_user=self.a)
            storage.assert_called_once()

    def test_minio_signing_contract_has_fixed_method_and_expiry(self):
        with patch.object(media, "_get_minio_client") as storage:
            storage.return_value.generate_presigned_url.return_value = "https://storage.invalid/synthetic"
            media.generate_presigned_get("fixture", "synthetic")
            call = storage.return_value.generate_presigned_url.call_args
            self.assertEqual(call.args, ("get_object",)); self.assertEqual(call.kwargs["ExpiresIn"], 300)
            self.assertEqual(call.kwargs["Params"], {"Bucket":"fixture", "Key":"synthetic",
                "ResponseCacheControl":"private, no-store, max-age=0"})

    def test_attachment_manager_cannot_bypass_canonical_ticket_policy(self):
        ticket = self.db.get(fixture.tm.Ticket, __import__('uuid').UUID(fixture.ident("ticket-a")))
        self.manager.department_id = None; ticket.created_by = self.manager.id; self.db.flush()
        args = dict(tenant_id=self.manager.tenant_id, ticket_id=ticket.id, current_user=self.manager, roles=["manager"])
        self.denied(lambda: tickets.get_ticket_for_user(self.db, **args), 403)
        self.denied(lambda: attachments_router._require_ticket_access(self.db, **args), 403)


if __name__ == "__main__":
    if sys.argv[1:] == ["seed-http"]:
        with Session(fixture.engine) as db:
            # Both authorized and denied parents are overdue, so the browser's
            # positive overdue check cannot pass merely because its list is empty.
            from datetime import datetime, timedelta, timezone
            for task_id in ("assigned", "sibling", "foreign-task"):
                db.get(m.Task, task_id).due_at = datetime.now(timezone.utc) - timedelta(days=1)
            owner = db.get(m.User, fixture.ident("foreign"))
            key = fixture.ident("phase2a1-http-foreign")
            if not db.get(m.MediaFile, key):
                db.add(m.MediaFile(id=key, user_id=owner.id, department_id=owner.department_id,
                    media_type=m.MediaFileTypeEnum.IMAGE, bucket="synthetic-not-connected",
                    object_key="synthetic/foreign", original_filename="foreign.png",
                    content_type="image/png", size_bytes=8, status=m.MediaFileStatusEnum.CONFIRMED))
            db.commit()
            print(fixture.json.dumps({"foreign_media_file":key}))
    else:
        unittest.main(verbosity=2)
