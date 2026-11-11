# ZeaPlay V2 Phase 6: workload alerts and notifications

The subsequent [Phase 6 audit](zeaplay-subtask-v2-phase6-audit.md) records current hardening, the additional queue-index migration, updated client/worker behavior and newer test results. The implementation evidence below remains its historical verification snapshot.

Verified 2026-11-03 against this FastAPI/SQLAlchemy/Alembic + React/Vite checkout. This is source and disposable-fixture verification, not an installed or production deployment. The Phase 0 architecture and Phase 3–5 accounting, activity and information-modal reports informed the integration. Earlier dirty work was preserved.

## Implemented behavior

| Trigger | Source and behavior |
| --- | --- |
| Fifth active parent task | Existing immutable activity event after the atomic Phase 4 admission succeeds. Different subtasks of one parent still occupy one parent slot. |
| Rejected sixth parent | Existing `409` remains. Its exception handler records a separately committed, request-keyed rejection alert after the attempted activity transaction rolls back; unauthorized task IDs generate no alert. |
| Approaching / overdue task and subtask | Bounded background scans use current deadlines, responsible employee's configurable window, and canonical task ownership. Completed/deleted subtasks are excluded. Managed unfinished children of completed parents remain monitored. Legacy unassigned tasks use their creator. An additional bounded task scan covers inactive responsible accounts so authorized creators/managers/watchers are not missed. |
| Productive overtime | Confirmed manual interval union for the employee's local day exceeds configured capacity plus the overtime threshold. Overlapping historical intervals count once. Elapsed timers do not supply productive hours. |
| Estimated overload | Existing remaining task estimates exceed remaining capacity: the smaller of unused productive capacity and future shift availability, including configured breaks. Unknown capacity stays unknown. |
| Assignment / reassignment / important task and subtask status changes / subtask completion | Existing task mutations and immutable workflow audit events supply the source. New subtasks explicitly notify their inherited assignee; parent reassignment is one scope event covering its inherited child assignments. Task completion retains the existing `TASK_COMPLETED` notification type. Identical retried assignments do not create another event. |
| Base credit / bonus / penalty / reversal | Canonical Phase 3 ledger components supply their stored signed amounts. The existing main-task payout emits its actual calculated components in the same transaction. Foundation record-only adjustments are not misrepresented as wallet payouts. No reward formula, legacy wallet balance or historical ledger entry is migrated or recalculated. |
| Permitted legacy task deletion | A tenant-bound deletion receipt remains readable after the parent row is removed. Existing immutable-history deletion restrictions still apply. |

Recipient candidates are the responsible employee, reporting manager (`manager_id`, with tenant-scoped legacy email fallback), task creator and followers. IDs are deduplicated. A reporting pointer or watcher row never grants access by itself: active status, creator-derived tenant ownership, current task visibility and canonical task-module navigation permission must also pass. Shared assignments retain the application's existing separate-task ownership semantics. Generic personal workload notices contain no private task detail. A former reward recipient who loses task access receives only their own signed balance adjustment, without task/subtask IDs, title or link.

Visibility is rechecked at inbox read, read/dismiss actions, external delivery and task-stream fanout. Report-subject workload visibility is rechecked after manager changes. Malformed foreign-tenant followers/reporting pointers are excluded. Managers gain no activity editing permission.

## Existing infrastructure reused

- `Notification` and `NotificationPreference` remain the durable inbox and preferences; there is no second notification center or notification database.
- `services/notification_dispatcher.py`, Web Push and the existing n8n/webhook event path deliver committed rows. Existing notification audit logging is retained.
- SQLAlchemy session hooks observe actual task writes, immutable activity events and reward-ledger entries. Alerts insert in the business transaction. Rollback discards them. Outer commit publishes one targeted invalidation per recipient; savepoint release does not publish early.
- `services/task_events.py` and `/ws/tasks` carry `notifications.changed` frames containing tenant and recipient scope, without task titles. Multiple sessions belonging to the same recipient receive invalidation; managers watching another employee's workload do not receive that employee's inbox stream.
- The existing Header, task activity popup, notification dropdown and Settings notifications panel are extended. Header reads a bounded inbox plus its authoritative total unread count. A `99+` visual badge retains the actual unread count in its accessible name. Mobile navigation shows an unread indicator before expansion.
- One aggregate process-local maintenance thread follows the existing maintenance pattern. It is independent of slow webhook HTTP delivery, performs no per-task polling and makes no per-second timer writes. Duplicate API-worker scans coordinate through database keys and delivery row locks.

