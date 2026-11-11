# Local V2 schema repair — 3 November 2026

> Subsequent port migration: use **http://localhost:7300**. The [7000-series port report](zeaplay-7000-ports.md) records current API/realtime/database/Redis addresses; the old addresses below retain the incident's historical context.

The reported `localhost:6300` CORS failures were secondary to backend database errors. The running application had new V2 ORM fields, while its persistent PostgreSQL database still had legacy columns. A successful image rebuild does not migrate existing tables.

Confirmed missing columns included `subtasks.planned_start_date`, `notifications.tenant_id`, `notification_preferences.sound_enabled` and `push_subscriptions.tenant_id`. The initial OPTIONS request already returned 200 with `Access-Control-Allow-Origin: http://localhost:6300`; unauthenticated reads returned 401 with that header. No CORS allowlist or credentials setting needed changing.

## Target and safeguards

Only the local `zeaplay_v1` Compose project in this checkout was repaired. Container project/workspace labels, existing backend image and frozen migration source hashes were checked. The database had no `alembic_version` and contained old columns alongside empty newer tables created by startup `create_all`.

The backend was paused to freeze its writers. A custom-format database backup was saved outside the repository in a directory restricted to the current Windows account and SYSTEM. Archive listing was validated, then the backup was actually restored into an owned PostgreSQL 16 container on an isolated internal Docker network. The restored copy contained private local data; neither its rows, credentials nor backup were exported into repository evidence. This is separate from earlier synthetic Phase 7 fixtures.

The protected repair directory is recorded in `$env:TEMP\zea-v2-local-schema-repair-current.txt`. It contains `before-v2-schema-repair.dump`, its checksum manifest and private operator logs. Keep it protected and do not stage or publish it.

## Repair

`backend/checks/reconcile_local_v2_schema.py` is an explicit operator helper, not automatic startup migration code. It:

- Requires PostgreSQL and an unversioned, recognized legacy schema; refuses partial/unknown adoption shapes and pre-existing policies/work contexts before initial adoption.
- Reuses the seven existing V2 migration implementations, with bounded lock/statement timeouts and an outer transaction. The historical migration files remain unchanged.
- Handles one observed startup drift explicitly: an empty workflow-settings table already has the later nullable JSON `reward_policy_data` column. Its actual shape/emptiness is checked first; only the Phase 1 adoption inspector projects that known optional column, and Phase 3 validates the real column. No column is dropped, renamed or rewritten.
- Validates all affected ORM column names and the existing readiness gate's 52 trigger/six index/data contracts. It deliberately does not claim the readiness script's Alembic-head check passed: no historical baseline was established or stamped.
- Compares all original-column/row fingerprints before committing. Existing subtasks receive legacy defaults, with no fake creation/actual timestamps, audit entries or reward recalculation.
- Verifies an already repaired schema without replaying old adoption revisions over newer records.

The restored-copy rehearsal passed. The same repair then passed on the paused local database, preserving original data across **85 tables**. Repeat verification passed on both the restored copy and local installation. The existing backend container was restarted; no frontend, presence or PostgreSQL container was rebuilt/recreated and no remote production deployment occurred.

Post-restart comparisons against the restored pre-repair snapshot confirmed unchanged user wallets, legacy subtask data and legacy point-ledger history.

## Executed checks

| Check | Result |
| --- | --- |
| New PostgreSQL reconciliation tests | **6 PASS**: mixed schema, repeat verification, versioned/unknown/policy refusal, interrupted-transaction rollback and incomplete-column detection |
| Ruff on the helper and new tests | **PASS** |
| Real authenticated local GETs across active Owner/Admin/Manager/User accounts | **300/300 HTTP 200**, covering auth, task activity, inbox and task page; every response had the expected origin header |
| Existing authorized task information sections | **5/5 HTTP 200**, Overview, Timeline, Subtasks, Points, Activity |
| Live push subscribe with deliberately invalid payload | **HTTP 422**, expected input-validation response with the CORS header |
| Valid push storage against local PostgreSQL | Tenant-scoped save/flush/read **PASS**, followed by rollback; **zero persisted test subscription rows** |
| Legacy preservation after restart | Wallets, legacy subtasks and legacy ledger fingerprints **unchanged** |

The storage test does not certify real browser subscription delivery or OS/provider push presentation. No test notification was sent. The current browser was not automatically reloaded; refresh `http://localhost:6300/#/tasks` to retry the requests.

Sanitized evidence is under `docs/verification/zeaplay-local-v2-schema-repair/`. Private backup/log data stays outside the repository. The six automated tests use a separate synthetic owned PostgreSQL instance, not the running local database. All owned rehearsal/test containers and the isolated network are removed afterward; installed services remain running.

## Recovery and remaining release gates

This fixes the local missing-column failure. It does not approve production release or silently establish an Alembic baseline for this historically unversioned installation. Future versioned rollout still requires an explicit installation-specific baseline/drift plan; do not blindly stamp or run the entire historical upgrade chain.

Retain the added schema and immutable history when rolling application code forward. Do not destructively downgrade, truncate ledgers/audits, recalculate old rewards or overwrite new writes with the pre-repair dump. If disaster recovery is required, restore the protected backup into a separately named database first and reconcile any post-backup writes before cutover.

The earlier final acceptance report retains its executed scope. Its credential, dependency, TypeScript/lint, legacy-regression and broader production/provider/accessibility gates remain open. This local repair is subsequent runtime evidence for the affected endpoints, not a replacement production certificate.
