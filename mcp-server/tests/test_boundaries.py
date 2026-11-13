import ast
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from zeaplay_mcp.config import Settings
from zeaplay_mcp.security import JsonFormatter, redact_text


@pytest.mark.parametrize('kind', ['at', 'rt', 'dt'])
@pytest.mark.parametrize('last', ['a', '-', '_'])
@pytest.mark.parametrize('prefix,suffix', [('', ''), ('prefix', 'suffix'), ('/', '?next'), ('_', '-')])
def test_opaque_oauth_credentials_are_redacted_including_urlsafe_suffixes(kind, last, prefix, suffix):
    raw = 'mcp_' + kind + '.' + 'a' * 42 + last
    assert raw not in redact_text(prefix + raw + suffix)
    record = logging.LogRecord('mcp', logging.INFO, '', 1, {'event': prefix + raw + suffix}, (), None)
    assert raw not in JsonFormatter().format(record)


def test_runtime_guard_denies_network_database_and_child_execution(tmp_path):
    probe = tmp_path / "offline_probe.py"
    probe.write_text(
        """import anyio,json,socket,sqlite3,subprocess,sys
from zeaplay_mcp.security import install_offline_guard
async def main():
 install_offline_guard()
 denied=[]
 for name,call in [
  ("dns",lambda:socket.getaddrinfo("production.invalid",443)),
  ("tcp",lambda:socket.socket().connect(("203.0.113.1",443))),
  ("listen",lambda:socket.socket().bind(("127.0.0.1",0))),
  ("database",lambda:sqlite3.connect(":memory:")),
  ("child",lambda:subprocess.run([sys.executable,"-c","print(1)"]))]:
  try:call()
  except PermissionError:denied.append(name)
 assert len(denied)==5
 print(json.dumps({"denied":denied}))
anyio.run(main)
""",
        encoding="utf8",
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }
    r = subprocess.run(
        [sys.executable, "-I", str(probe)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["denied"] == [
        "dns",
        "tcp",
        "listen",
        "database",
        "child",
    ]


def test_no_application_database_or_network_client_import_and_only_read_adapter():
    root = Path(__file__).resolve().parents[1] / "src/zeaplay_mcp"
    forbidden = {
        "app",
        "sqlalchemy",
        "psycopg",
        "psycopg2",
        "redis",
        "requests",
        "httpx",
        "httpx2",
        "urllib",
    }
    for f in root.glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf8"))
        imports = {
            n.module.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module and not n.level
        }
        imports |= {
            v.name.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for v in n.names
        }
        # Phase2B permits the one reviewed fixed-origin HTTP client; all other
        # modules retain the database/application/arbitrary-client boundary.
        permitted = {"httpx2", "urllib"} if f.name == "rest.py" else {"httpx2"} if f.name == 'oauth_http.py' else set()
        assert not imports & (forbidden - permitted), (f.name, imports & forbidden)
    adapter = (root / "adapter.py").read_text()
    assert 'self.calls.append(("GET"' in adapter
    assert all(
        word not in adapter for word in ['"POST"', '"PATCH"', '"DELETE"', '"PUT"']
    )


@pytest.mark.parametrize(
    "data",
    [
        {"timeout_seconds": 0.0},
        {"timeout_seconds": 11.0},
        {"max_output_bytes": 131073},
        {"max_concurrency": 17},
        {"backend_url": "https://production.invalid"},
    ],
)
def test_settings_bounds(data):
    with pytest.raises(ValueError):
        Settings(**data)


def test_secret_redaction_and_structured_logs_never_render_exception_or_arguments():
    raw = "password=fixture-secret api_key:fixture-key Bearer fixture-token eyJhbGci.eyJzdWI.signature"
    safe = redact_text(raw)
    assert all(
        x not in safe
        for x in ["fixture-secret", "fixture-key", "fixture-token", "eyJhbGci"]
    )
    record = logging.LogRecord("mcp", logging.ERROR, "", 1, raw, (), None)
    assert json.loads(JsonFormatter().format(record))["event"] == "sdk_event"
    record.msg = {
        "event": "tool_completed",
        "tool": "zeaplay_list_tasks",
        "arguments": raw,
        "traceback": raw,
    }
    assert raw not in JsonFormatter().format(record)


@pytest.mark.parametrize(
    "raw",
    [
        '"password": "fixture secret with spaces"',
        "'api_key': 'fixture-key'",
        "refresh_token=fixture-token",
    ],
)
def test_quoted_secret_assignments_are_redacted(raw):
    assert "fixture" not in redact_text(raw)
