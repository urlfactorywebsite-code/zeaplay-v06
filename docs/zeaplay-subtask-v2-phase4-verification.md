# Phase 4 — personal task activity, time and workload

Follow-up: the [Phase 4 audit and optimization](zeaplay-subtask-v2-phase4-audit.md) supersedes this report's locking, query, rendering and realtime-delivery details. The original execution results below remain historical evidence.

Implemented against this checkout on 2 November 2026 after reviewing the [Phase 0 discovery](zeaplay-subtask-v2-architecture.md), [Phase 2 verification](zeaplay-subtask-v2-phase2-verification.md), [Phase 3 implementation](zeaplay-subtask-v2-phase3-verification.md), and [reward audit](zeaplay-subtask-v2-phase3-audit.md).

**Source and disposable verification passes for Phase 4. This is not deployment certification.** No installed database, running application image, reward policy, wallet history, production configuration or unrelated page was migrated or redesigned. The existing dirty tree was preserved. Whole-application TypeScript and backend collection failures remain, as recorded below.

## Implemented behavior

The existing header has a compact activity control on desktop and mobile. It shows the user's active parent count out of five, parent/subtask names, personal work status, elapsed time, a workload warning and a quick Pause/Resume action. Its keyboard-accessible dialog shows five numbered slots, a separate paused list, task details links, priority, workflow status, manual actual timestamps, parent/selected-subtask elapsed and productive durations, and deadlines. Empty slots remain visible. Start can select a parent or a subtask; the detail link opens the existing task view.

Personal activity is separate from shared task/subtask workflow status. Each `(tenant, user, parent task)` has one current focus. Starting another subtask under the same parent switches that focus, retains the parent slot and accumulated parent elapsed, and attributes each elapsed segment to the subtask selected during that segment. Another user has independent slots. Existing globally `IN_PROGRESS` tasks do not fabricate personal activity or historical timer starts.

The header controls only the authenticated user's activity. Existing task/subtask workflow transitions into In Progress also pass through the personal Start gate within their transaction. A subtask Pause pauses the actor's matching personal focus. Authorized completion/deletion closes matching contexts, including other contributors' selected contexts. Completing the parent closes its running/paused contexts. Existing workflow authorization and reward reconciliation still apply. Header Start/Pause/Resume never writes shared workflow fields or manual actual timestamps.

Pause freezes elapsed and releases the slot; Resume requires a free slot. Stop also releases it. Switching within a running parent needs no additional slot. A sixth parent returns HTTP 409:

> You already have five active parent tasks. Pause one before starting or resuming another.

Users can release their own existing context after losing task access; this grants no task-field editing or other-user control. Starting/resuming requires current canonical task permission. The dialog also supports read-only workload inspection for same-tenant Owner/Admin and a Manager's direct reports (`users.manager_id`). Task details still require the viewer's existing task visibility: restricted running work occupies a redacted slot without exposing its task ID/name. No manager mutation endpoint was added.

## Reused infrastructure and storage

| Existing component | Phase 4 integration |
| --- | --- |
| `AuditEvent` version 2 and existing immutable guards | Append `work.started`, `work.paused`, `work.resumed`, `work.switched`, `work.stopped`, `work.completed`, and correction events. Server actor/tenant/time and old/new states are recorded here. No parallel event log. |
| `TaskWorkInterval` and `audit_logger.record_manual_work()` | Store confirmed productive intervals in the existing immutable entity. No replacement time-log table. |
| `subtask_rewards.lock_scope()` | Retain tenant/parent lock ordering before locking the working user's row. No reward formula, ledger component or balance recalculation change. |
| Task authorization and creator-based tenant ownership | Revalidate active identity, parent access and subtask relationship; request bodies cannot choose actor/tenant/recipient. |
| Existing `/ws/tasks`, Redis task-event channel/listener | Publish a minimal tenant-scoped invalidation after commit. Header owns the existing task socket; AllTasks consumes existing invalidation events without opening a second socket. |
| Header, auth, navigation policy, TanStack Query, Axios adapter, Luxon and existing actual-time helpers | Extend current components/providers and timezone/DST patterns. No new application or standalone production screen. |
| Backup manager | Add reviewed fields for the two new tables; preserve old work-interval archive fields. Restore cannot overwrite existing activity projections or immutable correction history. |

New tables:

* `task_activity_contexts`: ID, tenant, user, parent task, optional selected subtask, personal status, numbered slot, accumulated `elapsed_ms`, UTC `resumed_at`, version, last audit-event reference, UTC created/updated timestamps. This is an audited mutable projection; the events are immutable.
* `task_work_corrections`: immutable original/replacement interval references, tenant/user, audit reference, request ID and UTC timestamp. Originals remain permanently available; a superseded interval is excluded from productive totals. Correction chains are supported; branching, reused replacements and cycles are rejected.

