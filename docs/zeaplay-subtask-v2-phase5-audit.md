# Phase 5 Task Information review and refinement

Reviewed against the existing [Phase 5 implementation](zeaplay-subtask-v2-phase5-verification.md) on 2 November 2026. This report supersedes that implementation report's timeline normalization, query/cache behavior and ledger presentation details. Changes are limited to the information read model, modal, contracts, tests and evidence. Existing Task Details editing, header/navigation, task mutations, rewards, authentication and schema migrations are unchanged.

**Result: affected source/disposable verification passes.** Whole-application TypeScript retains 112 baseline diagnostics. Historical main-task payouts remain unknown where no attributed ledger exists. Automated accessibility checks do not certify gradient contrast or real assistive-device behavior. Nothing was deployed or migrated in an installed database.

## Reproduced defects and repairs

Seven initial regression tests against the original source produced **six failures and one pass**. Final coverage adds eleven backend review tests and five frontend tests.

| Verified problem | Scoped repair |
| --- | --- |
| Managed subtask writes record `workflow_status`; the projection only read `status`. Actual Start/Pause/Resume/Testing/Complete/Reopen transitions were absent, leaving creation/personal activity as an incomplete substitute. | Normalize recorded workflow status, explicit status and legacy boolean completion snapshots. Original before/after fields remain intact in Activity. Missing previous values remain unknown. Unrecognized completion values are not cast to database booleans or invented as states. |
| Personal chronology partitioned by selected child, so switching to another child failed to close the previous child's elapsed interval. Same-time events sorted by random UUID rather than their recorded sequence. | Use the persisted personal context ID and event version. A parent's personal stream spans child selections; a child timeline includes handoffs into/out of that child. Durations require a consecutive context version and matching states; time spent on another child is not attributed back to the old child. Equal-time personal events use their stored versions. |
| A restricted legacy viewer could receive a duration spanning hidden intermediate transitions whose endpoints happened to match. | Omit legacy duration in restricted role projections. Owner/Admin legacy durations are explicitly spans between recorded transitions, not certified total time in a status. Unrecorded/purged history cannot be reconstructed. |
| Ledger entries displayed no actor despite an existing linked immutable event. | Resolve linked events and actors in source batches, with tenant/task ownership checks; retain original posting timestamp and event reference. No actor is inferred from recipient or current assignee. |
| Non-object legacy JSON could raise `.items()` errors and turn a valid read into HTTP 500. | Ignore unrecognized metadata shapes while retaining the event. Only allowlisted task fields are exposed. |
| Overview scanned child event history it never displayed; empty searches still loaded work/configuration data; subtask counts repeated the ordinal window/settings joins. | Overview reads parent totals without child-event aggregation. Child pages restrict elapsed aggregation to their IDs. Empty pages return before work/config reads. Count queries omit reward ranking and configuration joins. |
| Loaded cached parent priority could disagree with a concurrent database update while capacity/ledger rows were read. | Read current parent priority/team and reward policy data in the same statement as capacity/ledger aggregation or the selected child page. Use the existing resolver and immutable policy data. No reward recalculation occurs. |
| Returning to tabs discarded fresh data; overlapping library and custom reconnect handlers issued duplicate requests. | Retain a 15-second in-memory freshness window while open, one modal-level coalesced refresh controller, staggered 30–35-second foreground recovery, and explicit online/focus/visibility recovery. Disable the overlapping library focus/reconnect paths. Closing cancels requests and removes that modal scope's cached queries/listeners/timer. |
| Background fetching rerendered the whole unchanged subtask table; each render recreated the timestamp formatter. | Memoize history/table sections and the zone-aware formatter. Structural sharing preserves unchanged rows. Timezone changes reformat locally without an HTTP read. |
| Main/subtask ledger adjustments were combined in component and recipient displays without a separate recorded main subtotal. | Keep authoritative aggregate fields and add separate recorded main/subtask components and recipient subtotals. Full historic main/task earned stays null; a recorded subtotal is not presented as a complete historic payout. |
| A same-browser account change could leave information queries tied only to the previous account's UI state. | Bind query scope to account/role/department/activation/session and verify server `viewer_id`, task and section. Storage/focus identity or authorization-context changes remount the modal session and clear old queries. Wrong-viewer responses fail closed. |
| Status arrows had an unsupported `aria-label` on a generic span; repeated history buttons lacked child-specific names. | Use screen-reader text for arrows, descriptive history-button names, valid expanded-panel references, a table caption and dialog description. Preserve the existing visual tokens and layouts. |

## Review coverage

