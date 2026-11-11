# All Tasks tabs: review, fixes and validation

Review date: 2026-10-29. Checkout: `F:\Projects\zeaplay-05\zea-play-08-05-26\zea-play`.

**Overall release result: FAIL.** The scoped task functionality/security checks pass. Repository-wide TypeScript, lint and legacy backend collection failures remain. No deployment, installed database migration, commit or reset was performed. Unrelated working-tree changes were preserved.

This review supersedes the implementation snapshot in [centralized-all-tasks-report.md](centralized-all-tasks-report.md), particularly its earlier UTC-only calendar grouping and separate list-cache architecture.

## Issues fixed

1. **Task tenant isolation:** real API tests reproduced an Owner receiving another tenant's task. Task lists, direct reads/updates, calendar and board visibility now enforce ownership through the existing creator's tenant. Assignees, approvers, followers and new dependency links cannot reference foreign tenant records. Task comment reads/deletes and foreign comment-author injection are also blocked. Historical foreign relationships are filtered from task responses without deleting the stored records.
2. **Workflow bypasses:** both PATCH status updates and the completion endpoint now reject unfinished or inaccessible dependencies. Required approval remains pending after completion; deployment requires approval when configured. An ordinary assignee cannot disable approval, replace its approver or supply completion timestamps. Creator/staff configuration access and existing task access checks remain in force.
3. **Calendar timezone mismatch:** the grid, summary API, day/range API, day filters, due-time display, scheduling and cache keys now use the profile's valid IANA timezone, falling back to the browser timezone. Existing clients omitting `timezone` retain UTC behavior. UTC database timestamps are preserved; aware incoming deadlines are normalized to naive UTC. Half-open midnight-to-next-midnight bounds handle 23/25-hour DST days. Invalid zones, invalid upper bounds and excessive calendar ranges are rejected. `tzdata` is declared for environments without system timezone data.
4. **Calendar dialogs and rollback:** creating a task from a day drawer now closes that drawer before opening the existing creation form. Calendar wall times are submitted as UTC; nonexistent DST wall times produce validation errors. Failed date changes restore the visible task's previous date.
5. **Gantt date/dependency handling:** naive backend timestamps are interpreted as UTC. Calendar-day intervals use the same resolved timezone and remain stable across midnight and DST. Deadlines before creation retain both recorded endpoints rather than using an absolute duration extending into future dates. Existing dependency IDs/titles survive API mapping and appear in timeline tooltips. No dependency-editing engine was added.
6. **Kanban pagination and renamed columns:** task membership and styling use stable status IDs rather than editable titles. Renamed columns remain visible. The existing API now accepts an optional `page` parameter, with stable per-column ordering and offsets; the UI uses server counts and no longer slices an already limited first page. Existing clients default to page 1. Subtasks and follower IDs are included in card responses using batched relationship loading.
7. **List caching and page size:** list queries and adjacent-page prefetch now share the existing React Query client. The duplicate list/board/summary LRU paths and unused prefetch branches were removed. In-flight requests are deduplicated; list/grid reuse identical server results. Empty adjacent pages are not prefetched. Selecting 100 tasks per page is honored; grid mode no longer multiplies requests beyond the API limit. Cancelling unchanged task dialogs does not refetch the list.
8. **Private caches and deep links:** task comments use session-bound memory caching and reject late responses after an account change. Backend task cache identities include role and department so privileged results cannot be reused after demotion. UUID notification links `/tasks/{id}` redirect to `/tasks?taskId={id}`, preserve filters/anchors/state and open existing Task Details. Unknown tab names still show Not Found.
9. **Visibility, draft protection and accessibility:** all tab controls reference existing panel elements without mounting unvisited views. A directly accessed hidden-only tab leaves another visible tab keyboard reachable. The wider Settings run reproduced a draft-loss registration race; draft registration now occurs before the next interaction and the navigation predicate reads the current draft registry. The final Sidebar Management regression run passes all 77 groups.
10. **Stale/unsafe browser behavior:** obsolete commented Calendar implementations, unused calculations and unused serializers were removed. Opening Calendar no longer automatically posts viewed task data to a hardcoded external webhook. Configured backend event integrations and local calendar notes/reminders remain in place.

## Requested validation matrix

PASS means the specific local/source/disposable/fixture evidence below passed. It does not certify an external installation.