Both tables use restrictive foreign keys and database ownership/relationship guards. Unique `(tenant,user,parent)` prevents duplicate focuses. Unique `(tenant,user,slot)` plus the running-slot constraint restricts running contexts to slots 1–5; non-running contexts must have null slot and resume anchor. Counters and versions are constrained. Context updates require a new matching immutable event, increasing version and nondecreasing elapsed. Deletion is blocked; PostgreSQL truncation is blocked. Correction updates/deletes are blocked.

## Time and workload contracts

Elapsed time is `persisted elapsed_ms + server_now - resumed_at` while running. Pause/Stop/Complete persist the completed segment and remove the anchor. A single frontend monotonic clock interpolates the server snapshot. Parent elapsed survives switches, reload and reconnect. Selected-child elapsed sums event segments using the **previous** selection, bounded by the captured context version so a concurrent pause/switch cannot count a segment twice. This is activity elapsed, not a productive-time claim.

Productive work requires explicit confirmation and timezone-aware start/end with `end > start`. The form displays/edits in the user's configured zone; ambiguous DST times require an offset choice, and changing either time/offset clears confirmation. Intervals normalize to UTC. The existing subtask actual start/end remain editable through the existing subtask editor and are never populated by activity or work-log actions.

New overlapping intervals for one user, across all parent/subtask scopes, return 409 with the actor's conflicting interval IDs/times and correction instructions. Corrections create a replacement and a supersession link atomically; no original is edited. Existing historical overlaps remain readable. A sweep-line union counts shared minutes once, assigning overlapping minutes to the earliest confirmed `(created_at,id)` interval, consistently across daily and per-task/subtask totals. For example, historical 09:00–10:00 and 09:30–10:30 intervals contribute **90 productive minutes**, not 120. New API submissions of that overlap are rejected until corrected.

Workload uses visible incomplete assigned tasks **plus the subject's running/paused personal parents**, including work whose assignment belongs to another person. Assignment is never rewritten. Estimates are existing `estimated_hours` less that user's allocated lifetime productive time for the parent, floored at zero; missing/invalid estimates are counted separately. Elapsed timers do not reduce estimates. The query loads the subject's related parents rather than all tasks visible to an Owner.

Manual work today is the interval union clipped to consecutive local midnights. Near deadline means the next **24 hours**, explicitly returned by the API; overdue parent/subtask lists are separate. Subtasks use their planned end date and captured reward timezone where available, otherwise the viewed user's zone; legacy parent timestamps are interpreted as UTC. Configured shift/break fields determine capacity, including overnight shifts and DST. Overlapping breaks are deducted once. Missing/invalid/ambiguous configuration yields unknown capacity/overtime. Overtime is `max(0, manual_today - configured_capacity)`. No new daily-hours default or productive-time cap was introduced.

Realtime messages contain only `{ "type": "work.changed", "tenant_id": "..." }`. Clients refetch through authorization instead of receiving other users' names, intervals or counts. Reconnect, focus, online events, task invalidations and one 30-second aggregate fallback recover missed updates. There are no per-task polling loops or new timer workers. Delivery is best effort after commit; a Redis outage does not roll back an acknowledged activity operation.

## API contracts

Routes extend the existing task router and retain the application's `/api` aliases. Existing task/subtask response schemas remain compatible.

| Method and route | Contract |
| --- | --- |
| `GET /tasks/activity?user_id=<optional>` | Own snapshot by default; authorized report otherwise. Returns subject identity, read-only flag, UTC server anchor, timezone, active count/limit, contexts and workload. |
| `POST /tasks/{task_id}/activity` | `{action: START\|PAUSE\|RESUME\|STOP, subtask_id?: string\|null, expected_version: integer >= 0, request_id: UUID}`. Returns current own aggregate snapshot. Extra properties forbidden. |
| `GET /tasks/{task_id}/work-intervals?limit=50` | Own recent intervals for a readable task, including `superseded`; maximum requested limit 200. Does not expose another user's notes. |
| `POST /tasks/{task_id}/work-intervals` | `{started_at, ended_at, confirmed: true, request_id, subtask_id?, note?, supersedes_id?}`. Explicit offset timestamps required; request key nonblank and at most 128 characters. Returns 201 with interval ID, normalized times and optional superseded ID. |

Missing fields/bad types/timezones/ranges produce 422. Tenant/relationship failures and permission errors use existing 404/403 behavior. Stale versions, conflicting request-key reuse, invalid activity states, capacity exhaustion and overlaps return useful 409 errors. Confirmation must be literal boolean `true`.

