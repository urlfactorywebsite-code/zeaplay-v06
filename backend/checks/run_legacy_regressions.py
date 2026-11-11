"""Run legacy hardcoded-SQLite tests without touching workspace databases.

Run in a fresh Python process; outbound network sockets are blocked. Temporary
test evidence is intentionally retained for inspection.
"""
import os
from pathlib import Path
import socket
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
scratch = Path(tempfile.mkdtemp(prefix="zea-sidebar-legacy-tests-"))
(scratch / "assets").mkdir()
os.chdir(scratch)
sys.path.insert(0, str(root))
os.environ.update(VEE_DATABASE_URL="sqlite:///:memory:", VEE_ENVIRONMENT="test",
                  VEE_BOOTSTRAP_SCHEMA="false", PYTHONDONTWRITEBYTECODE="1")
sys.dont_write_bytecode = True


def block_network(*args, **kwargs):
    raise RuntimeError("External sockets blocked for isolated regression checks")


socket.socket.connect = block_network
print(f"Disposable test cwd: {scratch}")
import pytest

files = ["test_chat_phase1.py", "test_ticket_tenant_permissions.py", "test_task_list.py",
         "test_generate_token.py", "test_oauth2_server.py", "test_time_bonus.py"]
raise SystemExit(pytest.main([str(root / "backend/tests" / file) for file in files] + ["-q", "--tb=short"]))
