"""Independent PostgreSQL media/presign checks; inherited fixture rolls back each method.

No real object-store connection: signer and byte-I/O assertions use spies.
"""
import unittest
import uuid
from unittest.mock import patch
from fastapi import HTTPException

import mcp_phase2a1_cases as retained
from app import models as m
from app.services import minio_media_service as media, media_service as legacy
from app.routers import media as routes
from app.tickets import attachments_router as attachments


class IndependentMediaAudit(retained.MediaSecurity):
    def test_foreign_confirm_is_nondisclosing_for_all_actor_roles(self):
        for actor in (self.a, self.manager, self.member):
            with self.subTest(role=actor.role), patch.object(media, "_get_minio_client") as client:
                self.denied(lambda: media.confirm_media_upload(self.db, user=actor, file_id=self.files["b"].id))
                client.assert_not_called()

    def test_same_tenant_other_uploader_confirm_remains_forbidden(self):
        for actor in (self.manager, self.member):
            with self.subTest(role=actor.role), patch.object(media, "_get_minio_client") as client:
                self.denied(lambda: media.confirm_media_upload(self.db, user=actor, file_id=self.files["a"].id), 403)
                client.assert_not_called()

    def test_foreign_delete_is_denied_before_storage_for_nonowners(self):
        for actor in (self.manager, self.member):
            with self.subTest(role=actor.role), patch.object(media, "delete_media_file") as client:
                self.denied(lambda: routes.delete_media(self.files["b"].id, hard=False, db=self.db, current_user=actor))
                client.assert_not_called()

    def test_page_count_excludes_foreign_rows_before_limit(self):
        rows, total = media.list_media_files(self.db, user=self.a, tab="images", search=None,
            from_date=None, to_date=None, page=1, page_size=1)
        self.assertEqual(total, 2)
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0].id, self.files["b"].id)

    def test_route_signs_only_authorized_uploader_objects(self):
        with patch.object(media, "generate_presigned_get", return_value="https://storage.invalid/synthetic") as signer:
            result = routes.list_media_files(tab="images", search=None, from_date=None, to_date=None,
                page=1, page_size=24, db=self.db, current_user=self.a)
            self.assertEqual(result.total, 2)
            self.assertEqual({c.args[1] for c in signer.call_args_list}, {self.files["a"].object_key, self.files["member"].object_key})

    def test_presigned_put_is_fixed_method_bucket_key_type_and_ttl(self):
        with patch.object(media, "_get_minio_client") as client:
            client.return_value.generate_presigned_url.return_value = "https://storage.invalid/synthetic"
            media._generate_presigned_put("synthetic-bucket", "synthetic-key", "image/png")
            client.return_value.generate_presigned_url.assert_called_once_with("put_object",
                Params={"Bucket":"synthetic-bucket", "Key":"synthetic-key", "ContentType":"image/png"}, ExpiresIn=300)

    def test_inactive_uploader_does_not_remove_existing_staff_admission(self):
        self.member.status = m.UserStatusEnum.DEACTIVATED
        self.db.flush()
        self.assertEqual(legacy.get_media_item(self.db, media_id=self.items["member"].id, user=self.a).id, self.items["member"].id)

    def test_ticket_foreign_presign_rejects_before_storage(self):
        with patch.object(attachments, "_get_minio_client") as client:
            self.denied(lambda: attachments.presign_attachment_upload(
                ticket_id=uuid.UUID(retained.fixture.ident("ticket-b")),
                payload=attachments.AttachmentPresignRequest(fileName="synthetic.txt", contentType="text/plain", sizeBytes=8),
                db=self.db, tenant_id=self.a.tenant_id, current_user=self.a, roles=["owner"]))
            client.assert_not_called()

    def test_foreign_and_missing_confirm_responses_are_indistinguishable(self):
        def failure(key):
            try:
                media.confirm_media_upload(self.db, user=self.member, file_id=key)
            except HTTPException as error:
                return error.status_code, error.detail
            self.fail("Expected denial")
        self.assertEqual(failure(self.files["b"].id), failure(str(uuid.uuid4())))

    def test_foreign_and_missing_metadata_responses_are_indistinguishable(self):
        def failure(key):
            try:
                legacy.get_media_item(self.db, user=self.a, media_id=key)
            except HTTPException as error:
                return error.status_code, error.detail
            self.fail("Expected denial")
        self.assertEqual(failure(self.items["b"].id), failure(str(uuid.uuid4())))


if __name__ == "__main__":
    unittest.main(verbosity=2)
