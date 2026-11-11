# ZeaPlay V2 Phase 7 rollout and recovery

> Final release gates: consult the [latest acceptance matrix](zeaplay-subtask-v2-final-acceptance.md) and [deployment checklist](zeaplay-subtask-v2-deployment-checklist.md). The final review strengthened the SQL gate and found tracked credential material. Complete credential rotation/source hygiene and the other failing/unverified gates before using this runbook. No deployment is authorized by these documents.

Prepared 3 November 2026. **Preparation only: no deployment, installed-service restart or shared-database migration was performed.** The release gates in [the verification report](zeaplay-subtask-v2-phase7-verification.md) are currently **not all green**. These are executable operator instructions for a subsequently authorized release, not evidence of production execution.

## Required release gates

1. Review a bounded release containing the complete Phase 1–6 dependency set plus Phase 7 repairs. The shared checkout contains unrelated dirty changes; do not publish its entire diff or stage everything. Retain the approved commit/artifact identifiers and verification manifest.
2. Resolve or explicitly accept the separately documented TypeScript, lint, dependency-security and legacy-regression failures. Validate the built release images and configured external integrations in staging. The local frontend checks used Node 24; the source frontend Dockerfile uses Node 18. The Python compatibility check used a disposable Python 3.11 image, not a new production image build.
3. Establish the target's actual Compose files, project name, database major version, volume names, current revision and worker images. `docker-compose.yml` is development configuration and currently uses PostgreSQL 16. `docker-compose.prod.yml` uses PostgreSQL 15 and prebuilt application/worker images. `docker-compose.github.yml` overrides the backend/frontend/presence with source builds. Do not switch an existing installation between these definitions or PostgreSQL versions as part of this release.
4. Rehearse on a restored, sanitized target-schema copy. The automated rehearsal used actual ORM-derived legacy schema and synthetic data, not a downloaded production backup. Compare schema drift, constraints, legacy balances and original-column fingerprints. Unknown/unversioned installations require an explicit additive reconciliation plan before Alembic; never blindly stamp them.
5. Record an encrypted/access-restricted database and media backup, verify the archive, perform a separate restore rehearsal, and establish a compatible rollback artifact. Identify every task/reward writer, including externally supplied workers. The production Compose references Celery/reporting modules not present in this source checkout; their compatibility is not certified here.

## Migration dependency order

The existing pre-V2 revision is `d4f6a8b0c2e4`. Apply the linear chain in order:

| Revision | Purpose |
| --- | --- |
| `e5a7c9d1f3b5` | Subtask planning/actual/policy/version fields, task-linked immutable audit/ledger, manual intervals and activation settings |
| `f6b8d0e2a4c6` | Workflow marker/status, audit and reference guards |
| `g7c9e1f3a5d7` | New-policy reward calculation inputs, stable order, deletion and captured timezone |
| `h8d0f2a4c6e8` | Accounting/ownership/immutability guards |
| `i9e1a3c5d7f9` | Personal activity slots and immutable manual-work corrections |
| `j0f2b4d6e8a0` | Existing notification storage/preferences/device binding extensions |
| `k1a3c5e7f9b1` | Pending-notification chronology index |

Phase 7 introduces **no schema migration and no historical reward backfill**. Its SQL readiness script is read only. Each revision was tested for an immediate retry before advancing. Replaying a historical adoption revision over a later expanded schema is deliberately rejected; normal `alembic upgrade head` uses the version table and does not replay applied revisions.

PostgreSQL migrations use bounded locks/timeouts and transactional changes. Large indexes are not all created concurrently. A fully uninterrupted rollout is therefore not promised: use a short, controlled write-maintenance window, or separately rehearse an online-index strategy on the actual large target. Do not mix pre-V2 task writers with newly managed subtasks.

## Backup and image preparation commands

The following Bash commands apply **only to an installation already using the production plus GitHub source-build Compose topology**. Run from its reviewed repository checkout. Existing protected `.env.production` is supplied to Compose; do not print it, run expanded `compose config`, or copy it into the release evidence.