Header invalidations coalesce for 200 ms. The foreground fallback refetch is staggered at 30–35 seconds, plus socket reconnect, online, focus and visibility recovery. Existing ticking clocks render on the client. Session/role changes clear private previews; late responses from an old token are ignored. Unmount cleans subscriptions, listeners and timers.

## Storage, idempotency and retention

Migration **`j0f2b4d6e8a0`**, following **`i9e1a3c5d7f9`**, adds:

| Existing table | Additions |
| --- | --- |
| `notifications` | Nullable `tenant_id`, `dedupe_key`, `alert_kind`, UTC `dismissed_at`; `delivery_pending` (old rows default false), `delivery_attempts`, UTC `next_delivery_at`. |
| `notification_preferences` | `sound_enabled`, `near_deadline_hours`, nullable `productive_capacity_hours`, `overtime_threshold_minutes`, nullable `quiet_start`/`quiet_end`. |
| `push_subscriptions` | Nullable tenant snapshot `tenant_id` and opaque UUID `binding_key` for safe existing-device enrollment. No authentication tokens are stored in the service worker. |

Database uniqueness on `(user_id, dedupe_key)` is authoritative. Inserts use `ON CONFLICT DO NOTHING RETURNING`; psycopg's `rowcount` is not used to infer a newly inserted row. Keys include tenant, source and alert kind. Ownership/key/task references of managed receipts are guarded against mutation. Numeric policy bounds are enforced in both API validation and database guards. Quiet-hour format and paired fields are validated by the preference endpoint.

Deadline identity includes parent, optional child, deadline instant and approaching/overdue kind. Repeated scans, read/dismiss and duplicate workers do not recreate the same alert; a changed deadline produces a new source. Productive/estimated overload alerts deduplicate per employee/local day/kind across roles and affected tasks. Separate genuine activity threshold crossings and status events remain separate events.

Indexes: unique recipient/event key; partial `(user_id, created_at, id) WHERE dismissed_at IS NULL` inbox lookup; `(delivery_pending, next_delivery_at)` delivery lookup; unique nullable push binding. The native PostgreSQL fixture's 5,000-row plans use `ix_notification_inbox` and `ix_notification_delivery`. Actual live-visibility SQL, not a simplified inbox query, is profiled.

Delivery uses `FOR UPDATE SKIP LOCKED`, bounded batches, an 8-second processing budget and bounded push HTTP requests. Transient failures remain pending with exponential retries capped at one hour; invalid endpoints are revoked. Quiet hours defer external delivery for five minutes while the in-app row remains immediately available. A crash after provider acceptance but before database acknowledgement can redeliver externally: delivery is **at least once**, while durable storage is unique. Browser notification tags use the notification ID with `renotify:false`; external webhook consumers must also deduplicate by notification ID. Exactly-once provider side effects are not claimed.

`VEE_NOTIFICATION_RETENTION_DAYS` defaults to 30. After that age, managed read/dismissed content is scrubbed and dismissed. Unread alerts are retained. Minimal deduplication tombstones remain so old jobs cannot revive dismissed alerts. Existing account deletion/cascade behavior is preserved. Backup allowlists include the additive inbox/preference fields and task restore dependency; push subscriptions remain excluded from portable backups.

## Browser delivery security and compatibility

