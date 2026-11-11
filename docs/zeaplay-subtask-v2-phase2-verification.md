# ZeaPlay Subtask V2: Phase 2 implementation and production review

Reviewed 2 November 2026. Checkout: `F:\Projects\zeaplay-05\zea-play-08-05-26\zea-play`, including its existing dirty work. The Phase 0 report is a historical discovery baseline; this document records subsequent implementation and review. No deployment, installed database migration, production access, reward activation, or historical points recalculation was performed.

## Decision and readiness

The user confirmed: **all new subtasks require planned dates and use the managed workflow; historical rows remain legacy**. Workflow activation is independent of reward activation. New subtasks have `workflow_version=2`; historical rows retain `0`. A new row can therefore be managed while retaining `point_policy_version=legacy`. Only the existing tenant activation settings select a different reward marker, at creation time. Neither enrollment nor status changes retag old rewards.

The scoped PostgreSQL, API, frontend unit, build, and component browser checks pass. Production rollout remains conditional on reconciling the actual installed migration history and the existing baseline failures below. Component browser checks used intercepted local HTTP responses, not a live authenticated end-to-end deployment.

## Review checklist and repairs

| Check | Result and evidence |
| --- | --- |
| Planning policy boundary | New task creation, task PATCH additions, and template assignment require both planned dates. Legacy title/checklist edits need no plan. Enrollment is explicit; the editor no longer silently enrolls incomplete historical rows. `SubtaskCreate`, `subtasks.create/edit`, existing task routes, workflow/API tests. |
| Date and time validation | Pydantic validates supplied values and the service validates the merged record, so single-field HTTP updates cannot evade range checks. Errors include `Planned end precedes start`, `Actual end precedes start`, missing planned dates, missing confirmation, and explicit timezone requirements. HTML requirements, date minimums, and client checks improve the UI; server checks remain authoritative. |
| User-controlled actuals | Creation rejects non-null actuals. Changes require `confirm_actual_times=true`; no status action supplies actuals. Entered offsets are normalized to UTC. Luxon edits use the configured user timezone, reject nonexistent DST times, and require an offset for repeated times. Editing one boundary no longer truncates the untouched boundary's fractional seconds. |
| Status and resume | Server and database guards enforce the five states and transition map below. Pause/resume returns to In Progress. Completion requires a manually confirmed actual pair for managed rows. Historical completed rows without actuals remain readable and editable. |
| Permissions and tenancy | Existing task visibility/update checks are reused with a live actor. USER followers may read but cannot mutate child fields. Foreign tenants receive 404; unauthorized users receive 403. Ticket-linked task edit restrictions remain in force. Direct HTTP tests deny title, priority, Testing, and Complete writes from unauthorized actors. Parent approval is not changed by child completion. |
| Priority and points | Effective priority is derived from `priority_override ?? task.priority`; no inherited value is copied into storage. Parent priority changes immediately affect inherited reads. Existing scoring/badge calls still receive main-task priority. No new child-point formula or wallet posting was introduced. |
| Audits and atomicity | Every actual child field change gets a synchronous immutable event with actor, UTC timestamp, and changed old/new values. Field write and event share a savepoint and caller transaction. Injected audit failure rolls back the field write. No-op writes create no event or version increment. |
| Visible audit history | Existing GET task endpoint accepts an opt-in history query. The subtask section displays the latest 200 immutable events with old/new values, actor IDs, timestamps in the user's timezone, and refresh. It does not fabricate historical events. No Logs page or duplicate audit store was introduced. |
| Concurrency and repeated updates | Managed edits require an integer expected version; atomic compare-and-update allows one concurrent winner and returns 409 for stale writers. Unchanged nested PATCH requests now skip badge, cache, and webhook side effects. Subtask editor, task creation, and template assignment have synchronous in-flight guards. Browser double activation sent one mutation. This is not a claim of global idempotency for every existing task POST endpoint. |
| Existing data and relationships | Subtask IDs, parent assignment, original timestamps, comments, dependencies, attachments, and wallet values are preserved. Audited/managed children cannot disappear through bulk replacement or parent hard deletion. These attempts return 409. Removing a managed group member uses existing unassignment rather than destroying history. |
| Keyboard and mobile | Real component exercised at 390px and 1280px. Keyboard Enter opens native details; labeled inputs and native form submission remain available. Mobile and desktop checks found no horizontal overflow. Calendar controls use a dark color scheme in the new section. This is not a screen-reader/device certification. |
| Scope | Changes are confined to subtask-related models, migration, shared repositories/validation, backup compatibility, existing task routes/forms/detail section, tests, and this report/evidence. Unrelated dirty work was preserved. |

