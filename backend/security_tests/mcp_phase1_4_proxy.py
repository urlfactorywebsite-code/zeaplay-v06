"""Real HTTP checks inside the launcher's network-none namespace, never app.main.

Reuse fixture/DB guards. The only IO guard extension permits numeric loopback
HTTP at the two fixed ports in this namespace. All other Python IO stays denied.
"""
import ast
from pathlib import Path
import sys
import time

assert Path("/.dockerenv").exists() and Path.cwd() == Path("/scratch")
# python-magic probes the local linker via subprocess during import on Linux.
# Resolve that optional dependency before the strict application IO guard.
# The outer container already has no network and a read-only filesystem.
try:
    import magic  # noqa: F401
except ImportError:
    sys.modules["magic"] = None  # Preserve the app's normal optional-import fallback.
    print("OPTIONAL DEPENDENCY: libmagic unavailable; upload/media paths NOT RUN", flush=True)
import httpx
import uvicorn
fixture_path = Path(__file__).with_name("mcp_phase1_3_cases.py")
tree = ast.parse(fixture_path.read_text())
guard = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "io_guard")
guard.body[:0] = ast.parse('''
if event in {"socket.bind", "socket.connect"}:
    address = args[1]
    ports = {7211} if event == "socket.bind" else {80, 7211}
    if isinstance(address, tuple) and address[0] == "127.0.0.1" and address[1] in ports:
        return
if event == "socket.getaddrinfo" and args[0] == "127.0.0.1" and args[1] in {80, 7211}:
    return
''').body
namespace = {"__name__": "proxy_fixture", "__file__": str(fixture_path)}
exec(compile(ast.fix_missing_locations(tree), str(fixture_path), "exec"), namespace)
(PGFixture, Session, engine, m, tm, text, command, config, unittest, threading) = (
    namespace[name] for name in ("PGFixture", "Session", "engine", "m", "tm", "text",
        "command", "config", "unittest", "threading"))
from app.routers import comments, logs  # noqa: E402


class RealProxyAudit(PGFixture):
    def test_direct_and_nginx_routes_enforce_same_current_authority(self):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE audit_logs DROP COLUMN tenant_id CASCADE"))
        command.upgrade(config, "m3c5e7f9a1d3")
        with Session(engine) as db:
            for ident, tenant, actor in (("proxy-audit-a", self.tenant, "member"), ("proxy-audit-b", self.foreign, "foreign")):
                db.add(m.AuditLog(id=ident, tenant_id=tenant, actor_id=self.ids[actor], action="FIXTURE",
                    category=m.AuditLogCategoryEnum.AUTOMATION, entity_type="task",
                    entity_id="assigned" if actor == "member" else "foreign-task"))
            db.commit()
        for router in (comments.router, logs.router):
            self.app.include_router(router)
            self.app.include_router(router, prefix="/api")
        server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=7211,
            log_level="error", access_log=False, lifespan="off"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        def stop():
            server.should_exit = True
            thread.join(timeout=10)
        self.addCleanup(stop)
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertTrue(server.started)
        count = 0
        with httpx.Client(timeout=10, trust_env=False) as client:
            # Nginx strips exactly one /api prefix. Include double-prefixed
            # requests to exercise the backend /api aliases through real Nginx.
            for origin, prefix in (("http://127.0.0.1:7211", ""), ("http://127.0.0.1:7211", "/api"),
                                   ("http://127.0.0.1", "/api"), ("http://127.0.0.1", "/api/api")):
                def request(method, path, actor="member", expected=(200,), **kwargs):
                    nonlocal count
                    response = client.request(method, origin + prefix + path, headers=self.headers(actor), **kwargs)
                    self.assertIn(response.status_code, expected, f"{method} {prefix + path}: {response.status_code} {response.text}")
                    if origin == "http://127.0.0.1":
                        self.assertIn("nginx", response.headers.get("server", ""))
                    count += 1
                    return response
                request("GET", "/auth/me")
                request("GET", "/tasks/assigned")
                request("GET", "/tasks/sibling", expected=(403, 404))
                request("GET", "/tasks/foreign-task", "owner", expected=(403, 404))
                request("PATCH", "/tasks/assigned", "watcher", expected=(403,), json={"description": "Forbidden"})
                request("POST", "/tasks/assigned/transfer-requests", "owner", expected=(400, 403, 404),
                        json={"to_user_id": self.ids["foreign"]})
                request("POST", "/tickets", expected=(400, 403, 404), json={"title": "Forbidden",
                        "description": "Synthetic", "owner_id": self.ids["foreign"]})
                for resource in ("logs", "tasks"):
                    request("GET", f"/tickets/{self.tickets[0]}/{resource}")
                    request("GET", f"/tickets/{self.tickets[0]}/{resource}", "peer", expected=(403, 404))
                    request("GET", f"/tickets/{self.tickets[1]}/{resource}", "owner", expected=(403, 404))
                audits = request("GET", "/logs/audit", "owner").json()
                self.assertEqual([row["id"] for row in audits["items"]], ["proxy-audit-a"])
                inbox = request("GET", "/notifications/inbox").json()
                self.assertNotIn("foreign-task", str(inbox))
                # Real authentication parsing, persistence, rotation and logout
                # at every transport path. Tokens stay in memory, never output.
                login = client.post(origin + prefix + "/auth/login", json={"username": "member@phase1.example.com",
                    "password": "fixture-password"})
                self.assertEqual(login.status_code, 200, login.text)
                pair = login.json()["token"]
                rotated = client.post(origin + prefix + "/auth/refresh", json={"refresh_token": pair["refresh_token"]})
                self.assertEqual(rotated.status_code, 200)
                headers = {"Authorization": "Bearer " + pair["access_token"]}
                logout = client.post(origin + prefix + "/auth/logout", headers=headers)
                self.assertIn(logout.status_code, (200, 204))
                self.assertEqual(client.get(origin + prefix + "/auth/me", headers=headers).status_code, 401)
                self.assertEqual(client.post(origin + prefix + "/auth/refresh", json={"refresh_token": pair["refresh_token"]}).status_code, 401)
                count += 5
            print(f"REAL_HTTP_CHECKS {count}: direct, direct /api, Nginx /api, Nginx /api/api; auth and resource denials", flush=True)
        with Session(engine) as db:
            self.assertEqual(db.get(m.Task, "assigned").assigned_to_id, self.ids["member"])
            self.assertEqual(db.get(tm.Ticket, self.tickets[0]).title, "Own tenant ticket")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RealProxyAudit))
    raise SystemExit(0 if result.wasSuccessful() else 1)
