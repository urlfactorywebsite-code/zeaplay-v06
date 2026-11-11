# Sidebar Management implementation and regression review

Historical implementation evidence. The subsequent [production-readiness review](sidebar-production-readiness.md) supersedes its API role policy, credential tenant scoping, migration requirements and results. API administration now permits Owner/Admin and rejects User/Manager; Master Control and access-policy changes remain Owner-only.

Local source review, 2026-10-29. No deployment, shared database migration, environment-file change, production infrastructure change, or external delivery was performed. The earlier six-tab review is recorded separately in `settings-navigation.md`.

## Architecture and behavior

`backend/app/navigation_registry.py` is the authoritative page registry. Its 22 stable IDs cover the 11 desktop entries, existing mobile Points/Templates/Levels shortcuts, header Chat entry, and all seven Settings tabs. Clients receive safe registry metadata and effective access from `GET /navigation` (also `/api/navigation`). There are no credentials in this response. Settings route manifests retain their existing permission ceilings; a regression test checks their agreement with the server registry.

Desktop, collapsed sidebar, mobile Pages, Settings tabs, header Chat, and existing achievement sub-tabs consume the effective policy. Existing artwork, sidebar classes, hash URLs, six original Settings implementations, account/logout behavior, and legacy redirects are retained. Case variants, encoded paths, trailing slashes, and achievement query-tab aliases are evaluated before rendering a page. Denied pages leave the user at protected Profile with a disabled/forbidden explanation.

There was no popup/editor in this checkout. The established controlled Zea sidebar editor and preference utility from the sibling `ideashop-zeaplay-v5` checkout were adapted into one full-page editor here; no second editor or unlock trigger was added. It supports drag handles, keyboard move buttons, rename, search, main/settings groups, save/discard/reset, dirty navigation/unload warnings, high-impact confirmation, protected controls, and inline status messages. Reset is a draft until Save.

| Setting | Scope and persistence |
| --- | --- |
| Enabled, hidden, allowed roles | Organization-wide, server persisted, tenant derived from authenticated database user |
| Names and ordering (including Settings tabs) | Personal to tenant/account/browser, `zea.sidebar.v2:<tenant>:<user>` |
| Existing permissions | Existing database roles, route ceilings and operation/object dependencies; never granted by a checkbox |

Legacy `zea.sidebar.v1:<tenant>:<user>` preferences migrate once when no v2 preference exists. Route keys become stable IDs; names, ordering, unknown future IDs, and the original legacy value are retained. Other accounts/tenants and unscoped storage are not imported. Browser storage failure is reported on Save; a successful global save is explicitly distinguished from a failed personal save.

## Access decisions and recovery

- Owner and Admin can open Sidebar Management. Owner can change availability and narrow role access. Admin can hide links and customize personal layout, but cannot enable/disable modules or change access policies. Manager/User cannot save policies.
- API and Master Control remain Owner-only because that is this checkout's existing route ceiling. Admin is deliberately not granted API access by the new role selector. Logs retains Manager/Admin/Owner access; Profile, Support and Media retain member access.
- `hidden` removes navigation only. Independently authorized direct access remains allowed.
- `enabled=false` blocks module access without deleting its route or data. A role outside the existing ceiling or configured allowed roles receives `forbidden`. Enabled state and parent state are evaluated independently of navigation hiding.
- Settings parent, Profile, and Sidebar Management cannot be disabled, hidden, or have their permitted roles narrowed. Every legitimate Admin/Owner retains recovery access.
- HTTP policy enforcement runs on both root and `/api` aliases, before relevant resource handlers, in addition to their existing authorization. No client page header, tenant, or role is trusted. Missing policy storage fails closed with HTTP 503.
- Task data shared by Tasks/Kanban/Calendar/Gantt/Dashboard remains accessible when another authorized view needs it. Dedicated calendar/kanban endpoints are individually gated. Shared config/points/level reads retain independently established consumers and endpoint permissions; page policies do not create new permission grants. Browser-only Templates has no new server data API.
- Existing task, chat, and ticket sockets validate policy at connection; incoming chat/ticket actions and outgoing module payloads recheck policy and active tenant identity. Revoked sockets close before payload transmission. Tenant policy audit entries are filtered by tenant in the existing Logs query.

## Database and APIs

The existing global FeatureFlag/config tables are not tenant-scoped and do not provide versioned atomic policy storage. Additive Alembic revision `a8d6e4f2c0b1` (after `9c8d7e6f5a4b`) creates one `navigation_policies` row per tenant: JSON rules, integer version, updated_by and updated_at. No existing application records are migrated or deleted.

`PUT /navigation` accepts exactly `{version, pages}` with every registered ID and only strict booleans and existing role IDs. It rejects unknown/duplicate roles, permission expansion, protected-page changes and unauthorized operations. A version-qualified UPDATE or unique first INSERT prevents lost updates; conflicts return 409. Policy and the existing AuditLog record commit in one transaction. Tests exercise actual overlapping saves and rollback on audit failure.

Page switches were removed from Master Control; it links to Sidebar Management. Legacy `page.*` FeatureFlag values remain stored for compatibility but cannot be changed through that API and do not become a second policy store.