### Server transition contract

| Current state | Allowed next states / buttons |
| --- | --- |
| `TODO` | `IN_PROGRESS` / Start |
| `IN_PROGRESS` | `PAUSED`, `TESTING`, `COMPLETED` / Pause, Send to Testing, Complete |
| `PAUSED` | `IN_PROGRESS` / Resume |
| `TESTING` | `IN_PROGRESS`, `COMPLETED` / Return to In Progress, Complete |
| `COMPLETED` | `TODO` / Reopen |

There is no independently verified subtask actual-time override permission in the existing application. No arbitrary administrator bypass was invented. Main-task approval and rewards keep their existing semantics. Parent assignment is the canonical subtask assignment.

## API changes and compatibility

Existing routes are extended; application mounts also expose their `/api` aliases:

- `POST /tasks`: each supplied new child requires `title`, `planned_start_date`, and `planned_end_date`; existing parent relationship/assignment rules remain. New children start To Do with null actuals.
- `PATCH /tasks/{task_id}`: new child rows follow the same contract. Existing echoed checklist rows remain compatible when unchanged. Changed managed children require `expected_version`. Unknown existing child IDs are rejected; omitting an immutable child returns 409 instead of deleting it.
- `PATCH /tasks/{task_id}/subtasks/{subtask_id}`: supports title, planned dates, actual timestamps, nullable priority override, status or action or legacy completed flag (one selector per request), `confirm_actual_times`, explicit `manage`, and expected version. Omission preserves data; explicit null is validated rather than treated as omission.
- `POST /tasks/task-templates/{template_id}/assign`: planned dates are required when the template creates children. Blueprint-only template editing does not create subtasks and needs no dates. Template, assignee, and department membership checks remain tenant scoped.
- `GET /tasks/{task_id}?include_subtask_activity=true`: adds bounded `subtask_activity` from the existing immutable event repository after task-read authorization. Default reads do not perform the history query.

Legacy `id`, `title`, and `completed` remain in responses. New response fields include planning/actuals, `priority_override`, `effective_priority`, `point_policy_version`, `version`, `status`, and `managed`. Task responses have an additive `subtask_activity` list, empty unless requested. Historic missing values stay null. Mutations do not auto-fill actual timestamps or recalculate old rewards. Old clients can continue legacy checklist edits, but cannot create undated new subtasks or overwrite managed rows without a version.

Example nested edit:

```json
{
  "expected_version": 3,
  "actual_start_at": "2026-11-02T10:00:00+05:30",
  "actual_end_at": "2026-11-02T11:00:00+05:30",
  "confirm_actual_times": true
}
```

UTC values are `04:30Z` and `05:30Z`. A later action request is only `{"expected_version":4,"action":"COMPLETE"}`; it does not resend actuals.

## Phase 1 hardening and migration dependency

Apply the verified Phase 1 foundation `e5a7c9d1f3b5` before new revision **`f6b8d0e2a4c6`**, whose parent is that foundation. The original foundation revision and frozen v1 guards were preserved. The new revision adds only workflow columns/indexes and stronger guards; it performs no historical reward updates, default date backfills, or audit-event synthesis.

Repairs discovered during schema/restore review:

- New history could previously be disguised as mutable legacy rows. Guards now reject new-only fields on legacy audit/ledger records, while retaining exact legacy archive compatibility.
- Ownership checks now cover new ledger recipients even where the original ledger lacks a user FK, and nonlegacy-policy child ownership even without a fabricated audit event. Existing v1 tenant share-lock guards remain installed.
- PostgreSQL TRUNCATE protection complements UPDATE/DELETE immutability. Audited parents and referenced users cannot be hard-deleted or reassigned across tenants. Manual intervals remain immutable and separate from elapsed/activity time.
- Migration preflight checks timezone-aware timestamp types, RESTRICT references, unconditional database idempotency/reversal/request uniqueness, ownership, index definitions, compatible workflow defaults and status capacity. Unsafe drift fails closed; it is not silently repaired. SQLite FK behavior is checked with authoritative `PRAGMA foreign_key_list`.
- Added FK/ownership lookup indexes and managed-status lookup. No duplicate ledger, interval, or activity tables were created.
- Fresh logical restore now orders original ledger entries before reversals, handles reversal chains, and breaks the existing nullable user/avatar cycle before immutable task history is inserted. Impossible immutable dependency deferral fails closed. Original, Phase 1, and current exact subtask archive headers are accepted. Restore does not apply imported wallet balances or credentials.
- Phase 1 compatibility writer functions now delegate managed creation/schedule changes to the canonical service, preventing internal omission of planning or actual-time confirmation.

