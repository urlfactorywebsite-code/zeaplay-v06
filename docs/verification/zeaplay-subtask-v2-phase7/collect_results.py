"""Archive explicitly selected synthetic verification evidence, never config/data."""
import gzip
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(sys.argv[1]).resolve()
assert root.name.startswith("zeaplay-phase7-") and (root / "OWNED-VERIFICATION.txt").is_file()
destination = Path(__file__).resolve().parent
repo = destination.parents[2]
names = [
    "baseline-all-complete", "pg-regression", "sqlite-regression", "pg-final", "sqlite-final",
    "pg-phase7-final1", "pg-fixes-profile", "rollout-gate-final", "redis-final",
    "pg-security-final", "pg-authorized-user", "sqlite-system-security-final",
    "sqlite-concurrency-fixed", "sqlite-final-regression-repairs", "linux-python311-final",
    "test_generate_token", "test_oauth2_server", "test_task_list", "test_ticket_tenant_permissions", "test_chat_phase1",
]
results, profiles = {}, []
for name in names:
    path = root / (name + ".xml")
    if path.exists():
        document = ET.parse(path)
        suites = list(document.iter("testsuite"))
        result = {key: sum(int(suite.get(key, 0)) for suite in suites) for key in ("tests", "failures", "errors", "skipped")}
        result["seconds"] = round(sum(float(suite.get("time", 0)) for suite in suites), 3)
        result["passed"] = result["tests"] - result["failures"] - result["errors"] - result["skipped"]
        result["problems"] = []
        for case in document.iter("testcase"):
            for kind in ("failure", "error"):
                problem = case.find(kind)
                if problem is not None:
                    result["problems"].append({"test": case.get("name"), "kind": kind, "message": problem.get("message", "")[:400]})
            for prop in case.findall("./properties/property"):
                value = prop.get("value")
                try:
                    value = json.loads(value)
                except (ValueError, TypeError):
                    pass
                profiles.append({"run": name, "test": case.get("name"), "property": prop.get("name"), "value": value})
        results[name] = result
        (destination / (name + ".xml.gz")).write_bytes(gzip.compress(path.read_bytes(), mtime=0))
    log = root / (name + ".log")
    if log.exists():
        (destination / (name + ".log.gz")).write_bytes(gzip.compress(log.read_bytes(), mtime=0))
for name in ["node-final.log", "build-final.log", "tsc-final.log", "npm-audit.json",
             "backend-dependency-audit.json", "backend-fixture-versions.txt", "dependency-scope.json",
             "presence-test.log", "presence-audit.json", "full-sqlite-final.log", "compose-check.log", "alembic-heads.log"]:
    path = root / name
    if path.exists():
        (destination / (name + ".gz")).write_bytes(gzip.compress(path.read_bytes(), mtime=0))
(destination / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
(destination / "profiles-and-query-plans.json").write_text(json.dumps(profiles, indent=2), encoding="utf-8")
owned = [
    "backend/app/routers/auth.py", "backend/app/services/audit_logger.py", "backend/app/services/task_events.py",
    "backend/app/ws/tasks.py", "backend/app/main.py", "frontend/components/Header.tsx",
    "backend/tests/conftest.py", "backend/tests/test_subtask_schema_rehearsal.py", "backend/tests/test_navigation_sockets.py",
    "backend/checks/phase7_browser_app.py", "backend/sql/zeaplay_v2_phase7_readiness.sql",
    *[str(path.relative_to(repo)).replace("\\", "/") for path in (repo / "backend/tests").glob("test_phase7_*.py")],
]
manifest = [{"path": name, "sha256": hashlib.sha256((repo / name).read_bytes()).hexdigest(),
             "verification_copy_matches": (root / name).exists() and (root / name).read_bytes() == (repo / name).read_bytes()}
            for name in sorted(owned)]
(destination / "source-sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps({name: {k: value[k] for k in ("passed", "failures", "errors", "skipped")} for name, value in results.items()}, indent=2))
