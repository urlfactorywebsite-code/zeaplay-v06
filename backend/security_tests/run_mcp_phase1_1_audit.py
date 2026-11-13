"""Run independent audit probes; exit 2 means reproduced open security gates."""
from pathlib import Path
import os
import secrets
import subprocess
import sys
import tempfile


def main():
    script = Path(__file__).resolve()
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC"}}
    environment.update(VEE_DATABASE_URL="sqlite:///:memory:",
                       VEE_JWT_SECRET_KEY=secrets.token_urlsafe(48),
                       VEE_JWT_REFRESH_SECRET_KEY=secrets.token_urlsafe(48),
                       ZEA_PHASE1_ISOLATED="memory-only", PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory(prefix="zea-phase11-independent-") as scratch:
        environment.update(TEMP=scratch, TMP=scratch)
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(script.with_name("mcp_phase1_1_audit_cases.py")),
             str(script.parents[2])], cwd=scratch, env=environment, timeout=180, check=False,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