Expected version is zero for a new context and the last snapshot version thereafter. Browser mutations have a synchronous pending guard. Backend request keys are enforced by a partial unique audit index over `(tenant,actor,correlation_id)` for work activity events; work intervals reuse their existing unique tenant/request constraint. Replaying identical Start after a subsequent Pause returns current state without restarting it. Reusing a key for different arguments returns 409. Mutations, projection changes and their immutable events share a transaction.

## Migration and rollout

Dependency: **`h8d0f2a4c6e8` → `i9e1a3c5d7f9`** (`backend/alembic/versions/i9e1a3c5d7f9_task_activity.py`). Apply prior Phase 1–3 revisions first. The new revision adds the two tables, lookup indexes, request uniqueness and frozen v5 guards. Existing/adopted tables/indexes are verified rather than silently accepted. It does not backfill contexts/events, update subtasks, rewrite rewards or recalculate balances.

The migration is online and transactional on PostgreSQL and SQLite. PostgreSQL uses 5-second lock and 120-second statement timeouts; audit-index construction serializes audit writers. **It is additive, but not lock-free**; large audit tables need a measured deployment window. Frozen DDL and guard definitions keep later ORM changes from changing this revision's contract. A malformed adopted index/schema causes refusal and rollback.

Deployment sequence (not executed here): verify a restorable backup and the actual deployed revision, apply the database revision, roll out the new backend across all mutation workers, then enable the new frontend. Do not send Phase 4 mutations to old workers during a mixed-version rollout. Older workers cannot maintain personal activity on workflow changes. New nullable/isolated infrastructure leaves legacy task reads and reward history intact.

For an already verified `h8d0f2a4c6e8` deployment, from `backend`, the migration command is `alembic upgrade i9e1a3c5d7f9`; inspect `alembic current` and `alembic heads` first. These are handoff commands, not claims that the installed database was migrated.

Downgrade intentionally refuses data deletion. Retain new tables/events and roll forward. An application rollback must coordinate/pause personal activity and mutation traffic so old workers do not leave stale projections; do not drop history to make an old image start. Unchanged backups can replay history; restoring a stale projection over a newer one is refused. No blanket stamp, unguarded bootstrap or automatic deployment was performed.

## Changed files in this phase

| Files | Purpose |
| --- | --- |
| `backend/app/models.py`; `backend/alembic/versions/i9e1a3c5d7f9_task_activity.py`; `backend/app/services/task_activity_schema.py` | Context/correction models, frozen migration and storage guards. |
| `backend/app/services/task_activity.py` | Atomic commands, audit projection, work intervals/corrections, union time, workload and scoped reporting. |
| `backend/app/schemas.py`; `backend/app/routers/tasks.py`; `backend/app/services/subtasks.py` | Strict API inputs, canonical task endpoints and existing workflow hooks. |
| `backend/app/backups/registry.py`; `backend/app/backups/service.py` | Export fields and immutable restore compatibility. |
| `frontend/components/Header.tsx`; `frontend/components/TaskActivityControl.tsx` | Existing header control and dialog. |
| `frontend/hooks/useTaskActivity.ts`; `frontend/hooks/useTaskWebSocket.ts`; `frontend/pages/AllTasks.tsx` | Shared aggregate state, reconnect recovery and one layout-owned socket. |
| `frontend/services/mockApi.ts`; `frontend/types/taskActivity.ts`; `frontend/utils/taskActivity.ts` | Existing HTTP adapter, contracts and monotonic elapsed helpers. |
| `backend/tests/test_task_activity.py`; `backend/tests/test_task_tabs_review.py`; `frontend/test/task-activity.test.ts` | New coverage; distinguish legacy audit assertions from newly expected work events. |
| This report; `docs/verification/zeaplay-subtask-v2-phase4/` | Results, source hashes and synthetic UI evidence. |

## Executed validation

Tests ran in a sanitized disposable source copy. Real concurrency used an owned PostgreSQL 15 container with temporary per-test schemas; no installed database was used. API and backup fixtures use disposable SQLite, even in PostgreSQL-enabled runs. No production credentials/configuration were copied. Browser checks mounted the actual Header/providers/components with synthetic API/WebSocket fixtures; separate ASGI tests exercise real task routes and signed WebSocket authentication.

