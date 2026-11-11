# Zea.Play 6.0.1 Export and Import Manager

Implemented in the supplied checkout on 29 October 2026. Evidence below is from source checks, browser fixtures and disposable databases. The running installation was not rebuilt or restarted, and no deployment or restore/reset against existing application data was performed.

## What changed

The Owner's Profile Settings now contains an Export and Import Manager with Entire Workspace and Custom Selection modes, searchable dataset cards, counts and dependencies, CSV/JSON selection, one ZIP download, related-data expansion, export summary, saved configurations, validated import previews, and separate export/import histories. The existing reset controls remain in a separate Danger Zone.

The requested reference screenshot was not attached. The implementation uses the existing navy/cyan theme. Desktop and mobile previews use intercepted fixture APIs, not live workspace data.

## Existing implementation reviewed

- `GET /admin/data/export` returned a JSON bundle. Profile Settings converted that bundle into separate browser-generated CSV downloads. This explains the multiple-download behavior.
- The original datasets were users, tasks, departments, achievements, rewards, user rewards, Kanban columns, notifications and user achievements. Tasks embedded subtasks, comments and dependency identifiers.
- `POST /admin/data/import` could import credential hashes, update users, and delete whole task/workspace scopes before replacement. That direct mutation endpoint now returns an actionable 409 requiring upload, validation, preview and confirmation through the new manager. Legacy file formats remain supported through that workflow.
- The legacy JSON export endpoint remains available, now without credential hashes and with the workspace isolation guard. It retains its historical limited format; use the new manager for the expanded dataset coverage.
- Reset uses Owner authorization, hashed OTPs, a ten-minute expiry and five failed attempts. Its original deletion list includes **all users**, followed by existing system seeding. The previous UI's promise that the Owner account remained intact was inaccurate. The UI now describes the actual behavior; the deletion scope was preserved.
- Core models and ticket models were reviewed, including task associations, chat, ticket lifecycle, approvals, rewards, badges, levels, tools, notifications and media metadata. Storage continues to use the application's existing infrastructure; no storage credentials or object bytes are included in an ordinary business-data archive.
- The existing webhook retry worker is specific to webhook delivery. No general-purpose backup queue was present. Export jobs use FastAPI background execution, existing database sessions and persisted job records; no queue service or dependency was added.

## Files modified or added for this task

| File | Change |
| --- | --- |
| `frontend/components/BackupManager.tsx` | New export, configuration, import/restore and history interface. |
| `frontend/pages/ProfileSettings.tsx` | Replaces browser export/import code with the manager; separates reset, adds explicit deletion acknowledgement and corrects its displayed scope. |
| `frontend/pages/Users.tsx` | Removes the password-hash column from the separate users CSV exporter; routes its existing user/department import entry points through the shared manager dialog. |
| `frontend/services/mockApi.ts` | Reuses the authenticated HTTP client and sends the explicit reset confirmation. |
| `backend/app/backups/registry.py` | Reviewed field allowlists for 70 datasets, explicit omissions, dependencies and additional application relationships. |
| `backend/app/backups/service.py` | Snapshot export, streaming serialization/ZIP writes, import staging, validation, conflict detection, transactional restore, timeouts and cleanup. |
| `backend/app/backups/http.py` | Rejects declared and chunked oversized uploads before multipart disk spooling. |
| `backend/app/backups/router.py` | Owner-authorized manager API, native download capabilities, scoped history and configuration CRUD. |
| `backend/app/backups/models.py` | Tenant-scoped job and preset metadata. |
| `backend/app/backups/maintenance.py` | Five-minute expiry cleanup task tied to application lifecycle. |
| `backend/app/backups/__init__.py` | Module entry point. |
| `backend/app/routers/data_admin.py` | Secures legacy export/import access and makes OTP consumption atomic with reset deletion; adds reset audit logging. |
| `backend/app/schemas.py` | Excludes the legacy backup hash field from serialization; adds server-validated reset confirmation. |
| `backend/app/main.py` | Registers manager routes under both API prefixes and starts/stops housekeeping. |
| `backend/alembic/versions/d4f6a8b0c2e4_backup_manager.py` | Additive job/preset migration with compatible startup-table adoption. |
| `backend/alembic/env.py` | Includes backup models in Alembic metadata so future autogeneration retains the tables. |
| `backend/tests/test_backup_manager.py` | Disposable SQLite/PostgreSQL API, archive, restore, migration, security and memory tests. |
| `frontend/checks/backup-manager.*` | Browser fixture and executable interaction checks. |
| `frontend/checks/backup-manager-*.png`, `*-results.json`, `*-build.txt`, `*-typecheck.txt` | Local verification artifacts. |
| `docs/backup-manager-*-tests.xml` | Backend test reports. |