**Sanitized rehearsal:** a full ORM-derived pre-feature schema with 81 tables, four synthetic tenants, eight users, 1,500 tasks, 7,500 subtasks, 3,000 old events, 1,500 old ledger records, one reward, and one claim. Both revisions run twice. Fingerprints verify original columns, identifiers, times, wallet values, rewards, and claims remain identical. Historical created-at values remain unknown/null. This is realistic synthetic data, not a production dump or proof of the installed production schema.

PostgreSQL 15 rehearsal added 6,000 new events and 3,000 new ledger entries, ran ANALYZE, then real `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` without disabling sequential scans:

| Lookup | Chosen index | Sample execution ms |
| --- | --- | ---: |
| Actor ownership guard | `ix_audit_events_actor_v2` | 0.012 |
| Tenant/task chronology | `ix_audit_events_tenant_task_time` | 0.105 |
| Task event FK lookup | `ix_audit_events_task_ref` | 0.028 |
| Ledger replay | `uq_xp_ledger_tenant_idempotency` | 0.014 |
| Recipient ownership guard | `ix_xp_ledger_user_v2` | 0.011 |

These are disposable-fixture observations, not production latency guarantees. Other FK indexes are schema-checked; every possible application query was not benchmarked.

### Rollout and rollback

1. Inventory installed revisions/schema and take a verified database backup. Resolve the historical `tasks.tenant_id` index-migration mismatch from Phase 0 before choosing the installed upgrade path; do not stamp or run the full chain blindly.
2. Rehearse these additive revisions on a sanitized restoration of that installed schema. The model-derived rehearsal here does not replace this deployment gate.
3. Apply schema before deploying managed writers. PostgreSQL migration uses transactional DDL, a five-second lock timeout, and a 120-second statement timeout. Normal index creation can briefly block writers; failure rolls back and should be retried in a suitable window. This is not a guarantee of lock-free deployment at arbitrary table sizes.
4. Deploy compatible API and frontend together for the creation contract. Observe validation/conflict rates and tenant authorization. Do not activate a reward policy as an implicit part of deployment.
5. If application rollback is necessary, retain additive schema and all new history. Destructive downgrade deliberately refuses. Older binaries can read legacy rows, but managed writes may be rejected by guards; use a compatible writer, temporary read-only operation, or roll forward. Restoring an old snapshot over new events loses data and is not a safe rollback.

Logical backups intentionally exclude opaque audit payloads under the existing credential-safe allowlist. They preserve declared snapshots/relationships, but full opaque metadata fidelity requires a verified full database backup. Restore tests cover fresh destinations and reversal ordering; live multi-tenant production restore was not performed.

## Changed files

Paths below are relative to the checkout. Existing unrelated changes in these files were retained.

| Area | Files changed during this implementation/review |
| --- | --- |
| ORM and database guards | `backend/app/models.py`, `backend/app/tickets/models.py`, `backend/app/services/task_audit_schema.py` (new) |
| Migration | `backend/alembic/versions/f6b8d0e2a4c6_subtask_workflow.py` (new; foundation dependency retained) |
| Contracts and writes | `backend/app/schemas.py`, `backend/app/services/subtasks.py` (new), `backend/app/services/audit_logger.py`, `backend/app/routers/tasks.py` |
| Compatible backups | `backend/app/backups/registry.py`, `backend/app/backups/service.py` |
| Frontend | `frontend/types.ts`, `frontend/services/mockApi.ts`, `frontend/utils/subtaskWorkflow.ts` (new), `frontend/components/SubtaskEditor.tsx` (new), `frontend/components/CreateTaskModal.tsx`, `frontend/components/TaskDetailModal.tsx`, `frontend/components/TaskTemplateModal.tsx` |
| Tests | `backend/tests/test_subtask_workflow.py` (new), `backend/tests/test_subtask_schema_rehearsal.py` (new), `backend/tests/test_task_audit_foundation.py`, `backend/tests/test_backup_manager.py`, `frontend/test/subtask-workflow.test.ts` (new) |
| Documentation | This report and bounded verification artifacts in `docs/verification/zeaplay-subtask-v2-phase2/` |

