# Centralized All Tasks implementation and validation

Historical implementation snapshot. The subsequent [All Tasks tabs validation report](all-tasks-tabs-validation-report.md) records the current fixes, shared query architecture, timezone contract and latest validation evidence.

Review date: 2026-10-29. Scope: this local checkout only. No deployment, commit, shared database migration, or production configuration change was performed. Existing unrelated dirty work was preserved.

## Result

The task module now has one sidebar entry and four route-backed tabs inside All Tasks. Local task interaction checks pass. The repository-wide release gate remains **FAIL** because existing TypeScript, backend lint, and backend test-collection failures remain outside this refactor.

## Implemented behavior

- Added the shared All Tasks heading, requested subtitle, icons, horizontal accessible tabs, keyboard navigation, and responsive tab scrolling.
- Reused the existing task list/grid, Kanban board, Gantt timeline, Calendar, task creation form, and task details. Removed the duplicate inline Kanban renderer, its requests, scrolling handlers, and state from the list page.
- Removed standalone task-view navigation through the authoritative registry. The existing All Tasks sidebar link stays highlighted on all four task routes. No sidebar submenu was introduced.
- Added an All Tasks Tabs group to Sidebar Management, using its existing labels, ordering, personal preferences, visibility, access controls, and confirmation/save behavior.
- Kept backend task API paths and task business routers unchanged. No schema or task relationship changes were needed.
- Fixed denied Kanban transitions leaving an optimistic card in the wrong column, Gantt's hidden Unassigned filter caused by a property-name mismatch, Calendar day keys shifting at local midnight, a day drawer covering Task Details, and tablet Calendar filter clipping.

## Routes and compatibility

| Existing route | Canonical route | Behavior |
| --- | --- | --- |
| `/tasks` | `/tasks` | All Tasks list/grid; canonical entry retained |
| `/kanban` | `/tasks/kanban` | Replace redirect |
| `/gantt` | `/tasks/gantt` | Replace redirect |
| `/calendar` | `/tasks/calendar` | Replace redirect |

These are hash-router paths, for example `/#/tasks/calendar`. Redirects retain query parameters, hash fragments and router state using the existing redirect component. Tabs preserve queries and history; refresh, Back and Forward select the route's tab. Unknown task children show Not Found.

## State, filters and loading

`AllTasks` owns a lazy, retained panel for each visited authorized view. Unvisited views do not fetch data. Switching tabs hides/inerts inactive panels and pauses their queries without discarding component state. Chart layout receives the existing resize signal when activated. Account, tenant or role changes reset the module identity. Navigation is validated before a new view mounts; a temporary policy error hides retained panels and offers Retry.

The shared URL contract covers `status`, `priority`, `assignee`, `team`, `due`, `created`, `quick`, and `search` where each existing view supports them. The established application search remains in use. URL updates retain unrelated parameters and use replace history for filter edits; tab changes use normal history. Gantt's Unassigned mode uses the separate `ganttUnassigned` parameter so other views never receive its sentinel as an employee ID. Range chips, pagination and other view-specific state retain their existing behavior. No new project filter or scheduling semantics were invented.

The existing list LRU and React Query caches remain in use. Task/private-user cache entries are session-bound in memory; legacy persisted task entries are ignored. Task identity entry clears old task caches. Late cached task/user responses are rejected if the account token changed. Kanban and Calendar share their user metadata query. React Query invalidation is centralized rather than repeated by each view.

## Realtime and permissions

One `useTaskWebSocket` instance lives in the task module. Tab changes do not reconnect it. It retains the existing authenticated server endpoint, heartbeat and reconnect behavior. Successful existing task mutations and incoming task events invalidate task caches through one shared event; list and Gantt refresh through their existing fetch paths, and Kanban/Calendar use React Query. Inactive views refresh when activated. The open Calendar day query also participates in invalidation. Relative API URLs now resolve correctly for the socket, and cleanup prevents reconnecting a disposed socket.