Browser permission is requested only by the existing user-clicked enable action. Denied/default/unsupported permission does not block in-app storage or unread counts. Sound defaults off, quiet hours use the recipient's profile timezone, and foreground sound follows the explicit preference. Web Locks plus optional local storage deduplicate foreground sound across tabs; a bounded in-memory cache prevents page-level replay if optional storage is denied/corrupt. Browser permission and OS autoplay restrictions still apply.

Push fixes include owner-scoped unsubscribe, serialized concurrent endpoint enrollment, and cryptographic subscription-key proof before changing an endpoint's user. Delivery requires the device's tenant snapshot to match the active current owner. Cross-user/tenant enrollment rotates its opaque binding nonce. The worker stores only that nonce and rejects missing, logged-out and previous-account push payloads. Logout/account changes clear the worker binding and old notification cards; native fallback cards are also closed and tracked with a bounded collection. Notification links stay within the existing same-origin hash router.

`POST /push/subscribe` remains `204` with the existing payload; the updated client additionally sends `binding_protocol:"user-v1"` and receives `X-Zea-Push-Binding` (CORS-exposed). Legacy device rows are preserved but unbound background delivery is suppressed until an authenticated visit silently re-enrolls an existing, already-permitted subscription. This never prompts for permission or creates a subscription without the user's enable action. Worker-update/online recovery retries enrollment. Worker acknowledgement is required before enabling bound delivery. An unavailable worker leaves in-app delivery intact. Provider retries use a stable tag. Visible application windows handle foreground sound; their worker delivery stays silent to avoid a second beep. Legacy payloads without a sound directive retain the browser default.

The existing authentication system remains stateless JWT authentication. This work binds browser routing to the active account; it does not introduce token revocation/session infrastructure or claim to revoke an independently stolen JWT.

## API and configuration

Existing notification list/read/read-all/dismiss routes remain. Additive `GET /notifications/inbox?limit=100&offset=0` accepts limits 1–500 and returns:

```text
{ user_id, items: NotificationRead[], unread_count,
  push_enabled, sound_enabled, quiet, server_now }
```

`NotificationRead` adds optional `alert_kind`; legacy response fields remain. Notification timestamps serialize UTC, including legacy timestamps whose existing storage contract is naive UTC. No fabricated status history is introduced.

Existing `GET/POST /notification/preferences` supports partial updates to:

```json
{"preferences":[{"module":"tasks","push_enabled":true,"sound_enabled":false,
 "near_deadline_hours":24,"productive_capacity_hours":null,
 "overtime_threshold_minutes":0,"quiet_start":null,"quiet_end":null}]}
```

Omitted additive fields retain stored values. Capacity is a personal override, not a new organization-wide standard. Blank capacity uses the existing configured shift/breaks; without either source, overtime/remaining capacity is unknown and no capacity alert is invented. Approaching threshold is 1–8760 hours, capacity if supplied is finite and >0 to 24 hours/day, overtime threshold is 0–1440 minutes; quiet times must be a valid paired `HH:mm` range. Overnight quiet windows are supported; identical endpoints mean quiet all day. Existing module push preferences remain independent from in-app storage. Concurrent preference creation/partial updates lock the existing user row to prevent duplicate module rows/lost partial updates.

Existing activity snapshot responses add `remaining_capacity_seconds`, `overtime_threshold_seconds` and `near_deadline_window_hours`; old fields are retained. No new activity/reward mutation endpoint is introduced. Productive time, manually entered actual timestamps and server-recorded elapsed activity remain separate.

## Modified source files

This is the Phase 6 contribution list within an already dirty checkout. It is not the entire Git diff. Exact tested file hashes are in [source-sha256.json](verification/zeaplay-subtask-v2-phase6/source-sha256.json).