```bash
set -eu
cd "$(git rev-parse --show-toplevel)"
compose=(docker compose --env-file .env.production -f docker-compose.prod.yml -f docker-compose.github.yml)
"${compose[@]}" config --quiet
"${compose[@]}" ps

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root="${ZEAPLAY_BACKUP_ROOT:-$HOME/zeaplay-rollout-backups}/$stamp"
umask 077
mkdir -p "$backup_root"

"${compose[@]}" exec -T postgres sh -ceu \
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version"' \
  > "$backup_root/revision-before.txt"

"${compose[@]}" exec -T postgres sh -ceu \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
  > "$backup_root/database.dump"
test -s "$backup_root/database.dump"
"${compose[@]}" exec -T postgres pg_restore --list \
  < "$backup_root/database.dump" > "$backup_root/restore-list.txt"
test -s "$backup_root/restore-list.txt"

backend_id="$("${compose[@]}" ps -q backend)"
test -n "$backend_id"
media_volume="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/media"}}{{.Name}}{{end}}{{end}}' "$backend_id")"
test -n "$media_volume"
docker run --rm --network none \
  --mount "type=volume,source=$media_volume,target=/media,readonly" \
  --mount "type=bind,source=$backup_root,target=/backup" alpine \
  sh -ceu 'tar -czf /backup/media.tar.gz -C /media .'

for service in backend frontend; do
  image_id="$("${compose[@]}" images -q "$service")"
  test -n "$image_id"
  docker image tag "$image_id" "zeaplay-v06/$service:phase7-before-$stamp"
done

cat > "$backup_root/rollback-images.yml" <<EOF
services:
  backend:
    image: zeaplay-v06/backend:phase7-before-$stamp
  frontend:
    image: zeaplay-v06/frontend:phase7-before-$stamp
EOF

"${compose[@]}" build backend frontend
```

Archive listing is not a successful restore test. Restore the dump and media into a separately named disposable database/volumes, validate constraints, relationships, row/balance fingerprints, and run the integration scenarios there before continuing. If media is a bind mount or external storage instead of the expected named volume, the command stops; use the installation's approved storage backup procedure. Backups contain private data and must remain protected outside public artifacts and Git.

## Migration, backend rollout, frontend activation

1. Confirm `revision-before.txt` is a known predecessor in the chain above or the current head. A missing `alembic_version`, another branch, or schema/model drift is a stop condition. Earlier unrelated migrations include assumptions about task tenant columns; a blind full-history upgrade from an unknown schema is unsafe.
2. Pause task/reward mutations and confirmed external writers using the deployment's maintenance procedure. For the API, the actual Compose control is `"${compose[@]}" stop backend`. Do not stop or rebuild unrelated worker integrations without checking their ownership and compatibility. No maintenance-mode feature flag is enforced by this application.
3. Apply the migration from the new backend image, before starting new application writers:

```bash
"${compose[@]}" run --rm --no-deps --entrypoint python backend \
  -m alembic -c alembic.ini upgrade head
"${compose[@]}" run --rm --no-deps --entrypoint python backend \
  -m alembic -c alembic.ini current

"${compose[@]}" exec -T postgres sh -ceu \
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
  < backend/sql/zeaplay_v2_phase7_readiness.sql
```

Alembic's environment imports the existing database module, which has legacy compatibility helpers. These commands must be confined to a backed-up, reconciled schema; they are not a substitute for a schema review. The readiness SQL checks the exact head, essential unique/index/trigger presence, tenant ownership, reversal shape, mandatory managed planning and active-slot invariants without repairing data or emitting identifiers.

4. Start the new backend, validate it, then activate the frontend:

```bash
"${compose[@]}" up -d --no-deps --no-build backend
"${compose[@]}" exec -T backend python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7211/health', timeout=5)"
"${compose[@]}" up -d --no-deps --no-build frontend
"${compose[@]}" ps
```

`/health` is a liveness response, **not a database readiness proof**. Also run the read-only SQL gate and authenticated checks for `/api/auth/me`, `/api/tasks/activity`, `/api/notifications/inbox`, all five `/api/tasks/{task_id}/information` sections, and both HTTP aliases as applicable. Use a dedicated staging/pilot task, not an employee's real work. Keep access tokens out of shell history and logs.

