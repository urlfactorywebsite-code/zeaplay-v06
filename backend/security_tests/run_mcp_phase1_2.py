"""Phase 1.2: in-memory Python API tests, then network-denied Node verification.

No app startup, installed databases, Redis, production configuration or secrets.
Cross-language credentials live only inside the disposable scratch directory.
Exit 0 covers the executed checks; durable revocation is deliberately unimplemented.
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
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC"}}
    environment.update(VEE_DATABASE_URL="sqlite:///:memory:",
                       VEE_JWT_SECRET_KEY=secrets.token_urlsafe(48),
                       VEE_JWT_REFRESH_SECRET_KEY=secrets.token_urlsafe(48),
                       ZEA_PHASE1_ISOLATED="memory-only", PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory(prefix="zea-phase12-isolated-") as scratch:
        environment.update(TEMP=scratch, TMP=scratch,
                           ZEA_PHASE12_INTEROP_FILE=str(Path(scratch) / "synthetic-interop.json"))
        python = subprocess.run(
            [sys.executable, "-I", "-B", str(script.with_name("mcp_phase1_2_cases.py")), str(repository)],
            cwd=scratch, env=environment, timeout=180, check=False,
        )
        print(f"PYTHON_EXIT {python.returncode}", flush=True)
        if python.returncode:
            return python.returncode
        # Node receives only synthetic fixture material, not backend environment keys.
        environment.pop("VEE_JWT_SECRET_KEY")
        environment.pop("VEE_JWT_REFRESH_SECRET_KEY")
        node = subprocess.run(
            ["node", "--require", str(script.with_name("phase1_1_network_guard.cjs")),
             "--test", str(repository / "presence-server/test/auth.test.mjs")],
            cwd=scratch, env=environment, timeout=60, check=False,
        )
        print(f"NODE_EXIT {node.returncode}", flush=True)
        return node.returncode


if __name__ == "__main__":
    raise SystemExit(main())