Support now posts to authenticated `POST /support` (also `/api/support`), which checks policy and forwards the existing payload to the fixed existing webhook. Sender ID comes from authentication; upstream responses and errors are not exposed. Attachment size is limited to 10 MB in the form and a corresponding server payload bound. This protects the application endpoint; it does not configure access control on the external webhook itself.

Hardcoded storage credential defaults were removed from backend configuration. Storage credentials must come from server environment configuration. Existing provider gateway/redaction and private-cache protections remain. No secret values were added to browser preferences or global navigation policy.

The migration was tested only in disposable SQLite storage, with PostgreSQL DDL compilation separately verified. It was **not applied to the running installation**. Before serving this release, the operator must back up the intended database and apply the normal Alembic upgrade through `a8d6e4f2c0b1`; no production command was executed here.

## Synchronization

The existing realtime channels are task/chat domain streams rather than a general reliable cross-worker configuration bus. Policy refresh runs on navigation, page refresh, focus/visibility return, and every 30 seconds while visible. Successful saves refresh the current session without a reload; browser storage events synchronize personal preferences between same-origin tabs. In-flight older responses cannot overwrite newer navigation validation. An existing draft is kept mounted but hidden/inert during a transient policy-read failure. Recovery requires a successful retry.

This is revalidation, **not immediate cross-session realtime synchronization**. Server API/socket checks enforce current stored policy independently of browser polling.

## Files changed for this extension

Created:

- Backend registry, HTTP guard, `routers/navigation.py`, `routers/support.py`, `services/navigation.py`, `services/navigation_sockets.py`, migration, `test_navigation_policy.py`, `test_navigation_sockets.py`, and `checks/run_legacy_regressions.py`.
- Frontend `types/navigation.ts`, `utils/sidebarPreferences.ts`, `utils/navigationIcons.ts`, `hooks/useNavigation.tsx`, `components/SidebarEditor.tsx`, `pages/SidebarManagement.tsx`, `test/sidebar-preferences.test.ts`, safe browser registry fixture, and this report.

Updated:

- Backend models, app registration, feature-flag update validation, navigation audit scope in Logs, task/chat/ticket sockets, storage credential defaults.
- Frontend App, ProtectedRoute, Sidebar, Layout, Header, Settings, Settings registry, MasterControl, Achievements, Support form, API service, Settings unit tests and saved browser checks/results.

Unrelated pre-existing work was preserved. No dependencies were added.

## Verification

All backend checks used `VEE_DATABASE_URL=sqlite:///:memory:`, `VEE_ENVIRONMENT=test`, and `PYTHONDONTWRITEBYTECODE=1`. Policy transaction tests create private pytest temporary databases.

| Command/check | Exact result |
| --- | --- |
| `npm test` from frontend | PASS, exit 0; 21 tests |
| `backend\venv\Scripts\python.exe -m pytest backend/tests/test_navigation_policy.py backend/tests/test_navigation_sockets.py backend/tests/test_settings_security.py -q` | PASS, exit 0; 71 tests, 21 deprecation warnings |
| `backend\venv\Scripts\python.exe -m pytest backend/tests/test_time_bonus.py -q` | PASS, exit 0; 18 existing tests |
| `frontend/checks/settings-navigation.browser.js` via Playwright | PASS; 78 checks, zero failures, zero uncaught browser errors; details in `frontend/checks/settings-navigation-results.json` |
| `npm run build` | PASS, exit 0; existing Lottie eval / large-chunk warnings |
| `node checks/check-provider-credentials.mjs` | PASS, exit 0; 41 production artifacts, zero provider-credential matches |
| `npx tsc --noEmit --pretty false` | FAIL, exit 2; 118 pre-existing diagnostics, none in new navigation implementation |
| `npm run lint` | FAIL, exit 1; Missing script: lint |
| `npx tsc --noEmit --pretty false --noUnusedLocals --noUnusedParameters` | Global failure, exit 2; 216 existing diagnostics; no unused-symbol diagnostics in reviewed navigation files |
| `backend\venv\Scripts\python.exe backend/checks/run_legacy_regressions.py` | FAIL, exit 2; four collection errors: SQLite lacks PostgreSQL `to_tsvector` used by the existing generated task column; disposable cwd and blocked outbound sockets |
| `git diff --check` | PASS, exit 0; Git's existing LF/CRLF conversion warnings remain |

The saved browser suite mocks all APIs and outbound services. Backend tests exercise real transactions and policy guards, fixture authentication, fixed-destination forwarding with mocked transport, socket revocation, tenant isolation, actual overlapping saves, audit atomicity, and migration DDL. They do not certify a production JWT/session, PostgreSQL execution, real email/OAuth/storage/AI delivery, or performance under load. Legacy integration collection is blocked before those tests execute; no claim is made that the entire application suite passed.

Overall release certification remains **FAIL** until the existing TypeScript/lint gates and legacy integration harness are repaired, the migration is applied in an approved environment, and live integrations are checked there. The implemented navigation feature has separate local test evidence; production infrastructure remains untouched.

Desktop and 390px screenshots were visually inspected. A final resize check confirmed the selected management tab remains visible at 390px without page overflow; the garbled mobile menu glyph was replaced with the existing Lucide Menu icon. Original external artwork was replaced with harmless fixtures during browser checks, so external image delivery was not certified.
