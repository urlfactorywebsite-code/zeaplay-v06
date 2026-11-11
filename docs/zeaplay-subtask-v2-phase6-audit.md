# Phase 6 notification and workload review

Reviewed 2026-11-03 in this existing FastAPI/SQLAlchemy + React/Vite checkout. This report supersedes the affected worker/client details in the [implementation snapshot](zeaplay-subtask-v2-phase6-verification.md). The verification used isolated synthetic databases and the actual frontend components with a synthetic transport fixture. Installed services, application data, credentials and configuration were not used or changed.

## Repairs and optimizations

1. **Continuous events could starve the inbox refresh.** A trailing debounce reset on every event. The inbox now reuses the existing fixed-window activity refresh utility and keeps one HTTP request in flight with one follow-up. Browser presentation also retains one active batch and the latest pending batch. A batch resolves its service-worker registration once, rather than once per notification.
2. **Healthy sessions polled unnecessarily.** Inbox and workload interval refetching now stops while the existing shared WebSocket is connected. Reconnect/focus/online/visibility recovery refetches authoritative state. Disconnected sessions retain a single staggered aggregate recovery interval per mounted scope; hidden tabs skip event-driven reads. The workload schedules one local-day-boundary refresh using server time plus monotonic elapsed time. Notification invalidations also refresh workload indicators.
3. **Slow workload queries could be cancelled repeatedly by activity bursts.** The shared refresh utility now supports asynchronous single-flight work with one pending refresh. Workload invalidation waits for an existing query using `cancelRefetch:false`, then performs a queued follow-up when necessary. Cancellation clears pending work on cleanup. Existing synchronous consumers, including the information modal, keep their existing behavior.
4. **A nested rollback discarded successful outer notification invalidations.** Savepoints now preserve and restore the outer transaction's staged notification state. Successful outer work publishes after commit; rolled-back inner work does not publish. Releasing a savepoint still cannot publish before the outer commit.
5. **Queued deadline notices ignored later policy/data changes.** Before external delivery, the worker rechecks the canonical responsible user's current threshold, deadline identity, parent/child relationship, deletion/completion state and current authorization. Changed or expired approaching windows and invalidated deadline sources are acknowledged without sending an obsolete external alert. Stored inbox history remains intact.
6. **Delayed/reordered events received processing-time chronology.** Audit and ledger notifications now retain the source event's actual UTC timestamp. Replays use the same database idempotency keys. Older Start events cannot recreate a fifth-slot alert after a later context transition: the immutable context/version stream detects the newer event. Notification processing never replays a wallet payout or changes a context's status.
7. **One failed delivery could poison the SQL batch.** Each delivery isolates failed SQL work in a savepoint. Other recipients can complete. Valid device revocations and successful-device metadata survive ordinary transport errors; a failed SQL statement rolls back its own delivery work. The existing receipt receives retry state rather than a new job.
8. **A failing first push device could starve other devices.** Phase 6 retry delivery continues past fast device failures and rotates the starting endpoint using the persisted notification attempt number. A slow endpoint cannot always occupy the first position in the bounded request budget. Expired endpoints remain revoked even when another endpoint fails. Legacy calls with retry delivery disabled retain their existing behavior; existing n8n/webhook integrations were not rewritten.
9. **Browser tags alone did not prevent replay after card dismissal.** The existing service worker now stores a bounded receipt list for the current opaque account binding. Concurrent retries and worker restarts deduplicate the last 1,000 notification IDs, including after dismissal. Account binding, quiet/sound directives, same-origin links and denied-permission fallback remain. No bearer credentials enter worker storage. The foreground seen cache is bounded to 16 accounts × 1,000 IDs; native-card tracking remains capped at 100.
10. **Fanout issued one insert per recipient.** Authorized recipients are inserted in groups of at most 100 with the existing database uniqueness constraint and `ON CONFLICT ... RETURNING`. Duplicate roles/requests generate no additional rows or recipient invalidations. Existing legacy ORM-created inbox entries now produce an after-commit invalidation too, so stopping healthy-client polling does not strand those integrations.
11. **Burst draining waited for another full workload tick.** The existing single aggregate thread can drain ready delivery work after one second while preserving the separate workload-scan cadence. It does not rescan every employee on each drain tick. Scan failures are isolated from committed notification delivery. Retention updates at most 500 rows per pass and retains deduplication tombstones.
12. **Pending history needed a queue-order index.** Additive revision `k1a3c5e7f9b1`, after `j0f2b4d6e8a0`, adds `ix_notification_pending_chronology(created_at,id) WHERE delivery_pending IS TRUE`. Existing indexes and all data remain. The database chooses the older delivery index for a tiny ready subset and the new index for the tested large ready backlog.
13. **Monitoring lacked batch-level delivery counters.** Structured `notification_delivery_batch` logs report selected/processed/delivered/retried/quiet/suppressed counts, elapsed milliseconds and whether ready work remains. `notification_workload_scan_failed` identifies the failed scan scope without task content. Monitoring tests verify that private notification bodies are not logged.