Existing unrelated dirty changes were retained. No commit, push, shared database migration or deployment was performed.

## Backend API

Routes below are relative to `/admin/data/manager`; the application also registers them under `/api`.

| Method / route | Behavior |
| --- | --- |
| `GET /catalog` | Discovers registered datasets available in the schema, counts, relationships, exclusions and schema drift. |
| `POST /exports` | Validates selection and dependency acknowledgement, persists a job, and queues archive generation. |
| `GET /jobs` | Returns the last 100 jobs in the authorized workspace. |
| `POST /jobs/{id}/cancel` | Cancels queued/processing jobs. |
| `POST /jobs/{id}/download-ticket` | Creates a hashed, job-scoped download capability valid for 60 seconds. |
| `GET /jobs/{id}/download` | Consumes that capability once and streams the completed archive as an attachment. Also rechecks the initiating Owner's active access. |
| `POST /imports/validate` | Accepts ZIP/CSV/JSON, validates it and stages safe records without changing business data. |
| `POST /imports/{id}/preview` | Validates selected restore scope, relationships, uniqueness and insert/update impact; creates a new preview token. |
| `POST /imports/{id}/confirm` | Requires the current preview token and literal `RESTORE`; applies all changes in one transaction. |
| `GET /presets`, `POST /presets` | Lists/creates the current Owner's workspace-scoped configurations. |
| `PUT /presets/{id}`, `DELETE /presets/{id}` | Edits/renames or deletes a configuration. Duplication creates a separate configuration. |
| `POST /presets/{id}/run` | Revalidates access and executes a saved configuration. |

Manager endpoints return an actionable 503 if the metadata migration is missing. Configuration names are required and settings are validated rather than accepting arbitrary JSON keys.

## Migration and operation

Revision `d4f6a8b0c2e4`, based on `c3e5f7a9b1d2`, adds only `backup_jobs` and `export_presets`, with tenant indexes. It changes no business tables, identifiers or records. Because existing startup calls `Base.metadata.create_all`, the migration also validates and adopts compatible pre-created manager tables without clearing their records, and refuses incompatible layouts. Migration execution was tested only on disposable databases. The repository reports one Alembic head.

Apply the additive revision through the project's existing backup-first migration/release procedure before enabling the manager in an installation. This task did not apply it to the installed database.

`ZEA_BACKUP_DIR` configures private archive/staging storage. Its default is a private directory below the process's temporary directory. Configure a private persistent mount when archives should survive container replacement. The directory is not exposed through static media routes.

Archives and staging expire after 24 hours. Downloads are refused after expiry. Housekeeping runs every five minutes while the application is running and also on manager requests; busy files are retried on subsequent passes. History metadata remains available after archive expiry. Export jobs that outlive the 30-minute deadline are failed; expired pending import previews are cancelled.

## Backup format and coverage

The download is one server-generated ZIP:

```text
zea-play-backup-YYYY-MM-DD-<job-prefix>.zip
  manifest.json
  data/users.csv                 # or .json throughout
  data/tasks.csv
  data/departments.csv
  data/achievements.csv
  data/rewards.csv
  data/user-rewards.csv
  data/kanban-columns.csv
  data/notifications.csv
  ...other selected registered datasets
```

The manifest contains schema version 1, application version 6.0.1, UTC export time, actual workspace identifier, format/scope, selected datasets, per-file paths/fields/counts/SHA-256 checksums/dependencies, completion status and coverage limitations. Internal names are deterministic. A manifest is written only after every selected dataset has serialized successfully; only a finalized archive is published as Completed.

Coverage extends the original datasets with task subtasks/comments/messages/dependencies/followers, user achievements, badges/rules/progress, reward icons/history, approvals/transfers, safe audit metadata, tools/favorites, notification preferences, chat conversations/membership/messages/reactions/attachments/pins/mentions, points configuration, safe release metadata, email templates, task templates, media metadata, levels/nodes/edges/events, seasons/progress, navigation policy, feature flags, tickets and their lifecycle/comment/attachment/approval/task/history/ledger datasets. The precise field contract is `registry.py`.

New tables or unreviewed columns block Entire Workspace export until registered or explicitly excluded. New model columns are never automatically serialized. Custom selection still uses the reviewed allowlist. Whole-workspace coverage refers to these supported business datasets; it is not a physical database/media disaster-recovery image.

CSV is UTF-8 with standard quoting and CRLF records. The new CSV contract JSON-encodes each cell (`json-cells-v1`), so strings are reversible and cannot begin with a spreadsheet formula. JSON datasets are arrays of safe objects. This is intentional: spreadsheet strings can display literal JSON quotes; use the manager to restore them without conversion.