Existing registry IDs `tasks`, `kanban`, `gantt`, and `calendar` and their saved policy rules are retained. New protected `tasks.list` is the default child. Gantt retains its Manager/Admin/Owner ceiling; other views retain their previous role ceilings. Parent restrictions propagate to every child. The default child cannot independently be disabled, hidden or role-narrowed; the existing parent policy can still restrict the module. Hidden-only pages retain the existing direct-access semantics; disabled/forbidden pages are blocked before view data loads. Backend operation permissions and tenant-scoped socket checks remain independently enforced. Old policy JSON loads without a database migration.

## Calendar and existing capability limits

This checkout already had a full-page `CalendarView`; the inspected task list had a Date Range filter popover rather than a Calendar navigation popup. The full Calendar is now inside its route-backed tab. The Date Range filtering control is retained. Calendar month/week/day navigation, existing scheduling APIs, colors, date details, and Task Details are reused. Civil grid dates no longer shift through UTC serialization; task grouping still follows the existing server UTC-day contract. No profile-timezone scheduling overhaul was introduced.

The existing Gantt provides a CSS timeline and 30/60/90-day/All Time range controls. There was no editable dependency/resize/zoom engine to relocate. No separate ActiveWork provider or active-work timer module exists in this checkout. Existing absolute due timestamps and retained view state were preserved; a dedicated active-work timer scenario therefore could not be executed.

## Executed validation

| Check | Result and evidence |
| --- | --- |
| Focused backend integration/security/migration regressions | **PASS: 174 tests**, including real disposable SQLite policy transactions, old policy compatibility, protected task child rules, parent restriction inheritance, Gantt ceiling, and existing tenant/socket tests |
| Frontend `npm test` | **PASS: 35 tests**; five task navigation/date tests plus existing identity, Settings and preference tests |
| Task Playwright interaction checks | **PASS: 17 groups**, zero uncaught errors; real components with intercepted APIs and controlled task socket |
| Wider Settings Playwright regression | **PASS: 77 groups**, zero uncaught errors, including labels/order, dirty drafts, drag/reorder, policy confirmations, reset/save, role restrictions and mobile editor controls |
| Production `npm run build` | **PASS**; existing large-chunk/Lottie warnings remain |
| Full Ruff on changed registry and navigation tests | **PASS** |
| Ruff `E9,F,I` on task socket | **PASS**; existing broad exception handling remains under the full lint rules |
| Repository-wide `python -m ruff check backend --statistics` | **FAIL: 2,423 violations**; no unrelated bulk rewrite applied |
| Frontend `npx tsc --noEmit --pretty false` | **FAIL: 113 existing diagnostics**, down from 118; normalized diagnostic comparison shows zero introduced signatures and five removed task/Gantt errors |
| Frontend ESLint | **NOT RUN**: no configured ESLint package/script in this checkout |
| Entire backend test directory, isolated temporary cwd | **FAIL during collection** in four legacy SQLite modules because PostgreSQL `to_tsvector` is unavailable |
| Workspace test database preservation | **PASS**: SHA-256 hashes of all three existing test databases unchanged before/after isolated verification |
| `git diff --check` | **PASS** |
| Dedicated active-work timer, live PostgreSQL workflows, multi-user server realtime, physical touch and cross-browser behavior | **NOT RUN** |
| Deployment and installed-database migration | **NOT RUN**, as requested |

Browser evidence covers the single sidebar link/tab order, lazy loading, existing creation POST and edit PATCH, Kanban status PATCH and 403 rollback in the visible board, Gantt controls and its isolated Unassigned filter, Calendar task/day navigation, keyboard focus/activation, refresh/history/legacy routes, shared filter retention and retained DOM nodes, one socket across switches, update propagation to all four visited views, role/disabled direct-link rejection, hidden-page compatibility, Sidebar Management grouping/protection, 390px/768px layouts and unclipped Calendar controls, and invalid child handling.