| Check | Actual result |
| --- | --- |
| Final Phase 4 suite, PostgreSQL fixture enabled | **PASS — 26 passed**, including real simultaneous starts/resumes/overlapping submissions and a signed native WebSocket test. |
| Final Phase 4 suite, SQLite | **PASS — 22 passed, 4 skipped**; skipped tests explicitly require PostgreSQL concurrency. |
| Wider task/subtask/reward/backup regression run | **PASS — 156 passed**. Includes an earlier 24-case Phase 4 suite, so counts overlap; API/backup fixtures remain SQLite. |
| Reward audit, audit foundation and migration regressions | **PASS — 52 passed** with PostgreSQL fixture enabled. |
| Frontend unit tests | **PASS — 54 passed**; initial baseline was 49, with five new timer/slot/warning tests. |
| Frontend Vite build | **PASS**. Existing Lottie eval and bundle-size warnings remain. |
| Whole frontend TypeScript | **FAIL — 112 existing diagnostics**, versus 112 in a reconstructed pre-change baseline; no new normalized diagnostics. Original touched frontend files were hash-verified against the prior source copy; unchanged tracked JSX files were included. |
| Whole backend collection | **FAIL — 4 existing SQLite `to_tsvector` collection errors**, 447 tests discovered before interruption. Same affected modules were recorded by Phase 0/3. Whole backend execution therefore **NOT RUN**. |
| Scoped Ruff / syntax / whitespace | **PASS** for new Python files, affected source syntax and scoped diff checks. |
| Browser interaction checks | **PASS** at 1280×900 and 390×844: five slots, sixth disabled, double-click guard, pause freeze/free slot, resume capacity, parent/child names, manual confirmation/UTC/overlap/correction, read-only report, keyboard Enter/Escape, reload/reconnect refetch, one task socket, no horizontal overflow and existing mobile menu. |
| Installed Docker/production migration, real Redis transport and full real-login UI E2E | **NOT RUN**. Native signed ASGI WebSockets and tenant delivery were tested with an in-process publisher bridge; this is not a Redis deployment claim. |

PostgreSQL races produced five successes/one 409 for six distinct simultaneous starts; two same-key starts produced one context/event; two resumes competing for the last slot produced one success/one 409; simultaneous overlapping work intervals produced one success/one 409. Raw storage cannot allocate slot six. Interruption after event creation rolled back both event and context. Migration rehearsal repeated the revision over synthetic legacy data, paid reward ledger/wallet state and confirmed work, preserving every captured row. Backup replay preserved paused context and original/replacement interval history; raw correction deletion and unaudited projection mutation were rejected.

During validation, fixture problems were corrected without speculative application changes: omitted static/JSX assets in sanitized copies, a future synthetic reward activation rejected by existing guards, and creation-time ties requiring ID-based ordinal selection. An old test assumed all task audit rows were legacy; it now asserts the preserved legacy history and the new work event separately. Review also fixed an elapsed-snapshot race, strict SQLite UUID adoption, confirmation reset on offset changes, and workloads omitting personal work assigned elsewhere.

Reproduction in a sanitized copy (not an installed application):

```powershell
# PostgreSQL URL must point to an owned disposable database; test fixture rejects
# targets other than its named loopback phase1 database.
$env:ZEA_TASK_AUDIT_TEST_URL = 'postgresql+psycopg://phase1@127.0.0.1:54317/zea_subtask_phase1'
python -B review_pytest.py backend/tests/test_task_activity.py
python -B review_pytest.py backend/tests/test_subtask_rewards.py backend/tests/test_subtask_workflow.py backend/tests/test_backup_manager.py backend/tests/test_task_tabs_review.py
python -B review_pytest.py backend/tests/test_subtask_reward_audit.py backend/tests/test_task_audit_foundation.py backend/tests/test_task_audit_migration.py
$env:ZEA_TASK_AUDIT_TEST_URL = $null
python -B review_pytest.py backend/tests/test_task_activity.py
python -B review_pytest.py --collect-only backend/tests
# From the sanitized frontend directory:
npm test
npm run build
npx tsc --noEmit --pretty false
```

The retained runner blocks outbound connections except the owned PostgreSQL port, uses an in-memory default database, disables external forwarding/Redis and supplies synthetic signing keys. [Evidence](verification/zeaplay-subtask-v2-phase4/) includes its copy, XML results, baseline/current typecheck logs, screenshots, browser assertions and tested source hashes. Browser external branding/media were replaced or blocked in the fixture; those blocked-resource console entries are not production behavior evidence. Large production-scale performance, installed authentication/proxy/realtime delivery and operational rollback still require the deployment validation phase.

Cleanup completed: the owned, labeled PostgreSQL container was removed and the owned Vite fixture process stopped. Existing ZeaPlay and Paradise containers were left running. Report subject lookups are tenant-scoped before loading a user; missing and foreign subjects both return 404.
