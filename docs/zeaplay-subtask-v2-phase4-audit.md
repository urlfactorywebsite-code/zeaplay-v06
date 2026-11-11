# Phase 4 activity audit and optimization

Audited on 2 November 2026 against the existing [Phase 4 implementation](zeaplay-subtask-v2-phase4-verification.md) and its Phase 0–3 dependencies. Scope: personal activity, elapsed/productive time, capacity, task-stream delivery and the existing header activity control. No unrelated header design, reward formula, actual-time field, model or migration was changed.

**Result: affected source/disposable checks pass.** There were already **no per-second database writes**. This audit preserves that property and reduces reads, subscription fanout, rendering and unnecessary lock contention. Installed database migration, deployment and production capacity certification were not performed.

## Findings and repairs

| Finding verified in source/tests | Change |
| --- | --- |
| Personal activity took the same exclusive tenant-wide advisory lock as financial mutations, serializing otherwise independent users. | Pure activity/manual-work writers share that existing barrier and lock the actor plus creator in deterministic ID order. The actor uses PostgreSQL `FOR NO KEY UPDATE`; the creator uses `FOR SHARE`. Five-slot allocation still serializes by actor. Financial/workflow writers retain the original exclusive barrier and original default behavior. Crossed actor/creator races and exclusive reward exclusion were tested. |
| Snapshot task loading included unused creator/assignee/follower/dependency relationships and full task columns. Productive-time reads loaded interval notes. | Narrow task/subtask projections and interval fields preserve the response contract without loading those unused relationships or private notes. Existing tenant/task visibility checks remain. No new or duplicate index was introduced. |
| One OR predicate grew with every historical context. | Reproduced SQLite `Expression tree is too large (maximum depth 1000)` with 1,100 child contexts. Selected-child event aggregation now uses batches of at most 100 contexts and the relevant previous selection. Parent-only contexts require no event scan. Context-version bounds still prevent counting a concurrent segment twice. |
| Every tenant member received every personal-work invalidation, including users not viewing that person's workload. | Work invalidations include the subject's user ID and go only to that user and authorized sockets explicitly watching the subject. Manager/Owner report authorization is checked again on delivery; removing a reporting relationship closes the subscribed socket. Missing tenant scope is dropped rather than broadcast globally. |
| Broadcast authorization ran synchronous database work on the event loop and repeated it for every tab. Sequential slow sends could block other users. | Authentication and authorization run in worker threads. Permission checks are grouped by identity per event, without a cross-event permission cache. Fanout permits at most 16 identity groups per broadcast, with five-second transport timeouts and failed-socket cleanup. |
| Reconnect timers had no jitter; sockets/listeners and heartbeat cancellation needed stronger cleanup. | Added jittered bounded backoff, offline suspension/online recovery, stale-connection recovery, explicit listener removal and reconnect/watchdog cancellation. Closed sockets cannot resurrect a stream. Server heartbeat tasks are cancelled **and awaited**. |
| Mutations installed their server snapshot, then immediately invalidated it again. Event bursts could repeatedly restart aggregate reads. | Accept the committed response, cancel stale in-flight GETs and queued invalidations, and coalesce subsequent refresh requests in fixed 250ms windows. GETs receive an AbortSignal. Recovery polls are staggered at 30–35 seconds, with one aggregate query per enabled subject. Background recovery bypasses the global progress indicator. |
| A response for a different account could be shown under a stale tab's UI identity after shared token storage changed. | Validate the response subject against the query/mutation subject. Error states hide cached activity/report data. The existing authentication system remains responsible for signing in/out. |
| A one-second state update rerendered the whole activity dialog, including forms and timezone calculations. | Move ticking text into memoized `ActivityElapsed` components using one shared render clock. Paused contexts subscribe to no clock; hidden documents stop the clock; the last unsubscribe removes the interval and visibility listener. The control is memoized against the existing header's own clock renders. |
| A backwards server clock reached the database's chronology guard as an internal failure. | Return a useful 409 before writing if server time is behind the context's last event. No false elapsed time or fabricated timestamp is recorded; a retry succeeds once server time recovers. |

The shared lock is specifically for state that **does not affect the agreed reward calculation**. Manual work intervals are not a Phase 3 reward input. Future financial-input writers must retain the exclusive reward scope. SQLite retains its existing single-writer path. No reward recalculation, history rewrite, historical context creation or schema backfill was added.

## Preserved invariants and timing semantics

* A user can run at most five distinct parent contexts. Numbered-slot checks and unique tenant/user/slot and tenant/user/parent constraints remain unchanged. Multiple subtasks switch the same parent focus. Paused and stopped contexts release their slot; Resume requires one.
* Concurrent commands from different tabs/devices use optimistic context versions and the same backend lock scope. Stale requests conflict; identical request IDs replay without adding another audit event or credit. Distinct explicit commands remain auditable; there is no periodic event-writing job.
* Start/Pause/Resume do not set `actual_start_at` or `actual_end_at`, change assignment, or equate elapsed time to productive time. Existing manual confirmation, UTC conversion, overlap union/correction history and work permissions remain.
* Elapsed displays use server snapshots plus `performance.now()`, rather than browser wall time. Refresh/reconnect loads persisted state; neither a backend process's memory nor Redis is the timer authority. Pauses do not accumulate time. Selected-child segments still belong to their prior selection on switches.
* Configured shift/break capacity and local-day productive unions remain separate from elapsed timers. DST boundary tests, overnight capacity, overlap deduplication and unknown-capacity behavior pass. No daily-hours policy or arbitrary productive-time cap was introduced.
* Capacity warnings use the server's personal active count, including `>= limit` defensively. Global task statuses and the number of child rows do not define that count. Read failures show unavailable data instead of presenting cached report data as current.