| # | Requirement | Result and actual evidence |
| --- | --- | --- |
| 1 | No independent Kanban/Gantt sidebar entries | **PASS:** browser checks find one All Tasks link and no standalone visualization links. |
| 2 | One All Tasks item, no submenu/dropdown | **PASS:** existing flat sidebar renderer and authoritative registry retained; parent stays highlighted on child routes. |
| 3 | Four tabs inside All Tasks | **PASS:** exact tab count, order, route selection, ARIA panel references and keyboard navigation checked. |
| 4 | Existing view functionality | **PASS within inspected scope:** existing list/grid, board, timeline, Calendar, creation and details components are reused; API/interaction tests exercise the principal actions. Unsupported engines are identified below. |
| 5 | Full-page Calendar replacement | **PASS for the resulting UX:** full-width month/week/day Calendar is inside its tab. Inspection found a Date Range filter popover, not a Calendar navigation popup, in this checkout; that filter remains. Task selection uses existing Task Details. |
| 6 | No data/history/comments/attachments lost | **PASS for persisted fields and references:** a real status PATCH retains an existing audit-history record, comment, attachment reference, subtask and dependency. Historical foreign relationships are not deleted. Three workspace database hashes remain unchanged. Live uploaded-byte/storage verification: **NOT RUN**. |
| 7 | Workflow rules enforced | **PASS:** real handlers return 403 for unrelated updates/assignee workflow-field injection, 404 for foreign references, and 409 for incomplete/inaccessible dependencies or missing required approval; valid completion/deployment succeeds. Board 403 rollback is also exercised in browser. |
| 8 | Gantt dates/dependencies accurate | **PASS for existing recorded fields:** UTC parsing, timezone civil-day intervals, DST and reversed endpoints tested; dependency mapping/tooltips checked. No editable dependency graph or separate scheduled-start field exists here. |
| 9 | Calendar timezone correct | **PASS:** browser timezone America/Los_Angeles with profile Asia/Kolkata; every calendar request carries the profile zone. Real summary/day endpoints agree at local midnight; New York 23/25-hour DST boundaries include the lower bound and exclude the next midnight. |
| 10 | Active timers survive tab switching | **NOT RUN for a dedicated active-work timer:** no such provider/module exists in this checkout. Retained panel nodes, view/page state and absolute due timestamps are verified; no timer service was invented. |
| 11 | Realtime across views | **PASS in controlled fixtures:** one incoming task event updates all four visited views. Existing authenticated server socket/tenant-policy regression tests also pass. Live multi-user delivery: **NOT RUN**. |
| 12 | No duplicate sockets/unnecessary requests | **PASS for tested request paths:** exactly one live task socket across switches; none reconnects after module exit. Unvisited views fetch nothing. Prefetch/live consumers share one request. List/grid reuse cache; unchanged-dialog close and invalid empty-page prefetch checks pass. |
| 13 | Sidebar Management remains consistent | **PASS:** task-tab group/protected default tab verified; all 77 wider Settings groups pass, including rename/order/drag, dirty drafts, policy confirmation, reset, conflicts and mobile controls. |
| 14 | Unauthorized direct tab URLs blocked | **PASS:** role-ceiling and disabled-child URLs redirect before privileged view requests. Backend policy inheritance tests pass. Hidden-only visibility retains established authorized direct-access behavior. |
| 15 | Deep links/redirects | **PASS:** all three legacy visualization routes retain queries/anchors; refresh, Back and Forward work; UUID task notifications open Task Details and retain location details. |
| 16 | Filters/sorting/pagination | **PASS:** real API search/priority/team filtering and title sorting across pages; list page 2 retention, 100-task selection, grid reuse, per-column second pages and renamed columns tested. Shared filters remain URL-backed; incompatible Gantt Unassigned state stays separate. |
| 17 | Existing actions/dialogs | **PASS in API/browser tests:** creation POST, editing PATCH, subtasks/details, Calendar day creation, date movement, denied-change rollback and modal closure work. Attachment/comment records remain intact. |
| 18 | Desktop/mobile usability | **PASS in Chromium viewports:** 1440px, 768px and 390px, keyboard tabs, internal chart/calendar scrolling, unclipped filters and no document horizontal overflow. Screenshots inspected. Physical touch/cross-browser testing: **NOT RUN**. |
| 19 | Duplicate/stale task code | **PASS for scoped task logic:** one board renderer, one shared subscription, shared list/prefetch queries; obsolete LRU branches, commented Calendar code, unused serializers and hardcoded automatic external posting removed. No repository-wide dead-code rewrite attempted. |
| 20 | Build and automated checks | **PASS:** production build, 200 combined backend tests, final 26-case task rerun, 41 frontend tests, 25 task browser groups and 77 Settings groups. **FAIL at repository level:** TypeScript, full Ruff and legacy backend collection, detailed below. |

