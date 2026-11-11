# Phase 5 — Task Information modal

Follow-up: [Task Information audit and refinement](zeaplay-subtask-v2-phase5-audit.md) corrects workflow chronology, linked ledger actors, refresh/cache behavior and accessibility details, and records the latest verification. The original results below describe the initial implementation.

Implemented on 2 November 2026 in the existing React/Vite + FastAPI/SQLAlchemy checkout, using the [Phase 0 discovery](zeaplay-subtask-v2-architecture.md), [Phase 2 review](zeaplay-subtask-v2-phase2-verification.md), [Phase 3 accounting audit](zeaplay-subtask-v2-phase3-audit.md), and [Phase 4 activity audit](zeaplay-subtask-v2-phase4-audit.md).

This is source and disposable-fixture verification. No installed database, production configuration, running application container, reward activation, or deployment was changed. Existing unrelated dirty work was retained.

## Delivered behavior

Both the compact information icon beside the task title and **View information** in the existing Task Details control panel open the same `TaskInformationModal`. The existing shared-assignment log keeps its separate behavior. Task Details remains mounted, including unfinished title edits and unsent comments. Closing information restores focus to its trigger. Closing/changing the parent task resets the information dialog.

The modal uses the existing Headless UI dialog/tabs, TanStack Query, API client, theme tokens, and task-stream invalidation events. No additional WebSocket, activity writer, reward engine, audit store, or standalone application was introduced.

| Tab | Source and behavior |
| --- | --- |
| Overview | Actual `Task` columns, same-tenant creator/assignee names, approval/completion data, configured estimate, confirmed productive work, and persisted personal activity. Parent tasks have **no relational project, planned-date, or manual actual-time columns**; those fields are explicitly unavailable instead of inferred from team, creation time, or children. |
| Status timeline | Ascending recorded transitions from structured `AuditLog` and `AuditEvent` snapshots. Shows previous/new status, actor, user-local time, full UTC timestamp, workflow versus personal-activity stream, and duration only between consecutive matching transitions. Creation time is displayed from the actual record; no synthetic historical event is inserted. |
| Subtasks | Paginated, literal case-insensitive name search; inherited parent assignee; live effective display priority; planned dates; manually recorded actual times; workflow/completion/deletion state; elapsed and productive durations; policy marker; additional base capacity, incomplete available base, verified earned points, and posted bonus/penalty/reversal indicators. Soft-deleted rows retain their visible history and have zero new available reward. Each row expands an independently paginated status timeline, including personal handoffs away from that child. |
| Points | Server-resolved current main-task base configuration, additional base capacity/availability, signed task-linked ledger aggregates, separate posted base/bonus/penalty/adjustment/reversal values, verified net, and recipient distribution. No reward total is calculated in the frontend. |
| Activity | Newest-first authorized immutable audit events, structured legacy task logs, legacy task observations, permitted current comments, and individual ledger postings/reversals. Source provenance is visible. Before/after task fields remain separate from safe event details. |

All large lists return at most 100 rows per request (25 by default). Search resets its page after a 250ms debounce; tab pages and search remain in the open modal's state. A shrinking result set corrects an out-of-range page. Tables scroll inside the modal on narrow screens. Histories scroll vertically without moving the dialog header or tab list.

## Accounting and historical coverage

The existing main-task completion service (`services/gamification.py`) calculates configured components and adjusts the wallet; it does not persist a complete task-attributed payout ledger. Current priority/status/due dates and a wallet balance cannot prove an old task's actual award. Therefore:

* `main_base_value` is the existing resolver's **current configured base**, clearly labelled as such.
* `main_earned` and `total_net_earned` are **null / unknown**. The UI explains incomplete history rather than equating unknown with zero or recomputing an old payout.
* `verified_net_earned` is the signed SQL sum of existing task-linked version-2 ledger entries. `subtask_earned` is its child-linked subset.
* Posted components retain their original amounts. `REVERSAL` is a separate signed adjustment; components plus reversals reconcile to the verified net. A positive reversal of a penalty remains positive.
* Potential **base** capacity and incomplete available base exclude contingent bonus/penalty amounts. Eligibility/order still excludes legacy/deleted rows and uses the immutable new-policy creation order. The existing reward snapshot/resolver supplies values; display-priority overrides never supply reward values.
* Legacy children without attributed ledger records have unknown historical earned values. Their additional new-policy base capacity is zero. No historical rewards or markers are changed.

Verified synthetic example with an existing General/HIGH base of 30:

| State | Main base configuration | Posted subtask base | Posted bonus | Posted penalty | Reversals | Verified net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Three eligible children; second on time, third late, both completed | 30 | 60 | 15 | -15 | 0 | 60 |
| Delete the original first child; the former second becomes zero-base first | 30 | 60 | 15 | -15 | -45 | 15 |

Main earned remains unknown in both states and is never added to these verified ledger totals. Reassigning the remaining credit preserves net 15 while compensating the former recipient to zero and crediting the new recipient 15. The tests compare sums with the existing reward engine and persisted ledger, rather than a frontend formula.