## Executed validation and limits

All Python tests ran under local Python 3.14.3 from a credential-free disposable source copy with external sockets blocked, except the owned loopback PostgreSQL fixture. The application Docker runtime was not exercised. API fixtures execute real handlers/validation/authorization with synthetic authenticated identities; rewards, delivery, and cache integrations are mocked. They do not certify login, proxy, WebSocket delivery, or production wallet behavior. Source hashes match the verification copy.

| Check | Result |
| --- | --- |
| SQLite workflow, schema, foundation, migration, task regression, time-rule, backup suites | **PASS: 151**, zero failures, eight PostgreSQL-only cases skipped. |
| PostgreSQL 15 foundation/migration/workflow/schema suites | **PASS: 55**, zero failures/skips. Includes concurrent ledger idempotency, one-winner concurrent child edits, schema drift refusal, append-only protections, and model-derived migration rehearsal. |
| Frontend complete Node test suite | **PASS: 47**, including six new workflow/date/DST/contract tests. |
| Frontend production build | **PASS**, with existing bundle-size warnings. |
| Scoped Ruff | **PASS**, new services/migration/tests and touched backup registry/tests. This is not whole-repository lint certification. |
| Component browser automation | **PASS**, real editor with local intercepted API: status requests omit actuals; incomplete completion disabled; confirmation blocks submission; UTC conversion; untouched microseconds preserved; double activation yields one write; keyboard details; legacy undated edit; audit visible; 390px/1280px no overflow. Earlier component run also exercised successful completion and planned child addition. |
| Frontend TypeScript | **FAIL, existing debt:** 112 diagnostics versus 113 baseline. Normalized comparison finds no new diagnostics; missing `Role` import in the touched creation form was fixed. |
| Full backend suite | **NOT RERUN** as a production acceptance suite. Phase 0 baseline has four collection errors and 24 reduced-run setup errors from missing SQLite `to_tsvector` fixture support. Targeted fixtures provide the required test compatibility. |
| Installed Docker app, full authenticated browser flow, complete historical Alembic chain, production schema/data | **NOT RUN**. No deployment claim. |

Existing warnings include duplicate `Level.created_by` mapping, deprecated Pydantic config/UTC-naive legacy defaults, SQLite table-sort cycle, and existing browser `/index.css` 404/CDN Tailwind warning. The component runs had zero page JavaScript exceptions. These do not justify unrelated page rewrites in this scope.

### Repeat commands

Retained disposable root: `C:\Users\Lenovo\AppData\Local\Temp\zeaplay-phase2-review-236e6ff20631484b816ca44ce44bed25`. Its runner enforces test settings and socket isolation. Never point these fixtures at an installed/shared database. PostgreSQL requires a newly owned disposable PostgreSQL 15 database at the runner's explicitly permitted loopback port; the review container is removed after verification.

```powershell
$reviewRoot = 'C:\Users\Lenovo\AppData\Local\Temp\zeaplay-phase2-review-236e6ff20631484b816ca44ce44bed25'
Set-Location $reviewRoot
python -B review_pytest.py backend/tests/test_subtask_workflow.py backend/tests/test_subtask_schema_rehearsal.py backend/tests/test_task_audit_foundation.py backend/tests/test_task_audit_migration.py backend/tests/test_task_tabs_review.py backend/tests/test_time_bonus.py backend/tests/test_backup_manager.py --junitxml=repeat-sqlite.xml

# Only after creating an owned disposable PostgreSQL fixture; synthetic user/database:
$env:ZEA_TASK_AUDIT_TEST_URL = 'postgresql+psycopg://phase1@127.0.0.1:54316/zea_subtask_phase1'
python -B review_pytest.py backend/tests/test_task_audit_foundation.py backend/tests/test_task_audit_migration.py backend/tests/test_subtask_workflow.py backend/tests/test_subtask_schema_rehearsal.py --junitxml=repeat-postgres.xml
Remove-Item Env:ZEA_TASK_AUDIT_TEST_URL

Set-Location "$reviewRoot\frontend"
npm test
npm run build
npx --no-install tsc --noEmit
```

The temporary browser fixture renders the real editor with synthetic users/tasks and local intercepted responses. It is retained only in the disposable copy and is not a new shipped application. No dependency or lockfile changes were needed.