- Models/contracts/startup: `backend/app/models.py`, `schemas.py`, `main.py`; `backend/alembic/versions/j0f2b4d6e8a0_workload_notifications.py`.
- Notification/activity/reward integration: `backend/app/services/workload_notifications.py` (new), `notification_schema.py` (new), `notifications.py`, `notification_dispatcher.py`, `push_service.py`, `task_activity.py`, `gamification.py`, `audit_logger.py`.
- API/realtime/backup: `backend/app/routers/notifications.py`, `notification_preferences.py`, `push.py`, `tasks.py`; `backend/app/ws/tasks.py`; `backend/app/backups/registry.py`.
- Frontend Header/preferences: `frontend/components/Header.tsx`, `TaskActivityControl.tsx`, `SettingsNotificationsPanel.tsx`, `WorkloadAlertSettings.tsx` (new).
- Frontend contracts/delivery: `frontend/types.ts`, `types/taskActivity.ts`, `services/mockApi.ts`, `services/tokenStorage.ts`, `services/pushBinding.ts` (new), `utils/notificationAlerts.ts` (new), `utils/pushBinding.ts` (new), `utils/taskActivity.ts`, `hooks/useNotificationInbox.ts` (new), `hooks/usePushNotifications.ts`, `public/sw.js`.
- Tests: `backend/tests/test_workload_notifications.py` (new); `frontend/test/notification-alerts.test.ts`, `notification-service-worker.test.ts`, `push-binding.test.ts` (new).

## Verification results

The complete current schema and synthetic identities are used in fresh disposable SQLite databases and PostgreSQL namespaces. The native migration test reconstructs actual pre-Phase-6 notification/preference/push tables, including PostgreSQL enum types and foreign keys, runs the additive migration twice, and compares old notifications/preferences, wallet values and historical ledger rows. This is **not a production database copy**. No `.env`, production credentials, runtime media or application data were imported. Outbound application sockets were blocked except the owned PostgreSQL fixture; provider delivery was mocked.

| Check | Real result |
| --- | --- |
| Final Phase 6 suite, disposable PostgreSQL 15 | **PASS: 52**, 0 failures/errors, 86.80 s. |
| Same suite, disposable SQLite | **PASS: 51**, **SKIP: 1** PostgreSQL-specific concurrent delivery case, 86.43 s. |
| Existing activity/reward/concurrency audit suites, PostgreSQL | **PASS: 86**, 297.60 s. Run during this phase before final notification-only refinements. |
| Broader existing workflow/activity/reward/backup/information/task-tab regression, SQLite | **PASS: 210**, **SKIP: 20**, 437.45 s. Run during this phase before final notification-only refinements. |
| Subsequent activity/task-tab compatibility run | **PASS: 53**, **SKIP: 9**, 117.20 s. |
| Final frontend Node tests | **PASS: 77**, 0 failures/skips. |
| Final frontend production build | **PASS**, 12.38 s. Existing large-chunk/Lottie warnings remain. |
| Real-component browser checks | **PASS: 37 assertions**: 33 Header/settings/activity checks plus 4 simultaneous-tab checks at desktop/mobile sizes. Actual components/providers under StrictMode; synthetic API/native transport fixtures. Zero automatic permission prompts. |
| Axe 4.14 | **PASS: 0 violations / 0 incomplete** for workload form and notification controls, with contrast rule disabled. Full application/theme contrast certification **NOT RUN**. Screenshots visually inspected at 1440×1000 and 390×844; remote image assets were intentionally blocked in the fixture. |
| TypeScript | **FAIL: 112 pre-existing diagnostics**, exactly the Phase 5 baseline after normalizing locations and nondeterministic union order. **0 added / 0 removed**, no new Phase 6 diagnostics. |
| New Python services/migration/tests Ruff; all owned Python AST; scoped whitespace check | **PASS**. |
| Whole backend collection | **NOT RUN**. Prior report records unrelated SQLite `to_tsvector` collection blockers. Those are not represented as fixed or freshly reproduced here. |
| Installed migrations, installed Docker rebuild, actual VAPID provider delivery, deployed Redis/proxy/multi-device sessions, production-scale histories | **NOT RUN**. |

The focused tests cover role/tenant/navigation revocation, multiple-role recipients, fifth/sixth admission, concurrent event inserts/delivery/preference/enrollment, rollback, savepoints, quiet/retry/revocation, unread counts beyond the visible page, dismissal/replay, deadline changes, inactive/unassigned responsibility, completed-parent pending children, configured capacity without invented defaults, retention, manager changes, reward components/reversals and absence of historical recalculation.

