"""Run only Phase 1 security tests in a disposable, network-denied process.

Usage from the repository: python backend/security_tests/run_mcp_phase1.py
No pytest discovery, installed application startup, migrations or file databases.
Exit 0: exercised checks/gates pass; 1: test failure; 2: open security gate.
No exit status certifies untested OAuth, PostgreSQL, proxy or deployment behavior.
"""
from pathlib import Path
import os
import secrets
import subprocess
import sys
import tempfile


def main():
    script = Path(__file__).resolve()
    repository = script.parents[2]
    # Do not inherit database, provider, Redis or authentication configuration.
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC"}}
    environment.update(VEE_DATABASE_URL="sqlite:///:memory:",
                       VEE_JWT_SECRET_KEY=secrets.token_urlsafe(48),
                       VEE_JWT_REFRESH_SECRET_KEY=secrets.token_urlsafe(48),
                       ZEA_PHASE1_ISOLATED="memory-only", PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory(prefix="zea-mcp-phase1-") as scratch:
        environment.update(TEMP=scratch, TMP=scratch)
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(script.with_name("mcp_phase1_cases.py")), str(repository)],
            cwd=scratch, env=environment, timeout=120, check=False,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