5. Verify `/api/ws/tasks` authentication, live fanout, Redis reconnect/resync, new service-worker activation, and device account binding. Reuse existing push permission; request new browser permission only through the existing user action. A browser-denied test must still receive in-app alerts. Check badge updates, preferences and watcher removal with actual accounts.
6. Enable new additional rewards for a pilot tenant only after approval, through the existing Owner configuration UI/API. Resume the other verified writers and expand the pilot only after accounting and capacity checks remain stable.

### Actual controls and configuration

- `GET/PATCH /api/config/subtask-rewards` is Owner-only and uses `expected_version`. Its `enabled` switch controls enrollment of **future** subtasks in `subtask-additional-v1`. Disabling it is not a payout freeze and does not reclassify existing managed or rewarded rows. Existing policy children still reconcile; legacy rewards remain unchanged.
- Every newly created subtask uses managed workflow and requires planning, regardless of the reward switch. The user explicitly chose this behavior. Historical checklist rows remain legacy until an authorized explicit workflow enrollment.
- Stored catalog flags such as `tasks.subtasks`, `tasks.points`, `tasks.time_tracking` are not reliable backend kill switches. Do not use them as a write freeze.
- Existing per-user notification preferences control deadline hours, optional productive capacity, overtime threshold, sound, push and quiet hours. No organization-wide working-hours default is introduced.
- `VEE_NOTIFICATION_RETENTION_DAYS` controls read/dismissed content retention, default 30; deduplication identities and unread rows are retained. The aggregate notification maintenance thread runs within each API process. There is no new Celery queue, one job per user, or independent notification worker command.
- Existing Redis/cache connection configuration and VAPID/Web Push/n8n configuration remain the canonical integration settings. Never put provider secrets into `VITE_*` variables. `X-Zea-Push-Binding` must remain exposed by the existing CORS configuration.

## Health observations and rollback criteria

Observe API errors/latency, database lock waits/deadlocks, SQL gate results, new-policy ledger/net balance deltas per scope, slot occupancy, task-event reconnect warnings, notification `selected/processed/retried/suppressed/due_remaining` counters, oldest pending age and provider failures. In-app storage is idempotent; external Web Push/n8n delivery remains at least once. Provider consumers must deduplicate notification IDs.

Immediately stop activation/writes for any tenant mismatch, unauthorized task/notification visibility, duplicate financial credit, lost audit event, more than five active parents, overwritten manual actual time, migration failure or legacy reward drift. Pause expansion for persistent latency/lock/backlog regressions against the installation's measured baseline; no arbitrary global latency or daily-hours limit is introduced by this release.

## Data-preserving rollback and recovery

1. Freeze affected mutations. Keep the database, all ledger/audit/manual-work rows, current migration revision, notification receipts and backups. Stop the API if a controlled write freeze is necessary; its in-process maintenance stops with it.
2. Prefer a forward repair. A previously captured image is usable only if it is already compatible with the complete Phase 1–6 schema and immutable-history contracts. A pre-V2 image is **not** a safe general rollback writer once new records exist.
3. When that compatibility has been demonstrated, use the saved image override without rebuilding or downgrading the schema:

```bash
docker compose --env-file .env.production \
  -f docker-compose.prod.yml -f docker-compose.github.yml \
  -f "$backup_root/rollback-images.yml" \
  up -d --no-deps --no-build backend frontend
```

4. Repeat the SQL gate and authenticated financial/ownership checks before restoring writes. Preserve the public-registration security fix: never re-enable unauthenticated enrollment into an existing tenant in a rollback artifact.
5. Never run `alembic downgrade` to remove V2 history, delete new tables/columns, truncate ledger/audit data, restore an old dump over a database that accepted new writes, reset user balances, or recompute legacy rewards. Several V2 downgrades intentionally refuse destruction; later index-only downgrades retain their indexes/data.
6. For corruption, restore the backup into a **new isolated database**, retain the original for investigation, and reconcile/replay valid post-backup records with their original IDs, ownership, timestamps, idempotency/reversal references and manual-work corrections. Validate balances, relationships and export/import scope before a separately approved recovery cutover. A snapshot alone cannot preserve writes accepted after it was taken.

No production backup, restore rehearsal, pilot, provider delivery, image cutover or rollback command above was executed during Phase 7.