Profiling evidence: 200 synthetic employees scanned in 3 keyset batches of at most 100; PostgreSQL 4.674 s and SQLite 1.973 s, 2,539 SQL statements. This is a bounded local profile, not a production SLA or a claim of fully set-based aggregate processing. Existing Phase 4 PostgreSQL profile also passed 200 snapshots at concurrency 20 with zero writes, and targeted fanout delivered only to the subject's two tabs among 201 sockets. Actual alert latency depends on user count, 30-second worker ticks, batch work, delivery backlog and quiet hours; a complete sweep can require several ticks. Large production datasets and worker counts still require measurement.

Financial regression example (existing rules, unchanged): opening wallet 100; main base +30 and bonus +15; additional subtask base +60, bonus +15 and penalty -15; final wallet **205**. Reopening the bonus-bearing additional subtask posts **-30 and -15** compensating entries, leaving wallet **160**. These components generate separate alerts; Phase 6 does not calculate a second reward total.

Evidence: [machine-readable results](verification/zeaplay-subtask-v2-phase6/results.json), JUnit/logs, query plans/profiles, TypeScript comparison, browser scripts/fixtures, assertions and screenshots are in [the verification directory](verification/zeaplay-subtask-v2-phase6/). A nonfatal 45-second diagnostic traceback from the scratch runner during a long test run/cleanup is retained in logs; JUnit and process completion confirm success. Existing SQLAlchemy/Pydantic/naive-UTC deprecation warnings remain.

## Reproduction and rollout dependencies

Run only in an explicitly sanitized scratch checkout with dependencies available. `review_pytest.py` changes its working directory to its own parent, configures synthetic SQLite/test signing settings, blocks outbound sockets except the owned fixture, and expects `backend/` beside it. Copy the archived runner to the scratch root. PostgreSQL fixture setup must use the existing guarded `test_task_audit_foundation.py` contract (owned localhost port 54317, `phase1` synthetic user, `zea_subtask_phase1`, isolated namespaces).

```powershell
$env:ZEA_TASK_AUDIT_TEST_URL='postgresql+psycopg://phase1@127.0.0.1:54317/zea_subtask_phase1'
python -B review_pytest.py backend/tests/test_workload_notifications.py --basetemp F:\OwnedVerification\unique-pg-run
Remove-Item Env:ZEA_TASK_AUDIT_TEST_URL
python -B review_pytest.py backend/tests/test_workload_notifications.py --basetemp F:\OwnedVerification\unique-sqlite-run
# From the scratch frontend directory:
npm test
npm run build
npx tsc --noEmit --pretty false
```

For browser reproduction, copy `.fixture` files into scratch `frontend/checks/` using their original names, serve that scratch frontend on localhost:6325, provide axe locally for the optional accessibility checks, and run the archived Playwright functions against `/checks/phase6.html`. Routes deliberately prevent access to the installed application API.

Deployment order (prepared, **not executed**): verify target backup and current Alembic revision first; review the exact additive migration against a sanitized target-sized copy; apply `alembic upgrade j0f2b4d6e8a0` only to a known compatible revision chain; then release the matching backend, frontend and worker together. Do not stamp, bootstrap or broadly upgrade an unknown/unversioned database. PostgreSQL DDL uses a 5-second lock timeout and 120-second statement timeout. Index creation is transactional, so very large tables may need a separately reviewed online index rollout; zero downtime on production data is not certified.

Rollback retains new tables/columns, notification rows, idempotency keys and push ownership bindings; the destructive Alembic downgrade intentionally refuses. Stop the new producers/delivery process and roll application code back without dropping data. An old frontend/worker cannot safely participate in the binding protocol: pause browser push during a mixed-version rollback and use the in-app inbox. Do not restore unsafe legacy push delivery merely to maintain background alerts. No installed services were migrated or rebuilt during this work.