Legacy `AuditLog` is still an asynchronous, retention-managed source. Missing or purged transitions cannot be recovered. Some old `AuditEvent` records contain only changed field names; those observations remain visible in Activity without invented before/after values. Current comments are identified as comment records, not an invented immutable edit history. Browser-local notes/transfer metadata are not promoted into authoritative server audit events. Personal running/paused activity is explicitly distinct from shared task/subtask workflow status.

## API contract

New read-only aggregation route on the existing task router:

```http
GET /tasks/{task_id}/information
    ?section=overview|timeline|subtasks|points|activity
    &page=1
    &page_size=25
    &search=<literal subtask name substring>
    &subtask_id=<optional child ID for timeline/activity>
Cache-Control: private, no-store
```

`section` defaults to `overview`. Page must be 1–1,000,000; page size 1–100; search at most 200 characters; optional child ID at most 36 characters. A child must belong to the authorized parent even when other query options would not use it. Invalid arguments return 422; missing/foreign parents or mismatched children return 404; same-tenant task permission failure or inactive identity returns 403.

Top-level response, defined in `backend/app/schemas_task_information.py` and mirrored in `frontend/types/taskInformation.ts`:

```typescript
{
  task_id: string;
  section: 'overview' | 'timeline' | 'subtasks' | 'points' | 'activity';
  as_of: string;                // UTC snapshot timestamp
  created_at: string | null;    // actual parent creation timestamp
  overview: InformationOverview | null;
  points: InformationPoints | null;
  items: (InformationEvent | InformationSubtask)[];
  total: number; page: number; page_size: number;
  coverage: string;
}
```

* `InformationOverview`: task identity/title/description/team, nullable unsupported project/planning/actual values, creator/assignees, priority/status, creation/update/assignment/completion/deadline timestamps, estimate, productive/elapsed seconds, approval state and coverage limitations.
* `InformationSubtask`: `kind="subtask"`, ID/name/assignee, effective priority/inheritance flag, planned/actual timestamps, status/completion/deletion/creation, policy version, additional base/available/nullable earned values, signed component map, productive/elapsed seconds.
* `InformationEvent`: `kind="event"`, source-prefixed unique ID, source/type/timestamp/actor/child, workflow/personal/note/points channel, previous/new status, nullable derivable duration, allowlisted before/after/details.
* `InformationPoints`: current main base and nullable historical main/full earned, subtask capacity/availability/verified earned, posted signed components, verified net, recipients with signed component distributions, and coverage explanation.

Existing details, mutation, activity, work-log and group endpoints/response schemas are unchanged. The API client passes an AbortSignal and rejects a response if the signed-in token changed during the read. Query keys include account, task, section, page, search and child. Errors hide cached details; retry refetches through authorization.

## Authorization, queries, and time

The service refreshes the active actor and uses canonical `_ensure_task_access` against creator-derived tenancy. It loads creator/assignee/followers in batches, without loading all children for authorization. Version-2 events and ledger rows require tenant plus parent ownership; optional child references are constrained to that parent. Legacy task sources are anchored to the authorized task and same-tenant/null actor; foreign actor identities/content are excluded. Historical foreign person references in otherwise authorized diffs are explicitly redacted.

Record permissions are applied **before counts and pagination**:

* Legacy `AuditLog` rows reuse `routers/logs.py::_apply_scope_filters`, retaining existing actor/target and manager-department visibility.
* Comments reuse `routers/comments.py::_ensure_comment_access`. A task follower does not gain comment access just by opening this modal.
* Another person's private confirmed-work note is omitted; its already shared audit event/times remain visible. Raw work logs keep their existing own-user API.
* Only task-field snapshots and constructed ledger details are returned. Arbitrary metadata, network/request headers, IPs, user agents, configuration and credentials are not serialized.

Audit source indexes are unioned and paginated in SQL; only the selected records and actor/reference names are then fetched in bounded source batches. Recipient/component totals and eligibility counts share one SQL statement snapshot. Child ordinal calculation occurs before search/pagination so page/search cannot change reward eligibility. There is no query per child or event. Tests bound the complete synthetic handler read to at most 16 statements for 100 rows in a 1,000-child hierarchy, and at most 12 statements for 100 rows in a 500-event history.

UTC is preserved internally; legacy naive parent times are interpreted according to the existing UTC storage convention. User-local display uses Luxon and the configured IANA timezone. Planned dates remain date-only strings. No timer/status/edit automatically writes actual timestamps.

Productive durations reuse Phase 4's confirmed-interval union/allocation **across all tasks for each contributing user**, excluding corrected originals. Only this parent's resulting durations are returned; other-task titles/notes are never loaded or disclosed. Contributor time can sum across people and is labelled accordingly. Elapsed totals reuse persisted contexts and version-bounded work-event segments, including switches; they are not productive hours or task wall age.

## Refresh and compatibility

The modal listens to the existing task/activity/app-refresh events plus online/focus recovery, coalescing bursts in 250ms windows. It creates no socket. The active section has one 30-second foreground recovery read; expanded histories refresh with query invalidation. The existing header remains the owner of `/ws/tasks`. Changes from another contributor outside the existing personal-work subscription recover through the aggregate fallback/focus read. No per-second HTTP/SQL/event writes are added.

