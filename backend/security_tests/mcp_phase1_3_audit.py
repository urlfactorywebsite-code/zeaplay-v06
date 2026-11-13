"""Independent adversarial acceptance tests; use the owning launcher --audit.

Reuse the isolation boundary and fixture, not the implementation assertions.
Every database transaction here targets the launcher's disposable PostgreSQL.
"""
from pathlib import Path
import runpy

base = runpy.run_path(str(Path(__file__).with_name("mcp_phase1_3_cases.py")))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

# Bind only reviewed fixture exports; avoid collecting any installed-app tests.
(PGFixture, Session, engine, decode_token_claims, AuthRefreshToken, AuthSession,
 auth_sessions, patch, event, select, func, text, inspect, threading, time,
 ThreadPoolExecutor, timedelta, m, command, config, unittest, replica) = (
    base[name] for name in (
        "PGFixture", "Session", "engine", "decode_token_claims", "AuthRefreshToken", "AuthSession",
        "auth_sessions", "patch", "event", "select", "func", "text", "inspect", "threading", "time",
        "ThreadPoolExecutor", "timedelta", "m", "command", "config", "unittest", "replica"))


class IndependentAudit(PGFixture):
    def test_preloaded_refresh_record_cannot_hide_committed_consumption(self):
        original = self.login()
        claims = decode_token_claims(original["refresh_token"], refresh=True)
        with Session(engine) as stale:
            held = stale.get(AuthRefreshToken, claims["jti"])
            self.assertIsNone(held.consumed_at)
            successor = self.refresh(original)
            self.assertEqual(successor.status_code, 200)
            with patch.object(auth_sessions, "_pair", wraps=auth_sessions._pair) as mint:
                with self.assertRaises(HTTPException) as failure:
                    auth_sessions.rotate(stale, original["refresh_token"])
                self.assertEqual(failure.exception.status_code, 401)
                mint.assert_not_called()
        self.assert_revoked(successor.json())

    def test_rotation_failure_rolls_back_consumption_and_successor_together(self):
        original = self.login()
        claims = decode_token_claims(original["refresh_token"], refresh=True)
        def fail_after_flush(db):
            db.flush()  # Execute both SQL mutations before simulating failed commit.
            raise RuntimeError("injected commit failure")
        with Session(engine) as db:
            event.listen(db, "before_commit", fail_after_flush)
            with self.assertRaisesRegex(RuntimeError, "injected commit failure"):
                auth_sessions.rotate(db, original["refresh_token"])
            db.rollback()
            event.remove(db, "before_commit", fail_after_flush)
        with Session(engine) as db:
            rows = db.scalars(select(AuthRefreshToken).where(AuthRefreshToken.session_id == claims["sid"])).all()
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0].consumed_at)
            self.assertIsNone(rows[0].replaced_by)
        self.assertEqual(self.refresh(original).status_code, 200)

    def wait_for_blockers(self, pids):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            with engine.connect() as connection:
                blocked = connection.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(:pids) "
                    "AND cardinality(pg_blocking_pids(pid)) > 0"), {"pids": pids})
            if blocked == len(pids):
                return
            time.sleep(0.02)
        self.fail("PostgreSQL did not show every contender blocked on the held user row")

    def test_postgresql_observed_lock_contention_allows_one_rotation(self):
        original = self.login()
        pids, ready = [], threading.Barrier(3)
        def contender():
            with Session(engine) as db:
                pids.append(db.scalar(text("SELECT pg_backend_pid()")))
                ready.wait(timeout=10)
                try:
                    return 200, auth_sessions.rotate(db, original["refresh_token"]).model_dump()
                except HTTPException as exc:
                    return exc.status_code, None
        with Session(engine) as holder, ThreadPoolExecutor(max_workers=2) as executor:
            auth_sessions.lock_user(holder, self.ids["member"])
            futures = [executor.submit(contender) for _ in range(2)]
            try:
                ready.wait(timeout=10)
                self.assertEqual(len(set(pids)), 2)
                self.wait_for_blockers(pids)
            finally:
                holder.rollback()
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sorted(status for status, _ in results), [200, 401])
        self.assert_revoked(next(pair for status, pair in results if status == 200))
        with Session(engine) as db:
            rows = db.scalars(select(AuthRefreshToken).where(
                AuthRefreshToken.session_id == decode_token_claims(original["access_token"])["sid"])).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(sum(row.consumed_at is not None for row in rows), 1)

    def test_tenant_writer_blocks_and_invalidates_waiting_rotation(self):
        original = self.login()
        ready, pids = threading.Event(), []
        def contender():
            with Session(engine) as db:
                pids.append(db.scalar(text("SELECT pg_backend_pid()")))
                ready.set()
                try:
                    auth_sessions.rotate(db, original["refresh_token"])
                    return 200
                except HTTPException as exc:
                    return exc.status_code
        with engine.connect() as writer, ThreadPoolExecutor(max_workers=1) as executor:
            writer.execute(text("UPDATE users SET tenant_id=:tenant WHERE id=:id"),
                           {"tenant": self.foreign, "id": self.ids["member"]})
            future = executor.submit(contender)
            try:
                self.assertTrue(ready.wait(10))
                self.wait_for_blockers(pids)
            finally:
                writer.commit()
            self.assertEqual(future.result(timeout=15), 401)
        self.change_user("member", tenant_id=self.tenant)
        self.assert_revoked(original)
        self.assertEqual(self.access(self.login()).status_code, 200)

    def test_access_identity_map_refresh_and_database_unavailability_fail_closed(self):
        original = self.login()
        claims = decode_token_claims(original["access_token"])
        with Session(engine) as stale:
            held = auth_sessions.validate_session(stale, claims)
            self.assertIsNone(held[1].revoked_at)
            self.assertEqual(self.client.post("/auth/logout", headers={
                "Authorization": "Bearer " + original["access_token"]}).status_code, 204)
            with self.assertRaises(HTTPException):
                auth_sessions.validate_session(stale, claims)
        fresh = self.login()
        with Session(engine) as disconnected:
            pid = disconnected.scalar(text("SELECT pg_backend_pid()"))
            with engine.begin() as killer:
                self.assertTrue(killer.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}))
            with self.assertRaises(DBAPIError):
                auth_sessions.validate_session(disconnected, decode_token_claims(fresh["access_token"]))
        self.assertEqual(self.access(fresh).status_code, 200)

    def test_cleanup_skip_locked_batches_cascade_and_indexes(self):
        expired = [self.login() for _ in range(3)]
        live = self.login()
        ids = [decode_token_claims(pair["access_token"])["sid"] for pair in expired]
        with Session(engine) as db:
            for sid in ids:
                session = db.get(AuthSession, sid)
                session.created_at = auth_sessions.now() - timedelta(days=40)
                session.expires_at = auth_sessions.now() - timedelta(days=31)
            db.commit()
        with Session(engine) as holder, Session(engine) as first, Session(engine) as second:
            holder.execute(select(AuthSession).where(AuthSession.id == ids[0]).with_for_update()).one()
            # Both workers keep their transactions open, proving SKIP LOCKED,
            # rather than merely running cleanup twice after each other's commit.
            first.execute(text("SET LOCAL statement_timeout='2s'"))
            second.execute(text("SET LOCAL statement_timeout='2s'"))
            self.assertEqual(auth_sessions.cleanup_expired(first, batch_size=1), 1)
            self.assertEqual(auth_sessions.cleanup_expired(second, batch_size=1), 1)
            first.commit()
            second.commit()
            holder.rollback()
        with Session(engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.id.in_(ids))), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(AuthRefreshToken).where(AuthRefreshToken.session_id.in_(ids))), 1)
            self.assertEqual(auth_sessions.cleanup_expired(db), 1)
            db.commit()
            self.assertEqual(db.scalar(select(func.count()).select_from(AuthRefreshToken).where(AuthRefreshToken.session_id.in_(ids))), 0)
            self.assertEqual(db.get(m.User, self.ids["member"]).auth_epoch, 0)
        inspector = inspect(engine)
        indexes = {index["name"]: index["column_names"] for index in inspector.get_indexes("auth_sessions")}
        self.assertEqual(indexes["ix_auth_sessions_retention"], ["expires_at", "id"])
        self.assertEqual(indexes["ix_auth_sessions_user_revoked"], ["user_id", "revoked_at"])
        self.assertIn(["session_id"], [index["column_names"] for index in inspector.get_indexes("auth_refresh_tokens")])
        self.assertIn(["digest"], [item["column_names"] for item in inspector.get_unique_constraints("auth_refresh_tokens")])
        self.assertEqual(self.access(live).status_code, 200)

    def test_migration_failure_rolls_back_partial_ddl_and_preserves_business_rows(self):
        def business():
            with engine.connect() as connection:
                return {table: connection.execute(text(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY id")).scalars().all()
                        for table in ("tasks", "tickets", "subtasks")}
        before = business()
        command.downgrade(config, "k1a3c5e7f9b1")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE auth_sessions (sentinel text)"))
            connection.execute(text("INSERT INTO auth_sessions VALUES ('owned disposable conflict')"))
        with self.assertRaises(DBAPIError):
            command.upgrade(config, "l2b4d6f8a0c2")
        with engine.begin() as connection:
            self.assertNotIn("auth_epoch", {column["name"] for column in inspect(connection).get_columns("users")})
            self.assertEqual(connection.scalar(text("SELECT version_num FROM alembic_version")), "k1a3c5e7f9b1")
            self.assertEqual(connection.scalar(text("SELECT sentinel FROM auth_sessions")), "owned disposable conflict")
            connection.execute(text("DROP TABLE auth_sessions"))
        command.upgrade(config, "l2b4d6f8a0c2")
        self.assertEqual(business(), before)
        auth_sessions.require_session_schema(engine)
        self.assertEqual(self.access(self.login()).status_code, 200)

    def test_migration_lock_timeout_leaves_predecessor_intact(self):
        command.downgrade(config, "k1a3c5e7f9b1")
        with engine.connect() as reader:
            reader.execute(text("SELECT id FROM users LIMIT 1")).first()
            with self.assertRaises(DBAPIError) as failure:
                command.upgrade(config, "l2b4d6f8a0c2")
            self.assertEqual(failure.exception.orig.pgcode, "55P03")  # lock_not_available
            reader.rollback()
        with engine.connect() as connection:
            self.assertNotIn("auth_epoch", {column["name"] for column in inspect(connection).get_columns("users")})
            self.assertEqual(connection.scalar(text("SELECT version_num FROM alembic_version")), "k1a3c5e7f9b1")
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM users")), len(self.ids))
        command.upgrade(config, "l2b4d6f8a0c2")
        auth_sessions.require_session_schema(engine)


if __name__ == "__main__":
    if not replica:
        outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IndependentAudit))
        if not outcome.wasSuccessful():
            raise SystemExit(1)
    raise SystemExit(base["main"]())