The full backend collection failures are `test_generate_token.py`, `test_oauth2_server.py`, `test_task_list.py`, and `test_ticket_tenant_permissions.py`. That run used a temporary directory with outbound sockets blocked; no shared database was opened. Browser mutations used synthetic fixture data, not a live backend. They prove UI/API contracts and cache behavior, not production delivery or complete task workflow certification.

Backend regression command, from the repository root:

```powershell
$env:VEE_DATABASE_URL='sqlite:///:memory:'
$env:VEE_BOOTSTRAP_SCHEMA='false'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest backend/tests/test_employee_avatar_profile.py backend/tests/test_settings_security.py backend/tests/test_navigation_policy.py backend/tests/test_navigation_readiness.py backend/tests/test_navigation_socket_auth.py backend/tests/test_navigation_sockets.py backend/tests/test_api_settings_migration.py -q -p no:cacheprovider --disable-warnings
```

Frontend checks run from `frontend`: `npm test`, `npx tsc --noEmit --pretty false`, and `npm run build`. To reproduce browser checks, start a local Vite fixture on port 6322 with both API base variables set to `/api`, then invoke `verifyAllTasks(page)` from the checked-in browser script in a fresh Playwright browser context. APIs and the socket are intercepted; external integrations are blocked.

## Files changed by this task

Some files were already dirty or untracked on entry. This list describes this task's edits, not every existing workspace change.

New source/tests: `frontend/pages/AllTasks.tsx`, `frontend/hooks/useTaskView.tsx`, `frontend/utils/taskNavigation.ts`, `frontend/utils/taskEvents.ts`, `frontend/utils/taskCalendarDates.ts`, `frontend/test/task-navigation.test.ts`, and `frontend/checks/all-tasks.browser.js`.

Updated frontend source: `frontend/App.tsx`, `frontend/types/navigation.ts`, `frontend/utils/navigationAccess.ts`, `frontend/utils/sidebarPreferences.ts`, `frontend/components/SidebarEditor.tsx`, `frontend/hooks/useTaskCache.ts`, `frontend/hooks/useTaskWebSocket.ts`, `frontend/services/mockApi.ts`, and the existing `Tasks.tsx`, `KanbanBoard.tsx`, `GanttView.tsx`, and `CalendarView.tsx` pages.

Updated backend source/tests: `backend/app/navigation_registry.py`, `backend/app/ws/tasks.py`, and `backend/tests/test_navigation_policy.py`. Updated metadata fixtures: `frontend/checks/navigation-registry.fixture.json` and the embedded registry in `frontend/checks/settings-navigation.browser.js`. No task router, model, migration or Compose configuration was changed by this task.

Evidence and documentation: this report, the JSON results below, and four screenshots. Screenshots use controlled API data; externally blocked artwork appears as missing images in this fixture and was not rewritten by this refactor.

- [Task browser results](../frontend/checks/all-tasks-results.json)
- [Check summary and unchanged database hashes](../frontend/checks/all-tasks-verification.json)
- [Settings/Sidebar Management regression results](../frontend/checks/all-tasks-settings-regression.json)
- [Desktop All Tasks](../frontend/checks/all-tasks-desktop.png)
- [Desktop Gantt](../frontend/checks/all-tasks-gantt.png)
- [Tablet Calendar](../frontend/checks/all-tasks-tablet.png)
- [Mobile Calendar](../frontend/checks/all-tasks-mobile.png)

## Remaining release limits

The existing repository-wide failures prevent a clean release PASS. Live PostgreSQL task permissions/concurrency, actual authenticated socket delivery across users, large-tenant chart performance, and physical touch interaction still require installation-level verification. The final 77-group Settings/Sidebar Management run passes with the current registry fixture; this supersedes the older fixture run's failures recorded in the separate avatar review. No deployment was attempted.