No reward values, recipient ownership rules, tenant policy, authorization grants, manually confirmed times, productive-capacity standards, or unrelated page styles were changed.

## Coverage of requested scenarios

| Scenario | Verified behavior / evidence |
| --- | --- |
| Repeated events / recipient deduplication | Database uniqueness remains `(user_id,dedupe_key)`. Repeated/dismissed/restarted/reordered processing creates one stored row per authorized recipient/source/kind. Four concurrent workers process the same source safely. |
| Creator = assignee = manager = watcher | The same employee receives one notification. The test reprocesses the event twenty times. Existing multi-role creator/reporting-manager coverage also passes. |
| Removed watchers / unauthorized users | Current membership, navigation access, role visibility, active status and tenant ownership are checked at selection, inbox/actions and external delivery. Removed watchers cannot read or mutate their formerly visible task alerts, and queued delivery is suppressed. |
| Cross-tenant delivery | Raw managed notification insertion with mismatched ownership is rejected by database guards. API reads/actions and push subscription ownership remain scoped. WebSocket delivery also rejects inconsistent envelope tenant IDs and misrouted socket identities. |
| Out-of-order status/reward/activity events | Original chronology and stable IDs are retained. Old Start replay cannot restore a capacity alert. Replaying credits/reversals in reverse order leaves the wallet at its authoritative value; notification handlers never apply ledger deltas. |
| Queue retries / restarts | A new database session resumes a pending receipt with the same ID. Retry/dismissal does not insert another job. PostgreSQL `SKIP LOCKED` prevents two delivery workers from sending the same claimed row concurrently. SQL poison-row isolation and device timeout/revocation scenarios pass. |
| WebSocket reconnect / lost browser state | One shared socket remains mounted; reconnect refetches inbox and workload. Visibility recovery restores the authoritative badge. Unmount removes socket/listeners/recovery timers. No per-task subscription or worker is introduced. |
| Browser denied / inactive / closed | Denied permission preserves in-app delivery and never triggers a permission prompt. Hidden tabs skip inbox/workload reads during bursts. Worker tests simulate no open clients and persistent cache across worker restarts, preserving explicit background sound and retry deduplication. Actual OS/provider delivery was not exercised. |
| Sound / quiet preferences | Existing server preference checks, quiet deferral, silent browser presentation and one audible foreground presentation across tabs remain tested. A denied browser can still use an independently enabled in-app sound, subject to browser autoplay rules. |
| Read/unread badge changes | Counts include authorized unread rows beyond the visible page. Read/read-all/dismiss and persisted unread-state changes produce correct counts. The existing API has no mark-unread action; this review did not invent one. |
| Deadline threshold / due-date edits | Canonical assignee/creator responsibility is retained. Expanded windows observe an eligible deadline once; repeated scans do not duplicate it. Shrunk windows, changed deadlines and completed/deleted children suppress stale queued delivery. |
| Paused/completed activity | Counts use personal context state. A test with RUNNING, PAUSED and COMPLETED contexts reports one active slot. Legacy global task statuses are not treated as a proxy for personal activity. |
| Overlapping productive work | Two historical one-hour intervals overlapping by 30 minutes count as **5,400 seconds**, with **1,800 seconds** of overlap. A configured 6,300-second capacity does not produce false overtime. Existing rejection/correction/concurrency tests for newly entered overlaps also pass. |
| High-volume activity | 100 simultaneous invalidations coalesce to one inbox read. A sustained 20-ms event stream with 450-ms inbox/workload responses keeps one request in flight per scope and refreshes before the burst ends. A 207-recipient event replayed twice uses six bounded INSERT statements and produces 207 receipts. |

## Bounded work and idempotency

