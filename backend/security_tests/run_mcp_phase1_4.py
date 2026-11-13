"""Own one disposable PostgreSQL container; never connect to installed services.

No host data mounts, no existing databases, sanitized child environment and fresh
keys. Docker cleanup targets only this run's random name after label validation.
"""
from pathlib import Path
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid


def main():
    if sys.argv[1:] not in ([], ["--audit"], ["--audit-only"]):
        raise RuntimeError("Only --audit or --audit-only supported")
    repo = Path(__file__).resolve().parents[2]
    run_id = uuid.uuid4().hex
    name = "zea-phase14-" + run_id
    env = {k: v for k, v in os.environ.items() if k.upper() in
           {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC"}}
    password = secrets.token_hex(24)
    created = False
    with tempfile.TemporaryDirectory(prefix="zea-phase14-isolated-") as scratch:
        def docker(*args, check=True):
            return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=45, check=check)
        try:
            if docker("image", "inspect", "postgres:16-alpine", check=False).returncode:
                print("NOT RUN: required local PostgreSQL image unavailable")
                return 3
            docker("run", "--detach", "--name", name, "--label", f"zea.phase13={run_id}",
                   "--tmpfs", "/var/lib/postgresql/data", "-p", "127.0.0.1::5432",
                   "-e", "POSTGRES_USER=zea_test", "-e", f"POSTGRES_PASSWORD={password}",
                   "-e", "POSTGRES_DB=zea_phase13", "postgres:16-alpine")
            created = True
            mapping = docker("port", name, "5432/tcp").stdout.strip()
            if not mapping.startswith("127.0.0.1:"):
                raise RuntimeError("Unexpected disposable database binding")
            port = int(mapping.rsplit(":", 1)[1])
            for _ in range(100):
                if docker("exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "zea_test", "-d", "zea_phase13", check=False).returncode == 0:
                    break
                state = docker("inspect", "--format", "{{.State.Status}}", name).stdout.strip()
                if state == "exited":
                    logs = docker("logs", "--tail", "15", name, check=False)
                    print((logs.stdout + logs.stderr).replace(password, "[REDACTED]"), flush=True)
                    raise RuntimeError("Disposable PostgreSQL exited during startup")
                time.sleep(0.2)
            else:
                raise RuntimeError("Disposable PostgreSQL not ready")
            env.update(VEE_DATABASE_URL=f"postgresql+psycopg2://zea_test:{password}@127.0.0.1:{port}/zea_phase13",
                       VEE_JWT_SECRET_KEY=secrets.token_hex(48), VEE_JWT_REFRESH_SECRET_KEY=secrets.token_hex(48),
                       ZEA_PHASE13_PORT=str(port), ZEA_ALEMBIC_MIGRATION="1", ZEA_PHASE13_ISOLATED=run_id,
                       PYTHONDONTWRITEBYTECODE="1", TEMP=scratch, TMP=scratch,
                       ZEA_PHASE13_INTEROP=str(Path(scratch) / "interop.json"))
            print("ISOLATION: new owned PostgreSQL 16; loopback random port; tmpfs; no host data mounts", flush=True)
            if sys.argv[1:] == ["--audit-only"]:
                env["ZEA_PHASE14_AUDIT_ONLY"] = "1"
            cases = repo / "backend/security_tests" / ("mcp_phase1_4_audit.py" if sys.argv[1:] else "mcp_phase1_4_cases.py")
            result = subprocess.run([sys.executable, "-I", "-B", str(cases), str(repo)],
                                    cwd=scratch, env=env, timeout=450, check=False)
            print(f"POSTGRES_SUITE_EXIT {result.returncode}", flush=True)
            if result.returncode:
                return result.returncode
            return result.returncode
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            # Do not print command arguments/DSNs: they contain disposable secrets.
            print(f"BLOCKED: isolated infrastructure failure ({type(exc).__name__}); incomplete checks NOT RUN", flush=True)
            return 3
        finally:
            socket_container = docker("inspect", "--format", '{{json .Config.Labels}}', name + "-socket", check=False)
            if socket_container.returncode == 0:
                if json.loads(socket_container.stdout).get("zea.phase13") != run_id:
                    raise RuntimeError("Refusing cleanup: socket container ownership mismatch")
                docker("stop", "--time", "3", name + "-socket")
            if created:
                label = json.loads(docker("inspect", "--format", '{{json .Config.Labels}}', name).stdout)["zea.phase13"]
                if label != run_id:
                    raise RuntimeError("Refusing cleanup: container ownership label mismatch")
                docker("stop", "--time", "3", name)
                docker("rm", name)
                print("CLEANUP: owned disposable container stopped and removed", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