The server reads through bounded database cursor fetches, serializes rows and writes compressed ZIP members directly to a disk-backed partial file. It does not collect the archive or dataset arrays in browser memory. PostgreSQL export uses one repeatable-read transaction; SQLite explicitly begins a consistent read transaction. PostgreSQL also reports completed-file progress between datasets. Completed downloads use the framework's streaming file response and a no-store cache policy. Cancellation and deadline checks prevent incomplete archives from being published.

The implementation follows the standard [Python ZIP entry writer](https://docs.python.org/3/library/zipfile.html#zipfile.ZipFile.open) and [SQLAlchemy cursor/isolation controls](https://docs.sqlalchemy.org/en/20/core/connections.html).

## Import compatibility and safeguards

New ZIPs require the supported manifest version, matching workspace, complete file list, safe deterministic paths, field headers, counts and SHA-256 integrity. Validation rejects unsafe paths/entries, duplicate entries/identifiers, encrypted or symlink entries, oversized archives, unsupported versions and broken relationships. Files are read without extraction or code execution.

Legacy CSV supports one dataset per upload, selected explicitly; camelCase fields are mapped to the safe schema. Legacy JSON bundles and dataset arrays remain supported. Embedded legacy task subtasks/comments/dependencies are staged separately. Unsafe/unknown legacy fields are discarded with warnings. Legacy hashes never become active credentials.

Missing-user provisioning is off by default and requires a fresh preview after explicit Owner acknowledgement. Insert mode skips existing identifiers. Update mode inserts missing records and updates matching identifiers only after a fresh preview and explicit confirmation. Existing user role, status, email, employer scope, tenant and authentication remain under account management. For missing users, an optional explicit Owner acknowledgement enables inactive-account provisioning in the same restore transaction. It preserves identifiers, binds the current tenant/employer scope, forces the ordinary User role and deactivated status, and generates a fresh cryptographically random credential hash without exposing its password. After restoration, the Owner uses the existing Users password-reset and activation controls to recover access and assign roles separately. That existing password-reset endpoint was exercised in the disposable tests. No known default passwords or imported password hashes are applied.

Staging is private disk-backed SQLite, separate from business tables. Preview checks types, required identifiers/fields, declared and reviewed application relationships, duplicates and uniqueness conflicts. Account provisioning also validates email addresses and rejects conflicting identities. It records fingerprints of current records; confirmation rejects data changed since preview. Nullable cyclic references are resolved after inserts. Unique/database constraints remain authoritative. PostgreSQL restore runs serializably and locks the existing business tables while validating and applying the selection. Any constraint or application failure rolls back the complete restore. No restore mode truncates or deletes tables. Scoped replacement is deliberately unavailable.

Declared and chunked request sizes are capped before multipart parsing can spool oversized uploads. Limits are explicit: 32 MiB uploaded file, 32 MiB per ZIP dataset, 128 MiB total declared expansion, 250,000 staged records, and 30-minute validation/restore deadlines; PostgreSQL statements also have a 120-second timeout. Export has an 8 GiB serialization ceiling and an 8 MiB row limit. Select smaller scopes when these limits are reached. Export's supported size can exceed the single-upload restore limits.

## Security and reset

Exports use explicit permitted fields. Passwords/hashes, API/OAuth/SMTP credentials, reset tokens, push authentication and webhook secrets/delivery bodies are excluded. Opaque audit/event payloads and executable release-note HTML/CSS/JS are excluded as well. Those datasets carry metadata, not their omitted payloads.

Owner access in a database with multiple workspaces: the manager uses explicit row ownership rather than blocking the entire catalog. Tenant-keyed tables are scoped directly; legacy tables follow required relationships back to their workspace (for example task creator, subtask parent and notification recipient). Optional references to foreign records are cleared in exported files. Records with required foreign-workspace relationships and actorless audit records are excluded. Shared installation datasets are explicit: departments, kanban columns, achievements, badges/rules, reward icons, rewards, audit retention, tool categories, points configuration, release notes, seasons and feature flags. Owners can export/import these shared datasets as elsewhere in the application. Imports reject foreign primary-key collisions, tenant changes and foreign relationship targets, including attempts to claim tenant-less records by replacing their creator. Newly inserted tenant-keyed records are bound to the requesting workspace. Jobs and presets retain workspace scope; presets also require creator ownership. Archives are accessible only through authorized, expiring downloads. Legacy email-template tables without a tenant column are treated as shared installation settings; exported records carry the requesting workspace identifier, and restore adapts to the existing layout without adding columns or changing migration history. The legacy global JSON exporter and destructive reset retain their isolation guard because their global scopes were not changed.

Reset still requires the existing active Owner, valid OTP, expiry and attempt limits. The server additionally requires literal `RESET WORKSPACE`, and the UI requires acknowledgement of the displayed affected data. OTP consumption and the unchanged deletion list now share a database transaction, with an audit event. Existing seeding still runs after deletion commit. Reset does not run during export/import. A successful destructive reset/reseed was not executed during this task; installations with retained foreign-key dependents can reject that legacy reset scope safely.

## Validation evidence

| Check | Result |
| --- | --- |
| Scoped Python Ruff lint and formatting | PASS |
| Python module compilation | PASS |
| SQLite manager/security/task regression tests | PASS — see `backup-manager-sqlite-tests.xml`. |
| PostgreSQL 16 manager integration/security tests | PASS — see `backup-manager-postgres-tests.xml`. A separate disposable container/database was used. |
| 50,000-record CSV and JSON exports | PASS — each stayed below the 24 MiB `tracemalloc` Python-allocation ceiling. This does not measure total process RSS or certify every production workload. |
| Snapshot consistency under a concurrent edit | PASS on disposable SQLite and PostgreSQL. |
| New ZIP and legacy file compatibility | PASS for supported safe fields; explicit account provisioning and dependencies are enforced. |
| Partial export/restore failures, checksum tampering, invalid ZIP/CSV, cross-tenant and unauthorized requests | PASS in automated tests. |
| Startup-created table adoption, repeat migration and incompatible-layout refusal | PASS ? four focused migration checks on each disposable database; see the two `backup-manager-migration-*-tests.xml` reports. |
| Existing frontend unit tests | PASS — 41 tests. |
| Desktop/mobile browser checks | PASS — 7 checks, one download, one explicitly confirmed fixture restore, zero component errors. |
| Production frontend build | PASS, with the existing large-chunk warning. |
| Full TypeScript check | FAIL — 113 diagnostics in existing code, including Ballpit, seed fixtures, level/ticket types and unrelated portions of mockApi. No diagnostic points to the new manager component or its fixture. Details: `frontend/checks/backup-manager-typecheck.txt`. |
| Running-installation verification, shared migration, deployment, production restore/reset | NOT RUN. |

Backend checks cover single archive generation, file/manifest/count/checksum correctness, CSV/JSON round trips, custom selection/dependencies, persisted presets, legacy compatibility, credential exclusion, authorization/tenant isolation, bounded export allocations, failure cleanup, broken archives/headers, relationship ordering, rollback, insert idempotency, optimistic conflict detection, histories, expiry/cancellation, migration boundaries and reset's authentication/OTP guards. Browser checks exercise the native download trigger and verify that reloading does not start a duplicate download.

Remaining operational limits: media bytes need a separate storage backup; missing accounts require explicit inactive provisioning followed by password reset and activation; shared installation settings affect all workspaces, while required cross-workspace business relationships are excluded; legacy global reset/export remain blocked in shared databases; replacement is unsupported; uploads have the limits above; background export jobs do not resume automatically after process failure and must be rerun after their stale-job failure is recorded. These limits are exposed instead of labelling an incomplete physical backup as complete.


## Owner access correction (2026-10-29)

The catalog 403 was caused by the previous blanket isolation guard, after the active Owner role had already been accepted. `backend/app/backups/scope.py` now supplies the same row policy to catalog counts, archive queries, import relationship validation and restore authorization. The running local Docker backend is built from this checkout but does not mount its source; a backend rebuild is required to serve this correction. No running services were rebuilt/restarted and no installed database was restored, reset or migrated during this correction.

Read-only installed-schema verification: corrected catalog logic and all 70 export SELECT projections succeeded for each of the two local workspaces with no unregistered tables. The legacy email-template layout was present. This verification loaded the changed code into a separate short-lived process with a stand-alone metadata base and a PostgreSQL READ ONLY transaction, bypassing application startup migrations. It did not change the running HTTP backend.

Correction validation: PASS - 55 SQLite manager tests (`backup-manager-owner-scope-sqlite-tests.xml`); 51 PostgreSQL manager tests followed by 6 focused final-code workspace/legacy-template tests (`backup-manager-owner-scope-postgres-tests.xml`, `backup-manager-owner-scope-postgres-followup-tests.xml`); scoped Ruff and formatting checks. The disposable PostgreSQL container was removed. No frontend files changed in this correction. To apply locally from the project directory, run `docker compose up -d --build --no-deps backend`, then refresh Settings. This command was prepared but not executed.
