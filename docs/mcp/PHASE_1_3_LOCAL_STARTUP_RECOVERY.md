# Phase 1.3 local startup recovery — 11 November 2026

Status: **APPLIED to the authorized local development database; backend startup and HTTP checks PASS.** A separate Redis chat-listener timeout remains unresolved. No remote production deployment was performed.

The supplied backend log ends in `RuntimeError: Apply Alembic l2b4d6f8a0c2 before starting authentication`. Read-only inspection confirmed the stopped backend belongs to this checkout's local development Compose project, `zeaplay_v1`, and targets PostgreSQL database `zeaplay` in `zeaplay_v1-postgres-1`, on volume `zeaplay_v1_postgres_data`.

The database is PostgreSQL 16.15. Both authentication tables, `users.auth_epoch` and the user invalidation trigger are absent. The startup guard correctly refuses to run authentication without its revocation authority. The CORS line and repeated framework lifespan frames are not the root cause.

This installation also has **no `alembic_version` table**, consistent with its [earlier local V2 reconciliation](../zeaplay-local-v2-schema-repair.md). A blind historical `alembic upgrade head` or predecessor stamp is inappropriate: neither the complete historical migration chain nor a versioned baseline has been established for this database.

## Prepared repair

An explicit operator script outside the repository reuses the unchanged canonical `l2b4d6f8a0c2` upgrade through Alembic Operations inside one outer PostgreSQL transaction. It does not import the application, execute startup helpers, replay other revisions, stamp migration history or weaken the startup guard.

The script defaults to read-only inspection and requires an explicit apply argument plus expected database identity. It refuses versioned, partial or unrecognized authentication schemas. During application it freezes existing row writers with bounded locks, fingerprints every original column/row, applies the frozen migration, verifies the resulting objects and compares all original data before commit. Only `users.auth_epoch`, its check constraint, the two authentication tables/indexes and invalidation function/trigger are added. No credentials are manufactured. Reapplication is refused.

The database backup and scripts are stored outside the repository in a directory restricted to the Windows user and SYSTEM:

`C:\Users\Lenovo\AppData\Local\ZeaPlay\recovery\phase13-20261111-161103`

The directory contains `before-auth-session-repair.dump`, `backup-manifest.json`, `repair_unversioned_auth.py`, the frozen canonical migration and `rehearsal-manifest.json`. These private artifacts must not be committed or published. `$env:TEMP\zea-phase13-recovery-current.txt` records the directory. The backup is 323,169 bytes; archive listing and a full disposable restore both passed.

## Executed verification

| Check | Result |
|---|---|
| Installed target identity and schema inspection | PASS, read-only |
| PostgreSQL custom-format backup and archive validation | PASS |
| Restore of that backup into owned tmpfs PostgreSQL on an isolated internal Docker network | PASS |
| Missing-schema inspection on the restored copy | PASS |
| Apply followed by deliberate transaction rollback; missing-schema state restored | PASS |
| Committed targeted migration on the restored copy | PASS |
| Original columns and rows across all 85 existing tables preserved | PASS |
| Added schema verified; no Alembic history fabricated | PASS |
| Reapplication rejected | PASS |
| Exact built-image `require_session_schema` function against the migrated copy | PASS |
| Owned rehearsal containers/network removed | PASS |
| Apply to installed local database and preserve its 85 original tables | PASS, authorized by the user |
| Restart only the existing local backend | PASS; application startup complete, running, restart count zero |
| Local `/health` | PASS, HTTP 200, version 6.1.7 |
| Unauthenticated `/auth/me`, `/api/auth/me`, `/api/tasks/page` | PASS, HTTP 401 |
| Login CORS preflight from `http://localhost:7300` | PASS, HTTP 200 and matching allow-origin |
| Installed session tables, epoch and enabled invalidation trigger | PASS; historical Alembic baseline remains unstamped |
| Authenticated browser login and full realtime integration | NOT RUN |
| Chat event-listener continuity | FAIL observed after startup: unhandled Redis socket timeout; unrelated source left unchanged |

The rehearsal startup-gate check executed the actual function from the built backend image without importing application startup. After authorization, the installed backend also logged `Application startup complete` and passed the HTTP checks above. This does not certify authenticated browser or realtime workflows.

## Authorized local execution

The earlier Phase 1.3 request explicitly prohibited migrations on existing databases. After reviewing the backup and successful rehearsal, the user authorized: **"Apply the local repair and restart."** This authorization was limited to the local `zeaplay_v1` database and its backend.

The local project/database/volume, stopped backend, built-image identity, frozen script/migration and backup hashes were rechecked. The same guarded transaction then committed successfully against the installed database, preserving all original columns and rows across 85 tables. Only the existing backend container was started; frontend, presence, PostgreSQL and Redis were not restarted or recreated. No application source changed. Private `installed-apply.log` and `installed-apply-manifest.json` record the action in the protected recovery directory.

Refresh the local frontend and sign in again: legacy credentials cannot satisfy the new session contract. The reported missing-schema startup failure is resolved. The unchanged `backend/app/chat/realtime.py` listener subsequently raised `redis.exceptions.TimeoutError: Timeout reading from socket`; HTTP remains available, but that separate chat-realtime defect requires its own correction and verification.

This repair does not certify a historical Alembic baseline, authorize production deployment or change the Phase 2/MCP NO-GO assessment. Retain the added revocation state; do not use a destructive downgrade as rollback.