| Resource | Limit / lifecycle |
| --- | --- |
| Backend maintenance | One aggregate thread per API process, using the existing maintenance pattern. No thread/job/polling loop per employee or task. |
| Workload scans | Keyset batches of at most 100 users and 100 inactive-owner tasks per scheduled sweep. Existing scanning is still per-employee aggregation inside this bounded batch. |
| Recipient inserts | At most 100 recipients per INSERT. Stable database keys, including tenant, source and kind. No insert per retry. |
| Delivery claims | At most 100 receipts; `FOR UPDATE SKIP LOCKED`; an eight-second admission budget checked between receipts. Existing per-integration HTTP timeouts still apply to a single receipt. |
| Delivery retries | Same persisted row and attempt count; exponential delay capped at one hour. There is no arbitrary attempt cap that discards an undelivered alert. Fast backlog ticks reuse the same thread. |
| Retention | At most 500 old read/dismissed contents scrubbed per pass. Unread history and minimal deduplication tombstones are retained under the existing retention policy. |
| Client requests | Shared healthy socket; one in-flight aggregate read and one pending refresh per scope. Recovery intervals apply only while the socket is unavailable. Hidden/unmounted views do not create event-driven reads. |
| Client presentation | One active batch and the latest pending batch. Receipt and native-card caches are bounded. Elapsed clock rendering makes no database writes. |

Stored history and a legitimate delivery backlog can grow with **distinct authorized events**. This is not a claim that durable history has a fixed row cap. Reprocessing the same source cannot multiply stored notifications or retry jobs. Queue throughput and external failure rates still need operational monitoring.

## Real execution results

| Check | Result |
| --- | --- |
| Before-review Phase 6 SQLite baseline | **PASS: 51; SKIP: 1** PostgreSQL-specific case, 79.24 s. |
| Final notification suites, PostgreSQL 15 | **PASS: 77**, 0 failures/errors, 120.00 s. |
| Same suites, SQLite | **PASS: 76; SKIP: 1** PostgreSQL `SKIP LOCKED` concurrency case, 128.03 s. |
| Additional 5,000-row pending-index scenario | **PASS: 1 PostgreSQL + 1 SQLite**, 5.41 / 5.01 s. This was added after the full suite and run separately. Distinct notification coverage totals **78 PostgreSQL cases / 77 SQLite cases plus one skip**. |
| Existing activity and activity-audit regression, PostgreSQL | **PASS: 36**, 85.66 s, including five-slot/concurrency/productive-overlap/read-only snapshot/fanout checks. |
| Frontend Node suite | **PASS: 81**, 0 failures/skips. Includes async coalescer lifecycle, denied browser, quiet/sound, worker restart, duplicate and reordered push cases. |
| Real-component browser assertions | **PASS: 48**: 33 existing desktop/mobile/keyboard/settings checks; 4 simultaneous-tab checks; 11 new sustained-burst/slow-read/hidden/reconnect/no-polling/boundary/cleanup checks. Zero automatic permission prompts. |
| Frontend production build | **PASS**, 11.49 s. Existing chunk-size and Lottie warnings remain. |
| Whole frontend TypeScript | **FAIL: 112 pre-existing diagnostics**. Normalized comparison with the Phase 6 snapshot: **0 added, 0 removed**. |
| Focused Ruff, owned Python syntax and scoped whitespace | **PASS**. |
| Whole unrelated backend suite | **NOT RUN**. Prior reports record unrelated SQLite `to_tsvector` collection blockers; those were not newly reproduced or represented as repaired. |
| Production migration/deployment, actual Redis reconnect, real push provider/OS/browser permissions, production-sized histories | **NOT RUN**. |

The database suites use the complete actual ORM schema and synthetic ownership relationships in disposable namespaces/databases. Tests execute real SQL transactions and concurrency barriers. External integration calls are mocked. Browser automation renders the actual Header, hooks, activity popup and preferences under StrictMode with synthetic API/native transports; service-worker lifecycle and closed-client cases use its actual script in a deterministic VM fixture. The workload form's automated axe check reports zero violations/incomplete findings with contrast disabled; full accessibility/OS push certification is not claimed.

Initial new subtask fixtures attempted direct edits without required version increments; they were corrected to use the actual subtask service. An initial verification-copy build excluded the source `components/media` folder while excluding runtime media; restoring those source components fixed that harness error. Neither failure represented an application defect. Final executed results are retained with the successful logs/JUnit.

### Query and burst evidence

- The 5,000-row / 2,500-pending PostgreSQL `EXPLAIN` selects `ix_notification_pending_chronology` with `LIMIT 100` and no sort. SQLite also selects the partial chronology index. For the six-ready-row fixture PostgreSQL reasonably uses the existing `ix_notification_delivery` plus a small sort; both paths are retained.
- The existing 200-employee scenario runs in three keyset batches. It records **2,339 SQL statements**, compared with **2,539** in the implementation evidence. Current local durations are **3.985 s PostgreSQL / 1.616 s SQLite**. Durations from separate runs are not production throughput guarantees.
- The sustained browser burst performs three new inbox reads; inbox and workload maximum concurrency each remain one. Repeated timer callbacks while healthy cause zero periodic inbox/workload HTTP reads. The local-day boundary causes one workload refresh.
- Queue logs contain counters and timing, with a test explicitly rejecting leakage of a private notification body. Failed-scan scope logs and `due_remaining` expose recovery/backlog conditions without a user-visible or tenant-leaking monitoring endpoint.