Cancelled older tab reads cannot overwrite the selected section. Closing removes listeners, timers and query observers; query data is not retained after its last observer. This is a read projection, not a new transactionally complete historical event source or a promise that all tabs come from one database-wide snapshot.

No schema migration or backfill is introduced. Existing Phase 1–4 schema through **`i9e1a3c5d7f9`** is required. Rollback consists of removing this additive route/client/modal integration; no stored information needs rollback. Deploy the backend endpoint before or with the frontend; an older backend produces the modal's error state. Installed migration/deployment was not performed.

## Changed files

| File | Phase 5 change |
| --- | --- |
| `backend/app/routers/tasks.py` | Add the scoped read-only `/information` route and response contract imports. |
| `backend/app/schemas_task_information.py` | New overview/points/event/subtask/page response models. |
| `backend/app/services/task_information.py` | Authorized, paginated aggregation using existing audit, ledger, reward, and time repositories/helpers. |
| `backend/tests/test_task_information.py` | Disposable real-handler and service tests. |
| `frontend/services/mockApi.ts` | Add the existing client's `getTaskInformation` method. |
| `frontend/types/taskInformation.ts` | Typed API contracts. |
| `frontend/components/TaskInformationModal.tsx` | Five-tab accessible modal, queries, pagination/search and refresh cleanup. |
| `frontend/components/TaskDetailModal.tsx` | Both triggers and sibling modal integration; existing editor retained. |
| This report and `docs/verification/zeaplay-subtask-v2-phase5/` | Results, source hashes, browser scripts/fixture and evidence. |

These are Phase 5 contributions within an already dirty working tree; the complete Git diff also contains earlier work and is not this phase's change list.

## Validation

The runner and sanitized fixture procedure follow prior phases: explicit tracked/untracked source copy, no `.env`, runtime media or persisted databases, synthetic identities, outbound connections blocked except the owned PostgreSQL fixture. The database uses fresh disposable namespaces. Browser checks render the actual Task Details and information components with existing providers, a synthetic API and existing theme assets; they do not claim authenticated production browser coverage.

| Check | Result |
| --- | --- |
| Phase 5 focused suite, PostgreSQL fixture enabled | **PASS: 27/27**. Real HTTP fixtures use disposable SQLite; service/reward tests use PostgreSQL. |
| Same Phase 5 suite, disposable SQLite | **PASS: 27/27**. |
| Existing task/workflow/reward/activity regression | **PASS: 106 existing tests** in the broader run. One new fixture initially assumed UUID order proved causality at identical timestamps; it was corrected to use distinct server instants and passed subsequent focused runs. The separate 500-event test checks deterministic equal-time ordering. |
| Existing isolated reward calculator/accounting audit | **PASS: 35 tests**, including transactional/concurrency cases, in the 59-test run with the then-current 24 Phase 5 tests. |
| Existing frontend unit tests | **PASS: 60/60**. |
| Production frontend build | **PASS**. Existing large-chunk/Lottie warnings remain. |
| Real component browser automation | **PASS: 49 assertions** at 1280×900 and 390×844; includes 20 successive focus-trap checks. Both triggers, tabs/arrows/Home/End, exact UTC/local times, search/pagination/expansion, signed totals/unknown history, error/retry/empty/loading states, stale-read cancellation, draft preservation, Escape/focus return, reconnect, burst coalescing and unsubscribe cleanup. |
| Whole frontend TypeScript | **FAIL: 112 pre-existing diagnostics**, 112 before/after; zero added/removed after normalizing line/column locations and nondeterministic union-member order. No diagnostics in the new modal/contracts. |
| Scoped Python syntax/Ruff and changed-line whitespace | **PASS**. |
| Whole backend suite | **NOT RUN**. The prior report records four unrelated SQLite `to_tsvector` collection failures; this phase does not claim those were fixed. |
| Installed migration, deployed Redis/proxy/authenticated multi-device browser, production-scale query plans/load | **NOT RUN**. Source/disposable results are not deployment certification. Counts/window queries still process eligible histories; production-size legacy audit indexing/load must be measured in the target environment. |

Representative commands, run from the **sanitized scratch copy**, never an installed application directory:

```powershell
$env:ZEA_TASK_AUDIT_TEST_URL='postgresql+psycopg://phase1@127.0.0.1:54317/zea_subtask_phase1'
python -B review_pytest.py backend/tests/test_task_information.py
# Unset that fixture URL to exercise disposable SQLite instead.
Remove-Item Env:ZEA_TASK_AUDIT_TEST_URL
python -B review_pytest.py backend/tests/test_task_information.py
# From scratch/frontend:
npm test
npm run build
npx tsc --noEmit --pretty false
```

`review_pytest.py` is retained with evidence and refuses application outbound sockets. PostgreSQL setup uses only a separately owned, synthetic, tmpfs-backed container on the disposable test port. Browser fixture/scripts and machine-readable results are in [the evidence directory](verification/zeaplay-subtask-v2-phase5/). No production credentials or private configuration are included.