## Realtime contract and compatibility

Existing `/ws/tasks` and its Redis listener/publisher are reused. HTTP activity/work-log routes and response fields are unchanged.

```json
{"type":"work.changed","tenant_id":"<tenant>","user_id":"<subject>"}
```

The header sends the following only while selecting a workload report, and resets to its own subject when the dialog closes:

```json
{"type":"activity.watch","user_id":"<subject-or-null-for-self>"}
```

The server replies with `activity.watching` or `activity.watch_denied`; these messages contain no task names, intervals or counts. Report subscription authorization uses the same live subject/tenant/manager rules as the HTTP report. Ordinary task invalidations retain their existing tenant behavior because parent changes can affect multiple users. Personal-work messages no longer invalidate AllTasks.

Old tenant-wide work messages without a subject still trigger a coalesced refresh. An older client connected to the new server receives its own activity immediately and uses its existing aggregate fallback for reports until upgraded. An older server ignores the new watch message and retains its prior delivery behavior. Deploy backend and frontend together for the optimized subscription behavior. Dropping a message with no tenant is intentional fail-closed behavior; all task publishers must supply ownership.

No migration is needed for these audit repairs. Phase 4 still depends on `i9e1a3c5d7f9`; no frozen migration/guard definition was modified. Existing slots, timestamps, IDs, event history and rewards remain readable. Source rollback needs no database rollback, but backend/frontend versions should be coordinated for subscription efficiency.

## Executed tests

Tests ran in sanitized copies, with synthetic tenants/users and an owned PostgreSQL 15 container on the existing disposable test port. Real PostgreSQL concurrency uses separate test schemas. API/backup/ASGI WebSocket fixtures use disposable SQLite even when the PostgreSQL fixture is enabled.

| Check | Actual result |
| --- | --- |
| Final Phase 4 plus new audit suite | **PASS: 36 passed**, PostgreSQL fixture enabled. |
| Same final suites, SQLite | **PASS: 27 passed, 9 skipped**. Skips require PostgreSQL concurrency, load or query plans. |
| Broader task/subtask/workflow/reward regression | **PASS: 129 passed**. Includes the earlier 35-case activity/audit set; counts overlap. Final column-projection/query-plan refinements were checked by the final suites above. |
| Frontend tests | **PASS: 60 passed**, including six new clock, cleanup, coalescing, retry, drift and subject/capacity tests. |
| Frontend build | **PASS**; existing Lottie eval and large-chunk warnings remain. |
| Whole frontend TypeScript | **FAIL: 112 pre-existing diagnostics**, matching the Phase 4 baseline after normalizing line/column locations; no new diagnostics. |
| Scoped Python syntax/Ruff and changed-line whitespace | **PASS**. |
| Whole backend execution | **NOT RUN**. Phase 4 retained four SQLite `to_tsvector` collection failures; this audit did not repair unrelated collection infrastructure. |
| Real deployed Redis/proxy/login/device load and installed migration | **NOT RUN**. Native signed ASGI sockets were tested with an in-process publisher bridge. Browser transport tests used a synthetic socket/API fixture. |

Concurrency checks cover six simultaneous distinct starts, concurrent same-key requests, resumes competing for the last slot, Start/Pause and subtask-switch version races, independent users with a common creator, crossed actor/creator ownership, and the exclusive reward barrier. Existing interruption rollback, duplicate interval, immutable history, tenant and actual-time preservation tests pass.

Signed socket tests cover cross-tenant and unauthorized watches, manager reporting, report relationship revocation, per-user invalidations, disconnected socket removal and zero remaining heartbeat tasks. The broadcaster fixture has **200 users/201 tabs**: one personal-work event performs **one authorization check and two deliveries**, leaving other users untouched. There is no permission cache surviving the event.

## Measured profiling

Controlled baseline and optimized profiles ran sequentially against the same owned PostgreSQL fixture, with other verification jobs and the UI fixture stopped. These are local **service-call** profiles, not HTTP/JWT/proxy/Redis end-to-end throughput or a production SLA. Other installed services were left running, so host scheduling and resource contention still affect timing.

The load fixture contains 200 users in one tenant, five parent/selected-child contexts per user, and ten confirmed manual intervals per user: 1,000 parents, 1,000 child contexts and 2,000 work intervals. It submits 200 snapshots with **20 request workers**, using the fixture's normal SQLAlchemy pool. All snapshots assert five active parents and 50 productive minutes; no mutation statements occur.