Machine-readable results, JUnit/logs, query plans/profiles, browser assertions/scripts/fixtures, TypeScript comparison, guarded runner and exact source hashes are in [the audit evidence directory](verification/zeaplay-subtask-v2-phase6-audit/).

## Modified files and interfaces

- `backend/app/services/workload_notifications.py`: batching, original chronology, live deadline checks, savepoint state, isolated delivery, bounded retention, backlog scheduling and counters.
- `backend/app/services/push_service.py`, `notification_dispatcher.py`: optional internal retry-attempt forwarding and bounded device retry fairness. Public HTTP contracts are unchanged.
- `backend/app/ws/tasks.py`: fail-closed tenant-envelope/socket checks.
- `backend/app/models.py`; new `backend/alembic/versions/k1a3c5e7f9b1_notification_queue_review.py`: additive partial index only. No new tables/columns or enum changes.
- `frontend/hooks/useNotificationInbox.ts`, `useTaskActivity.ts`; `frontend/utils/activityRefresh.ts`, `notificationAlerts.ts`: coalescing, query/presentation bounds, socket-aware recovery, day-boundary refresh and bounded caches.
- `frontend/components/Header.tsx`, `TaskActivityControl.tsx`: existing stream/connection-state wiring. No restyling or replacement components.
- `frontend/public/sw.js`: bounded delivery receipts over the existing account binding/cache.
- `backend/tests/test_workload_notifications.py`; new `backend/tests/test_workload_notification_review.py`; `frontend/test/notification-service-worker.test.ts`, `task-activity.test.ts`.
- This report, the implementation report's superseding link and verification artifacts. The checkout already contained earlier dirty work; the full Git diff is not this review's change list.

No new mutation endpoint or notification center was introduced. Existing notification DTOs, read/dismiss APIs, settings, rewards and task APIs retain their response contracts.

## Rollout, rollback and remaining limits

Apply only the new additive revision `k1a3c5e7f9b1` after confirming the target revision chain and backup. The migration is repeatable and preserves existing rows, constraints and indexes; tests compare data before/after two upgrades. PostgreSQL lock/statement timeouts are five/120 seconds. A large production table may need a separately reviewed online index rollout. No installed migration or rebuild was performed.

Application rollback retains the additive index; its downgrade does not drop data or remove the performance index. Existing Phase 6 browser-binding rollout requirements remain. The owned verification PostgreSQL container and Vite server are stopped after checks; unrelated installed containers remain unchanged.

Provider delivery remains **at least once**: acceptance followed by process interruption can precede the database acknowledgement. Stable IDs, bounded worker receipts and browser tags mitigate external replay; the 1,000-ID browser receipt window does not promise permanent exactly-once OS presentation. Durable in-app idempotency remains database-enforced. Existing n8n/webhook consumers must deduplicate by notification ID, and existing provider timeouts can extend an individual operation beyond the between-row budget. A real Redis/provider outage, authenticated multi-device installation and target-size production load still require deployment-level verification.

To reproduce, use a sanitized source checkout with the archived `review_pytest.py` placed beside `backend/`. This run used an owned PostgreSQL 15 fixture on **localhost:15467** because 54317 was occupied; the runner only permits that fixture socket plus local socket-pair plumbing. Keep the existing fixture host/user/database and isolated-schema guards.

```powershell
$env:ZEA_TASK_AUDIT_TEST_URL='postgresql+psycopg://phase1@127.0.0.1:15467/zea_subtask_phase1'
python -B review_pytest.py backend/tests/test_workload_notifications.py backend/tests/test_workload_notification_review.py --basetemp F:\OwnedVerification\unique-pg-run
python -B review_pytest.py backend/tests/test_task_activity.py backend/tests/test_task_activity_audit.py --basetemp F:\OwnedVerification\unique-activity-run
Remove-Item Env:ZEA_TASK_AUDIT_TEST_URL
python -B review_pytest.py backend/tests/test_workload_notifications.py backend/tests/test_workload_notification_review.py --basetemp F:\OwnedVerification\unique-sqlite-run
# In the sanitized frontend:
npm test
npm run build
npx tsc --noEmit --pretty false
```

For the browser fixture, copy the archived `.fixture` files to scratch `frontend/checks/phase6.tsx` and `phase6.html`, provide the local axe script used by the regression check, serve localhost:6325 and execute the archived Playwright functions. They block installed application APIs and unrelated external assets. The fixtures contain only synthetic tokens and identities.