## Executed checks and saved evidence

| Check | Result |
| --- | --- |
| Combined task + avatar/profile + navigation/security/migration backend command | **PASS: 200 tests** in disposable fixtures; [exact output](../frontend/checks/task-tabs-review-backend.txt). |
| Final task API review rerun after final privacy/dependency cleanup | **PASS: 26 tests**; [exact output](../frontend/checks/task-tabs-review-final-task-tests.txt). |
| `npm test` | **PASS: 41 tests**; [exact output](../frontend/checks/task-tabs-review-unit.txt). |
| Task Chromium interaction checks | **PASS: 25 groups**, zero uncaught errors and zero external task-data POSTs; [JSON](../frontend/checks/task-tabs-review-browser-results.json). |
| Wider Settings Chromium regressions | **PASS: 77 groups**, zero uncaught errors; [JSON](../frontend/checks/task-tabs-review-settings-results.json). An earlier run reproduced the intermittent draft-loss failure and six cascading failures; the guard fix precedes this passing run. |
| `npm run build` | **PASS**; existing dependency/large-chunk warnings remain; [exact output](../frontend/checks/task-tabs-review-build.txt). |
| Full configured Ruff on calendar helper, task review tests, navigation registry and policy tests | **PASS**. |
| Ruff `E9,F` on touched task/comment routers and existing task socket | **PASS**. Full router lint still includes pre-existing style/dependency-default warnings. |
| Repository-wide Ruff | **FAIL: 2,421 violations**, compared with 2,423 before review; [statistics](../frontend/checks/task-tabs-review-lint.txt). |
| `npx tsc --noEmit --pretty false` | **FAIL: 113 diagnostics**, identical to the review baseline after normalizing line numbers; zero new signatures; [exact output](../frontend/checks/task-tabs-review-typecheck.txt). |
| Frontend ESLint | **NOT RUN:** no ESLint script/package is configured. |
| Entire backend test directory | **FAIL during collection** in four older SQLite modules using PostgreSQL `to_tsvector`; [error summary](../frontend/checks/task-tabs-review-full-backend.txt). Temporary cwd and blocked external sockets protect workspace databases. |
| `git diff --check` | **PASS**. |
| Workspace test databases | **PASS:** all three SHA-256 values match before/after verification; [summary/hashes](../frontend/checks/task-tabs-review-verification.json). |
| Deployment/shared DB migration | **NOT RUN**, as requested. |

The full-backend collection failures are `test_generate_token.py`, `test_oauth2_server.py`, `test_task_list.py` and `test_ticket_tenant_permissions.py`. The new isolated task fixture registers a deterministic SQLite function solely to permit the existing generated column; it does not emulate or certify PostgreSQL full-text search. External notifications, webhook delivery, badge/points side effects and task-to-ticket completion side effects are stubbed in the task endpoint fixtures. Their actual external delivery/reward behavior is not certified by these checks.

The combined backend command, from the repository root, was:

```powershell
$env:VEE_DATABASE_URL='sqlite:///:memory:'
$env:VEE_BOOTSTRAP_SCHEMA='false'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest backend/tests/test_task_tabs_review.py backend/tests/test_employee_avatar_profile.py backend/tests/test_settings_security.py backend/tests/test_navigation_policy.py backend/tests/test_navigation_readiness.py backend/tests/test_navigation_socket_auth.py backend/tests/test_navigation_sockets.py backend/tests/test_api_settings_migration.py -q -p no:cacheprovider --disable-warnings --tb=short
```

The final task-only rerun uses `backend/tests/test_task_tabs_review.py` with the same flags. Frontend commands run from `frontend`: `npm test`, `npx tsc --noEmit --pretty false`, `npm run build`.