| Requested area | Verified behavior |
| --- | --- |
| Five tabs / parent versus child | Overview uses actual parent fields; no fabricated project/planned/manual actual values. Subtask assignment still inherits the existing parent ownership semantics. Shared assignments remain separate task IDs. |
| Status chronology | Real repository writes exercise TODO → IN_PROGRESS → PAUSED → IN_PROGRESS → TESTING → COMPLETED → TODO. Personal activity remains a separate labelled stream. Creation timestamps are real records, not invented historical transitions. |
| Dates / timezone / manual times | Planned values remain date-only. Actual and audit edit timestamps display in the configured IANA timezone, retain fractional precision and preserve source UTC. New York's repeated 01:30 EDT/EST instants remain distinct. Invalid legacy timezone settings explicitly fall back to UTC. No actual values are written by the modal. |
| Priority | Inherited display priority responds to parent priority; overrides remain distinct. Base capacity still uses the main-task priority and existing reward snapshot. A stale-ORM/concurrent-parent test verifies fresh database priority. |
| Accounting / recipients | Signed ledger base, bonus, penalty, adjustment and reversals remain separate. Available base is independent of earned values and contingent timing rewards. Former recipients' compensating entries remain visible. No arbitrary caps, wallet rewrites or historic rescoring. |
| Audit / exposure | Canonical live task tenancy/RBAC remains in force. Legacy logs retain actor/target/department rules; followers do not gain comment access. Other users' private confirmed-work notes and foreign user references remain hidden. Arbitrary metadata, headers, IPs and private configuration are excluded. |
| Accessibility / layouts | Accessible dialog/tabs, Escape/focus return, arrows/Home/End, a focus trap, internal long-history scrolling and horizontally scrollable tables. Real components exercised at 1280×900 and 390×844, including long names/notes, loading, empty and error states. |
| Large lists / reads | Existing 1,000-child and 500-event tests remain. Returned pages are bounded at 100; actor/source/ledger reads use batches, not one query per row. Existing query bounds remain ≤16 handler statements for a 100-row child page and ≤12 for a 100-row history page. |
| Realtime / context | The existing header socket remains the sole stream. Task/activity/app-refresh invalidations share one coalescer. Active child histories refresh alongside the current section. Search, selected child and child-page context survive tab changes; shrinking histories clamp their page. Closing leaves drafts in the original Task Details editor. |
| Missing/legacy data | Null dates/times, missing prior states, empty histories, malformed legacy metadata and unlinked historical rewards are handled explicitly. No fake events or payout values are inserted. |

## Accounting contract additions

The existing read-only route is unchanged:

```http
GET /tasks/{task_id}/information?section=overview|timeline|subtasks|points|activity&page=1&page_size=25
```

Existing search, child filtering, pagination validation and `Cache-Control: private, no-store` remain. The HTTP cache directive is unchanged; the new cache is transient application memory for the open modal, isolated by account/session and removed on close.

Additive response fields:

```typescript
viewer_id: string; // live authenticated server actor
points: {
  // Existing fields retain their meanings and signed totals.
  main_recorded_net: number;
  main_recorded_components: Record<string, number>;
  subtask_components: Record<string, number>;
  recipients: {
    id: string; name: string; net: number;
    main_net: number; subtask_net: number;
    components: Record<string, number>;
  }[];
};
```

Deploy this backend contract before/with the refined frontend. Existing clients can ignore the extra fields; the refined modal deliberately refuses an old response lacking a matching viewer identity.

Verified accounting example: a child earns base 30 plus bonus 15, while a separate recorded main-task adjustment is -7. The API reports main recorded subtotal **-7**, child net **45**, verified ledger net **38**. Recipient scopes remain separate (owner main -7, worker child 45). Full historical main/task earned remains **unknown**. The frontend reads these amounts directly; it does not sum current priority/status projections into a different reward total.

## Measured request/render behavior

Sequential before/after browser runs used the same synthetic API fixture and actual components. Render counters were added only in disposable instrumented copies and removed before final UI/accessibility checks. JSON fixture responses were cloned as real HTTP responses are, so the cache and server fixture do not share mutable object references.

| Controlled operation | Original | Refined |
| --- | ---: | ---: |
| Offline → online plus focus recovery | 2 reads | 1 read |
| Unchanged 25-row subtask table during a coalesced 100-event refresh | 2 table renders | 0 table renders |
| Quick return to an already loaded, still-fresh tab | New read | Cached authorized snapshot |
| Local timezone profile change | — | 0 data requests |

These are request/render counts in a controlled component fixture, not production throughput measurements. General task invalidations may affect grouped task records; the modal conservatively refreshes rather than incorrectly assuming an event's one task ID is a complete affected scope. There is no new socket, per-task polling loop, per-second database write, or backend timer process.

## Executed validation

