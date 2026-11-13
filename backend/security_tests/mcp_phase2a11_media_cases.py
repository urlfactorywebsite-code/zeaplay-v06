"""Phase 2A.1.1 checks; run ONLY inside the guarded disposable Phase 1.5 stack.

Real PostgreSQL, real SDK signing, synthetic bytes, and explicit storage spies.
These tests do not establish object-store signature enforcement or expiration.
"""
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import mcp_phase1_5_backend as fixture
fixture.verify()
import boto3
from botocore.config import Config
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app import models
from app.services import minio_media_service as media
from app.storage.local import LocalAdapter
from app.storage.minio import build_ticket_attachment_key
from app.tickets import attachments_router as tickets


class PrivateMediaBoundaries(unittest.TestCase):
    def setUp(self):
        self.tenant = uuid.UUID(fixture.ident('tenant-a'))
        self.ticket = uuid.UUID(fixture.ident('ticket-a'))
        self.prefix = f'tenant/{self.tenant}/tickets/{self.ticket}/'

    def test_generated_ticket_key_remains_accepted(self):
        key = build_ticket_attachment_key(tenant_id=str(self.tenant), ticket_id=str(self.ticket),
                                          filename='../../synthetic attachment.txt')
        tickets._validate_file_key(key, tenant_id=self.tenant, ticket_id=self.ticket)

    def test_ticket_key_rejects_traversal_and_noncanonical_paths(self):
        for tail in ('../other/file.txt', 'x/../../other', 'x/y.txt', 'x\\..\\y',
                     '%2e%2e%2fforeign', 'a%252fb', 'a\x00.txt', 'a\r\n.txt', '.', '..', ''):
            with self.subTest(shape=repr(tail)):
                with self.assertRaises(HTTPException) as error:
                    tickets._validate_file_key(self.prefix + tail, tenant_id=self.tenant, ticket_id=self.ticket)
                self.assertEqual(error.exception.status_code, 400)

    def test_foreign_ticket_key_rejected(self):
        with self.assertRaises(HTTPException) as error:
            tickets._validate_file_key('tenant/foreign/tickets/foreign/opaque.txt',
                                       tenant_id=self.tenant, ticket_id=self.ticket)
        self.assertEqual(error.exception.status_code, 400)

    def test_invalid_ticket_key_rejected_before_object_lookup(self):
        with Session(fixture.engine) as db:
            owner = db.get(models.User, fixture.ident('owner'))
            with patch.object(tickets, '_get_minio_client', side_effect=AssertionError('Storage reached')) as store:
                with self.assertRaises(HTTPException) as error:
                    tickets.confirm_attachment_upload(self.ticket,
                        tickets.AttachmentConfirmRequest(fileKey=self.prefix+'../foreign/object'),
                        db=db, tenant_id=self.tenant, current_user=owner, roles=['owner'])
                self.assertEqual(error.exception.status_code, 400)
                store.assert_not_called()

    def test_private_get_signs_cache_override_and_fixed_ttl(self):
        with patch.object(media, '_get_minio_client') as store:
            media.generate_presigned_get('synthetic-private', 'synthetic/object')
            call = store.return_value.generate_presigned_url.call_args
            self.assertEqual(call.args, ('get_object',))
            self.assertEqual(call.kwargs['ExpiresIn'], 300)
            self.assertEqual(call.kwargs['Params'], {'Bucket': 'synthetic-private',
                'Key': 'synthetic/object', 'ResponseCacheControl': 'private, no-store, max-age=0'})

    def test_real_sdk_signature_covers_cache_override(self):
        client = boto3.client('s3', endpoint_url='http://127.0.0.1:9',
            aws_access_key_id='synthetic-access', aws_secret_access_key='synthetic-secret',
            region_name='us-east-1', config=Config(signature_version='s3v4', s3={'addressing_style':'path'}))
        with patch.object(media, '_get_minio_client', return_value=client):
            query = parse_qs(urlsplit(media.generate_presigned_get('synthetic-private', 'synthetic/object')).query)
        self.assertEqual(query.get('response-cache-control'), ['private, no-store, max-age=0'])
        self.assertEqual(query['X-Amz-Expires'], ['300'])
        self.assertEqual(len(query['X-Amz-Signature'][0]), 64)

    def test_local_storage_containment(self):
        with tempfile.TemporaryDirectory(prefix='/scratch/phase2a11-local-') as directory:
            adapter = LocalAdapter(directory, '/uploads')
            for path in ('../outside.txt', 'x/../../outside.txt'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    adapter.save(b'synthetic', path, content_type='text/plain')
            saved = adapter.save(b'synthetic', 'allowed/file.txt', content_type='text/plain')
            self.assertEqual((Path(directory)/saved.path).read_bytes(), b'synthetic')
            adapter.delete(saved.path)
            self.assertFalse((Path(directory)/saved.path).exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