To reproduce browser checks, run Vite locally on port 6322 with `VITE_API_URL=/api` and `VITE_API_BASE_URL=/api`, then invoke `verifyAllTasks(page)` from `frontend/checks/all-tasks.browser.js` in a fresh Playwright context with timezone `America/Los_Angeles`. All APIs are intercepted and task sockets are controlled. The Settings check uses its existing script with its local origin changed from port 6319 to 6322. Temporary verification contexts and the Vite fixture are closed after testing.

## Architecture and compatibility

- `/tasks`, `/tasks/kanban`, `/tasks/gantt`, `/tasks/calendar` remain the canonical frontend paths. `/kanban`, `/gantt`, `/calendar` redirect. Existing UUID `/tasks/{id}` links now redirect into the default view with a `taskId` query.
- No backend task API path was renamed. New optional `timezone` and Kanban `page` parameters retain legacy defaults. Calendar ranges are bounded to protect database aggregation work.
- No model, schema migration, task ID, stored deadline or dependency relationship was rewritten. Tenant ownership uses existing creator/user relationships; invalid historical relationships are hidden, not deleted.
- Existing role ceilings, navigation IDs, protected default child, parent restrictions and personal preference structures remain. Hiding navigation alone continues to differ from revoking access.
- Visited authorized panels remain mounted; unvisited panels are lightweight placeholders. One existing task socket drives shared invalidation. List/board/calendar use the established query client; Gantt keeps its existing fetch path and participates in the same event invalidation.
- New private task/comment entries are memory/session-bound; legacy persisted private entries are ignored and removed when accessed. No browser credential/storage system was replaced.

## Review file scope

New source/test files: `backend/app/task_calendar.py`, `backend/tests/test_task_tabs_review.py`, `frontend/test/task-query-cache.test.ts`.

Updated backend files: `backend/app/routers/tasks.py`, `backend/app/routers/comments.py`, `backend/requirements.txt`.

Updated frontend files: `frontend/pages/AllTasks.tsx`, `Tasks.tsx`, `KanbanBoard.tsx`, `GanttView.tsx`, `CalendarView.tsx`; `frontend/hooks/useTaskCache.ts`, `useTaskList.ts`, `useTaskPrefetch.ts`, `useUnsavedChanges.tsx`; `frontend/components/CreateTaskModal.tsx`; `frontend/services/mockApi.ts`; `frontend/types.ts`; `frontend/utils/taskNavigation.ts`, `taskCalendarDates.ts`; `frontend/test/task-navigation.test.ts`; and `frontend/checks/all-tasks.browser.js`.

Evidence/documentation: this report, the linked JSON/text outputs and screenshots below. Files already dirty from unrelated work remain untouched by this review.

- [Desktop All Tasks](../frontend/checks/task-tabs-review-desktop.png)
- [Desktop Gantt](../frontend/checks/task-tabs-review-gantt.png)
- [Desktop Calendar](../frontend/checks/task-tabs-review-calendar.png)
- [Tablet Calendar](../frontend/checks/task-tabs-review-tablet.png)
- [Mobile Calendar](../frontend/checks/task-tabs-review-mobile.png)

Screenshots use synthetic data. External artwork is blocked by the fixture, so missing remote logos/icons in these captures do not certify a production asset failure.

## Remaining risks and limits

- The repository is not release-green: 113 TypeScript diagnostics, 2,421 full-lint violations and four legacy collection errors remain outside this bounded review.
- No dedicated active-work timer exists here. Task view retention is tested; an active-work timer cannot receive a fabricated PASS.
- Live PostgreSQL isolation/concurrency, full-text search, production authenticated multi-user socket delivery, actual attachment storage bytes, large-tenant performance, physical touch and other browsers were not tested.
- Gantt remains the existing created/due-date timeline with range controls and dependency information; there is no editable dependency scheduler or separate planned-start engine to certify.
- Historical malformed cross-tenant relationships are not silently repaired or deleted. They should be audited through an installation's normal data-maintenance process; the reviewed task responses hide foreign members/dependencies and completion rejects inaccessible dependency links.
- The sidebar registry and workflow integration retain their existing policy meanings. The tests cover the reviewed task handlers and navigation boundaries, not an exhaustive certification of every administrative API or external integration in the application.
- No deployment or shared database migration was performed.