All runs used a fresh sanitized source copy, synthetic tenants/users, disposable SQLite files and an owned tmpfs-backed PostgreSQL 15 container. Private environment files, runtime media and installed databases were excluded. The guarded test runner blocks outbound application connections except the owned fixture port. Installed services were left intact.

| Check | Actual result |
| --- | --- |
| Original Phase 5 + review suite, PostgreSQL fixture enabled | **PASS: 38 passed** (27 existing + 11 new). HTTP harnesses use disposable SQLite; repository/accounting cases use PostgreSQL. |
| Same suite plus existing task/API/workflow regression, SQLite | **PASS: 81 passed, 1 skipped**. Skip is the PostgreSQL-only concurrent-edit test. |
| That concurrent-edit test, separately on PostgreSQL | **PASS: 1 passed**, verifying one winner/one audit event. |
| Frontend tests | **PASS: 65 passed** (60 existing + 5 new), including actual QueryClient deduplication/invalidation/cancellation, wrong-viewer rejection, permission-context cache isolation and DST/precision formatting. |
| Production frontend build | **PASS**. Existing chunk-size/Lottie warnings remain. |
| Browser functional checks | **PASS: 73 assertions** (49 retained + 19 extended + 5 StrictMode checks), using real Task Details/modal components and synthetic API responses. StrictMode covers load/effect replay, cache, reconnect, cleanup and deactivation. |
| axe-core 4.14.0, WCAG 2 A/AA and 2.1 AA tags | **14 scans, zero automatic violations**. All five tabs at both sizes, expanded child histories, error, retry, empty and cold-loading states. Gradient contrast requires manual review; this is not full WCAG certification. |
| Scoped Ruff, Python syntax and source/fixture hashes | **PASS**. |
| Whole frontend TypeScript | **FAIL: same 112 baseline diagnostics**. Zero added/removed after normalizing line/column positions and nondeterministic union-member order; none in the new/refined information modules. |
| Whole backend suite, installed DB migration/deployment, production Redis/proxy/device/load checks | **NOT RUN**. Prior whole-suite SQLite `to_tsvector` collection failures remain outside scope. No new migration is needed. |

Evidence, scripts, source hashes and raw results: [Phase 5 audit evidence](verification/zeaplay-subtask-v2-phase5-audit/).

Representative commands in the **sanitized scratch copy**:

```powershell
$env:ZEA_TASK_AUDIT_TEST_URL='postgresql+psycopg://phase1@127.0.0.1:54317/zea_subtask_phase1'
python -B review_pytest.py backend/tests/test_task_information.py backend/tests/test_task_information_review.py
python -B review_pytest.py backend/tests/test_subtask_workflow.py::test_postgres_concurrent_edits_have_one_winner_and_one_audit
Remove-Item Env:ZEA_TASK_AUDIT_TEST_URL
python -B review_pytest.py backend/tests/test_task_information.py backend/tests/test_task_information_review.py backend/tests/test_task_tabs_review.py backend/tests/test_subtask_workflow.py
# scratch/frontend:
npm test
npm run build
npx tsc --noEmit --pretty false
```

## Changed files and outstanding risks

Changes: `backend/app/services/task_information.py`, `backend/app/schemas_task_information.py`, new `backend/tests/test_task_information_review.py`, `frontend/components/TaskInformationModal.tsx`, `frontend/types/taskInformation.ts`, new `frontend/utils/taskInformation.ts`, new `frontend/test/task-information.test.ts`, this report, the original report's follow-up link, and evidence. No model/migration, mutation router, reward writer, header or unrelated page was changed.

Outstanding limits:

* Historical main-task awards and missing/retained legacy transitions cannot be made complete from the existing records. Legacy recorded spans are not certified time-in-status totals.
* Gradient/partially obscured surfaces leave contrast checks requiring human review. Real screen readers, touch devices and all theme combinations are not certified by these viewport/keyboard/axe fixtures.
* Existing subscription scope can recover another contributor's personal-work changes through the 30–35-second foreground fallback/focus rather than instant delivery. Cached tab snapshots have a 15-second freshness window; every HTTP read rechecks authorization, and identity/role/department/activation changes isolate caches.
* Counts/window ranking still process eligible history; tested row/query bounds do not establish production query plans, peak throughput or a production SLA. No speculative index migration was introduced.
* Cross-section responses are separate snapshots. Recorded ledger sums/capacity and their parent priority/policy inputs share a statement snapshot; the modal does not promise a database-wide snapshot across all five tabs.
* Backend/frontend rollout must be coordinated for `viewer_id`. TypeScript baseline debt and prior whole-backend collection failures remain. Source rollback needs no data rollback; no production activation/deployment was performed.
