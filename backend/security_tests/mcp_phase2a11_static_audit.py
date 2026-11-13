"""In-process HTTP/static boundary tests with synthetic owned scratch files.

Not browser tests and not object-storage tests. Import fixture guard first.
"""
import tempfile
import unittest
from pathlib import Path

import mcp_phase1_5_backend as fixture
fixture.verify()
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient
from app.avatar_http import AvatarSafeStaticFiles
from app.media_http import UploadedMediaStaticFiles


class UploadedDocumentPolicy(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='/scratch/phase2a11-static-')
        root = Path(self.scratch.name)
        uploads = root/'uploads'; assets = root/'assets'
        uploads.mkdir(); (assets/'task_templates').mkdir(parents=True)
        (assets/'avatars/library').mkdir(parents=True); (assets/'avatars/custom').mkdir()
        for p in [uploads/'synthetic.svg', assets/'task_templates/synthetic.svg',
                  assets/'avatars/library/default-avatar-01.svg', assets/'avatars/custom/synthetic.svg']:
            p.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>')
        (root/'private.txt').write_text('synthetic outside-mount sentinel')
        self.client = TestClient(Starlette(routes=[Mount('/uploads', UploadedMediaStaticFiles(directory=uploads)),
            Mount('/assets', AvatarSafeStaticFiles(directory=assets))]))

    def tearDown(self):
        self.client.close(); self.scratch.cleanup()

    def assert_sandbox(self, response):
        self.assertEqual(response.headers['content-security-policy'], 'sandbox allow-downloads')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')

    def test_public_uploaded_bytes_retain_anonymous_access_with_sandbox(self):
        r = self.client.get('/uploads/synthetic.svg')
        self.assertEqual(r.status_code, 200); self.assertIn(b'<svg', r.content)
        self.assert_sandbox(r)

    def test_template_image_is_sandboxed_bundled_art_is_unchanged(self):
        template = self.client.get('/assets/task_templates/synthetic.svg')
        self.assertEqual(template.status_code, 200); self.assert_sandbox(template)
        bundled = self.client.get('/assets/avatars/library/default-avatar-01.svg')
        self.assertEqual(bundled.status_code, 200)
        self.assertNotIn('content-security-policy', bundled.headers)
        self.assertEqual(self.client.get('/assets/avatars/custom/synthetic.svg').status_code, 404)

    def test_head_keeps_headers_and_has_no_body(self):
        r = self.client.head('/uploads/synthetic.svg')
        self.assertEqual(r.status_code, 200); self.assertEqual(r.content, b''); self.assert_sandbox(r)

    def test_range_keeps_headers_and_partial_bytes(self):
        r = self.client.get('/uploads/synthetic.svg', headers={'Range':'bytes=0-3'})
        self.assertEqual(r.status_code, 206); self.assertEqual(r.content, b'<svg'); self.assert_sandbox(r)

    def test_conditional_response_keeps_headers(self):
        etag = self.client.get('/uploads/synthetic.svg').headers['etag']
        r = self.client.get('/uploads/synthetic.svg', headers={'If-None-Match':etag})
        self.assertEqual(r.status_code, 304); self.assert_sandbox(r)

    def test_encoded_traversal_cannot_read_existing_outside_file(self):
        r = self.client.get('/uploads/%2e%2e%2fprivate.txt')
        self.assertEqual(r.status_code, 404); self.assertNotIn('outside-mount sentinel', r.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
