"""Actual Nginx/Uvicorn/PostgreSQL, sharing one network-none disposable namespace.

No published ports, production mounts, image builds or installed services.
Only current source/test directories are mounted read-only; secrets are ephemeral.
"""
from pathlib import Path
import json
import secrets
import subprocess
import tempfile
import time
import uuid


def main():
    repo = Path(__file__).resolve().parents[2]
    run_id = uuid.uuid4().hex
    prefix = "zea-phase14-proxy-" + run_id
    owned = []
    password = secrets.token_hex(24)

    def docker(*args, check=True, timeout=45):
        return subprocess.run(["docker", *args], capture_output=True, text=True,
                              timeout=timeout, check=check)

    with tempfile.TemporaryDirectory(prefix="zea-phase14-proxy-") as scratch:
        try:
            for image in ("postgres:16-alpine", "nginx:alpine", "zeaplay_v1-backend:latest"):
                if docker("image", "inspect", image, check=False).returncode:
                    print("NOT RUN: a required cached proxy-test image is unavailable")
                    return 3
            nginx = Path(scratch) / "default.conf"
            source = (repo / "frontend/nginx.conf").read_text()
            assert source.count("http://backend:7211") == 2
            nginx.write_text(source.replace("http://backend:7211", "http://127.0.0.1:7211"))
            db_name, proxy_name, app_name = (prefix + suffix for suffix in ("-db", "-nginx", "-app"))
            for name in (db_name, proxy_name, app_name):
                if docker("inspect", name, check=False).returncode == 0:
                    raise RuntimeError("Disposable name already exists")
            owned.append(db_name)
            docker("run", "-d", "--name", db_name, "--label", f"zea.phase14.audit={run_id}",
                   "--network", "none", "--tmpfs", "/var/lib/postgresql/data",
                   "-e", "POSTGRES_USER=zea_test", "-e", f"POSTGRES_PASSWORD={password}",
                   "-e", "POSTGRES_DB=zea_phase13", "postgres:16-alpine")
            for _ in range(100):
                if docker("exec", db_name, "pg_isready", "-h", "127.0.0.1", "-U", "zea_test", check=False).returncode == 0:
                    break
                time.sleep(.2)
            else:
                raise RuntimeError("Disposable PostgreSQL unavailable")
            owned.append(proxy_name)
            docker("run", "-d", "--name", proxy_name, "--label", f"zea.phase14.audit={run_id}",
                   "--network", f"container:{db_name}", "--read-only", "--tmpfs", "/var/cache/nginx",
                   "--tmpfs", "/var/run", "--tmpfs", "/tmp",
                   "--mount", f"type=bind,src={nginx},dst=/etc/nginx/conf.d/default.conf,readonly",
                   "--entrypoint", "nginx", "nginx:alpine", "-g", "daemon off;")
            mounts = []
            for part in ("backend/app", "backend/alembic", "backend/security_tests"):
                mounts += ["--mount", f"type=bind,src={repo / part},dst=/repo/{part},readonly"]
            env = {"VEE_DATABASE_URL": f"postgresql+psycopg2://zea_test:{password}@127.0.0.1:5432/zea_phase13",
                   "VEE_JWT_SECRET_KEY": secrets.token_hex(48), "VEE_JWT_REFRESH_SECRET_KEY": secrets.token_hex(48),
                   "ZEA_PHASE13_PORT": "5432", "ZEA_PHASE13_ISOLATED": run_id, "ZEA_ALEMBIC_MIGRATION": "1",
                   "PYTHONDONTWRITEBYTECODE": "1"}
            env_args = [value for key, value in env.items() for value in ("-e", key + "=" + value)]
            owned.append(app_name)
            print("ISOLATION: actual Nginx + Uvicorn + PostgreSQL; shared network=none; no published ports; source read-only", flush=True)
            result = docker("run", "--name", app_name, "--label", f"zea.phase14.audit={run_id}",
                "--network", f"container:{db_name}", "--read-only", "--tmpfs", "/scratch", "--tmpfs", "/tmp",
                "--workdir", "/scratch", *mounts, *env_args, "--entrypoint", "python",
                "zeaplay_v1-backend:latest", "-I", "-B", "/repo/backend/security_tests/mcp_phase1_4_proxy.py",
                "/repo", check=False, timeout=180)
            print((result.stdout + result.stderr).replace(password, "[REDACTED]"))
            print("PROXY_SUITE_EXIT", result.returncode)
            return result.returncode
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print(f"BLOCKED: {type(exc).__name__}; incomplete proxy checks NOT RUN")
            return 3
        finally:
            for name in reversed(owned):
                labels = docker("inspect", "--format", "{{json .Config.Labels}}", name, check=False)
                if labels.returncode:
                    continue
                if json.loads(labels.stdout).get("zea.phase14.audit") != run_id:
                    raise RuntimeError("Cleanup ownership mismatch")
                docker("rm", "-f", name)
            print("CLEANUP: owned proxy-test containers removed")


if __name__ == "__main__":
    raise SystemExit(main())