| Measurement | Baseline | Optimized |
| --- | ---: | ---: |
| SQL statements per child-context snapshot | 10 | 6 |
| SQL statements for 200 requests | 2,000 | 1,200 |
| Database INSERT/UPDATE/DELETE during reads | 0 | 0 |
| Median snapshot latency, 200-user run | 447.4 ms | 338.0 ms |
| p95 snapshot latency, 200-user run | 560.3 ms | 480.7 ms |
| Measured service-call throughput | 33.7 requests/s | 42.9 requests/s |
| Ten-request snapshot median | 56.5 ms | 34.2 ms |

The reliable structural reduction is **40% fewer SQL statements**; local timing is illustrative. `EXPLAIN (ANALYZE, BUFFERS)` on the disposable model-derived schema verifies the existing context/user lookup and task-assignee indexes. The deployed index inventory was not inspected or modified. The long-history regression passes with 1,100 child contexts; the original source fails that same SQLite case.

Actual Header/provider/component browser checks at 1280px and 390px verified:

* During a 2.4-second sampling window, elapsed text advanced `0:00:00` → `0:00:03`, with **zero activity-control body rerenders and zero aggregate requests**. A counter was injected only in the disposable component copy, then removed before final build/source verification.
* 100 unrelated-subject invalidations caused zero refetches. 100 own-subject invalidations caused one refetch. A report event fetched only the viewed subject.
* A held stale GET released after an acknowledged Pause did not overwrite the zero-active snapshot. Resume worked and manual actual timestamps stayed unchanged.
* Offline produced no reconnect loop; online created exactly one replacement socket. Late callbacks from closed sockets could not create another stream; one live socket remained.
* Opening/closing a report sent the watch/reset messages. Reload preserved the running count and elapsed anchor. Keyboard dialog dismissal and the existing mobile menu worked, with no horizontal overflow.

## Files changed

| Files | Purpose |
| --- | --- |
| `backend/app/services/task_activity.py` | Personal writer locks, narrow/batched read paths, chronology conflict. |
| `backend/app/services/subtask_rewards.py` | Optional shared advisory barrier; existing financial default stays exclusive. |
| `backend/app/ws/tasks.py`; `backend/app/routers/tasks.py` | Scoped invalidations, authenticated report watch, threadpool checks and transport cleanup. |
| `backend/tests/test_task_activity.py`; `backend/tests/test_task_activity_audit.py` | Updated payload expectation and concurrency/load/ownership/query-plan/resource regressions. |
| `frontend/components/Header.tsx`; `frontend/components/TaskActivityControl.tsx`; `frontend/components/ActivityElapsed.tsx` | Existing header wiring and isolated clock rendering; layout/styles retained. |
| `frontend/hooks/useTaskActivity.ts`; `frontend/hooks/useTaskWebSocket.ts`; `frontend/services/mockApi.ts` | Abortable/coalesced recovery, subscriptions, reconnect cleanup and silent background requests. |
| `frontend/utils/taskActivity.ts`; `activityClock.ts`; `activityRefresh.ts`; `taskSocket.ts` | Subject/count checks, shared clock, refresh scheduler and retry jitter. |
| `frontend/test/task-activity.test.ts` | Resource, timing, identity and capacity unit tests. |
| This report; Phase 4 report follow-up link; `docs/verification/zeaplay-subtask-v2-phase4-audit/` | Evidence, source hashes and retained profiling results. |

## Reproduction and remaining operational limits

Run only in a sanitized copy with the retained outbound-blocking `review_pytest.py` and an owned disposable database. The database fixture rejects targets other than its named loopback test database.

```powershell
$env:ZEA_TASK_AUDIT_TEST_URL = 'postgresql+psycopg://phase1@127.0.0.1:54317/zea_subtask_phase1'
python -B review_pytest.py backend/tests/test_task_activity.py backend/tests/test_task_activity_audit.py -o junit_family=xunit1
python -B review_pytest.py backend/tests/test_subtask_rewards.py backend/tests/test_subtask_reward_audit.py backend/tests/test_subtask_workflow.py backend/tests/test_task_tabs_review.py
# Profile sequentially in baseline/optimized sanitized copies:
python -B review_pytest.py backend/tests/test_task_activity_audit.py -k profile -o junit_family=xunit1
$env:ZEA_TASK_AUDIT_TEST_URL = $null
python -B review_pytest.py backend/tests/test_task_activity.py backend/tests/test_task_activity_audit.py
# From the sanitized frontend:
npm test
npm run build
npx tsc --noEmit --pretty false
```

Lifetime productive interval allocation remains an exact union over the user's stored intervals, and the compatible aggregate response still includes historical contexts. No arbitrary retention cap or unsafe cached balance was added. Extremely large individual histories need production-shaped profiling before a separate rollup/pagination design. The 200-user fixture is not evidence of 200 concurrent real devices, high-latency networks, multi-worker Redis delivery or production failover. Those installed-environment checks remain deployment validation work.

[Evidence](verification/zeaplay-subtask-v2-phase4-audit/) contains XML/logs, query plans, sequential profiles, browser assertions, baseline failure characterization and final source hashes. No installed application was rebuilt or deployed, and no production/private configuration was exported.
