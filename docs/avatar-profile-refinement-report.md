# Avatar and employee profile refinement report

Reviewed locally on 2026-10-29. **Avatar/profile checks: PASS. Repository-wide release checks: FAIL.**

No deployment, shared database migration, running-install restart, commit or publication was performed. Unrelated working-tree changes were preserved. Browser checks use intercepted fixture APIs; database checks use disposable databases. They do not certify a deployed installation.

## Issues fixed

- Closed manager bypasses for roles, employee IDs, departments, reporting relationships, private contacts and passwords. Managers cannot create privileged accounts. Admins cannot promote accounts to Owner or modify/reset Owner accounts. The global administrative dependency and unrelated module permissions remain unchanged. Directory controls now match these restrictions; ordinary manager status actions remain available.
- Removed private phone, location, timezone, reporting email and shift fields from unauthorized peer responses. Internal notes require Admin/Owner access. The shared `UserRead` serializer also protects nested identities returned by other APIs. Storage keys are never serialized. Authorized self/admin reads retain permitted contact data.
- Stopped read requests from modifying persisted legacy avatar columns. Directory reads eagerly load avatar, department and reward-claim relationships; ordinary profile GET requests no longer take row locks.
- Fixed local storage's sibling-directory path traversal check. Upload paths use server-generated names. Added bounded request streaming, including chunked requests and `/api` route aliases. Limited multipart file/field counts and retained decoded byte/pixel limits.
- Unified personal and uploaded library images through private durable storage and the same normalization/thumbnail engine. Removed the duplicate public-directory upload path, repeated image decoding and unused image helpers. Explicitly misconfigured private storage returns 503 instead of silently switching providers.
- Fixed tenant access when a library image's creator has been deleted. Immutable packaged artwork cannot be modified by tenant owners. Referenced library images return 409 on deletion. Avatar assignment and deletion lock the asset before changing references.
- Made cleanup queues immutable snapshots. Commit removes unreferenced previous variants; rollback, partial-write failure and session close remove newly staged variants. Shared pictures survive until their final user reference is removed.
- Blocked direct public access to legacy uploaded avatar files. Legacy raster reads are normalized through authenticated routes; uploaded SVG content is rejected. External avatar URLs accept only HTTP/HTTPS without embedded credentials. API image responses use private caching, `nosniff` and a restrictive content policy.
- Routed packaged artwork through the same avatar image endpoint. This works through the existing `/api` proxy without requiring a frontend `/assets` proxy. Only the ten immutable packaged SVG illustrations can be returned as SVG; user uploads remain JPEG/PNG/WebP inputs normalized to WebP.
- Removed synthetic avatar library IDs and loaded actual server assets. Kept failed crop uploads open for retry and allowed reselecting the same rejected file.
- Removed the directory's duplicate browser profile/manager model and browser-local frame selection. User and avatar response caches stay in memory and are scoped to the login; retired persisted response caches are ignored/removed. Existing user-authored legacy profile storage is not deleted or read.
- Added shared in-flight image downloads, bounded idle caching, object URL cleanup and login/logout invalidation. Image state is keyed by source/session to prevent a previous identity's photo flashing during changes. Large profile/card avatars explicitly request display variants; small consumers use thumbnails. Upload policy requests are shared.
- Centralized frame options, retained all seven existing frame IDs, bounded profile names/contact fields, rejected unknown frame values, and corrected equivalent-timezone optimistic-version comparisons.
- Fixed long designation wrapping on the employee card. Empty fields, long names/emails/bios/skills, tablet and mobile layouts were checked.

## Requested review areas

PASS below means the stated source/disposable/fixture evidence passed. External installation checks are listed separately.

| # | Review area | Result and concrete evidence |
| --- | --- | --- |
| 1 | Upload, normalization, crop, replace, remove | **PASS**: PNG/JPEG/WebP, EXIF rotation/metadata removal, multipart crop, JSON upload and legacy presigned workflow; replacement/removal checks inspect files and API reads. |
| 2 | XSS, traversal, unsafe content | **PASS**: SVG/executable/GIF/truncated/MIME-mismatched/oversize inputs rejected; legacy SVG not served; sibling traversal rejected; script-like bio rendered as text; invalid URL schemes rejected. |
| 3 | Durable storage and URLs | **PASS, local/simulated**: persisted local variants and simulated MinIO variants; canonical proxy-safe image routes, including packaged artwork; Compose media volumes validate. Live storage policy/restart persistence: **NOT RUN**. |
| 4 | Previous images/thumbnails | **PASS**: replacement, removal, rollback, session-close and partial-write tests; shared references retained; library deletion conflicts while in use. |
| 5 | Propagation across identity consumers | **PASS for shared implementation**: source audit covers Header, Settings, directory, organization/project assignments, task members/comments and chat identity consumers. Browser tests prove Header/card/Settings updates together; the shared renderer merges current-user context updates. Full real-data Project/Task workflows: **NOT RUN**. |
| 6 | No full-page refresh | **PASS**: upload, remove, bio/skills and frame changes update fixture views through context/events; saved values also survive a later navigation/refresh. |
| 7 | Desktop/tablet/mobile appearance | **PASS**: 1365px, 768px and 390px; screenshots visually inspected. Long-content cards do not overflow at tablet/mobile widths. |
| 8 | Empty fields | **PASS**: missing employee ID, designation, department, bio and skills use clean empty states; no literal null/undefined text. |
| 9 | Bio/skills persistence and validation | **PASS**: 500-character bio, 30 skills/60 characters per skill, whitespace/case deduplication, structured comma-containing skill, clear/save/conflict tests. |
| 10 | Additional Details structures | **PASS**: existing User contact, manager, shift, notes and project fields retained; existing JSON skill/project arrays reused; no parallel personal-data schema. |
| 11 | Existing role boundaries | **PASS**: self/Admin/Owner avatar rules retained; manager ordinary actions retained while privilege/private-data bypasses are closed. Wider navigation/security regressions pass. |
| 12 | Unauthorized restricted updates | **PASS**: manager attempts against self and peers for role, employee ID, department, manager, shifts, password, phone and notes return 403; self-service role injection returns 422. |
| 13 | Cross-tenant access | **PASS**: list/read/update/selection/image tests reject foreign IDs, including a foreign Owner and an orphaned tenant-default image. |
| 14 | Sensitive API fields | **PASS**: peer list, direct and employee-ID reads omit sensitive keys; nested `UserRead` serialization is private by default; self/admin reads tested. |
| 15 | Migration compatibility | **PASS, disposable**: nullable additions preserve old rows, backfill tenant ownership and tolerate repeated upgrade; Alembic has one head, `c3e5f7a9b1d2`. Live PostgreSQL upgrade: **NOT RUN**. |
| 16 | Directory regressions | **PASS**: name/employee-ID/role/department filtering, pagination, page size, details expansion, admin editing, real library selection and manager action visibility tested in browser fixtures. |
| 17 | Frame customization | **PASS**: all seven IDs remain available; selected frame persists independently through upload/removal/refresh. |
| 18 | API/image performance and caching | **PASS**: shared downloads and object URLs, failure retry, idle expiry, login-change cleanup and content-type rejection tested. Three visible profile consumers issue two image requests: display and thumbnail. |
| 19 | Duplicate/unused logic | **PASS**: one storage/normalization/crop/assignment engine; synthetic library data, duplicate browser profiles/frame state and unused image helpers removed. |
| 20 | Lint/typecheck/tests/build | **FAIL at repository level**: scoped checks and production build pass; full lint/typecheck/backend collection and wider Sidebar Management browser failures remain, as detailed below. |

## Executed checks

| Check | Result |
| --- | --- |
| Combined backend avatar/profile + Settings/security/navigation/migration regression command | **PASS: 167 tests**, including 60 avatar/profile tests. |
| Frontend `npm test` | **PASS: 30 tests**. |
| Avatar/profile Playwright component checks | **PASS: 18 checks**, zero uncaught component errors. |
| Wider Settings browser regression | **70 PASS / 7 FAIL**. Failures concern Sidebar Management dirty drafts, drag/reorder, nested editor controls and reset/save; those modules were not changed by this review. |
| Full configured Ruff rules on the eight scoped backend/test files | **PASS**. |
| Ruff syntax/undefined-name checks on `schemas.py` and `main.py` | **PASS**. |
| Repository-wide `python -m ruff check backend --statistics` | **FAIL: 2,432 violations** in the current working tree. No broad automatic lint rewrite was applied. |
| Frontend `npx tsc --noEmit --pretty false` | **FAIL: 118 diagnostics**. Comparison with the earlier snapshot is identical after ignoring shifted line numbers. Examples include Ballpit, seed data and existing missing ticket/level types. |
| Frontend ESLint | **NOT RUN**: this checkout has no configured ESLint script/package. |
| Production `npm run build` | **PASS**; existing large-chunk/Lottie dependency warnings remain. |
| Entire backend test directory | **FAIL during collection** in four older modules: `test_generate_token`, `test_oauth2_server`, `test_task_list`, `test_ticket_tenant_permissions`. Their SQLite schema creation encounters PostgreSQL `to_tsvector`. |
| Full-suite isolation/data preservation | **PASS**: temporary cwd, outbound sockets blocked; SHA-256 hashes of the three workspace test databases were unchanged. |
| Both source Compose configurations, Alembic head, `git diff --check` | **PASS**. Compose notes the existing unset `PRESENCE_URL` variable. |
| Deployment, installed-database migration, live MinIO authorization, live PostgreSQL concurrency | **NOT RUN**. |

The combined backend command uses these files under `backend/tests`: `test_employee_avatar_profile.py`, `test_settings_security.py`, `test_navigation_policy.py`, `test_navigation_readiness.py`, `test_navigation_socket_auth.py`, `test_navigation_sockets.py`, and `test_api_settings_migration.py`. It runs with `VEE_DATABASE_URL=sqlite:///:memory:`, `VEE_BOOTSTRAP_SCHEMA=false`, `PYTHONDONTWRITEBYTECODE=1`, `-q -p no:cacheprovider --disable-warnings`; individual fixtures own their disposable databases.

Scoped Ruff files: `avatar_utils.py`, `avatar_http.py`, `routers/avatars.py`, `routers/users.py`, `profile_validation.py`, `services/minio_media_service.py`, `storage/local.py`, and `tests/test_employee_avatar_profile.py`.

## Saved evidence

- [Avatar/profile browser results](../frontend/checks/avatar-refinement-results.json)
- [Wider Settings browser results, including failures](../frontend/checks/settings-refinement-results.json)
- [Desktop card](../frontend/checks/avatar-refinement-desktop.png), [tablet card](../frontend/checks/avatar-refinement-tablet.png), [mobile card](../frontend/checks/avatar-refinement-mobile.png)
- [Backend regression tests](../backend/tests/test_employee_avatar_profile.py), [frontend cache tests](../frontend/test/avatar-image-cache.test.ts), [avatar identity tests](../frontend/test/user-avatar.test.ts)
- [Reproducible browser check](../frontend/checks/avatar-profile.browser.js) against the isolated Vite fixture on port 6321.

## Installation acceptance limits

Actual MinIO bucket policy must deny public reads of both staged and normalized private avatar objects. Existing historical public object URLs cannot be revoked by application-source changes alone. No bucket policy was changed or certified here.

Before any later installation update, retain database/media backups, apply the additive migration through that installation's normal migration process, and verify actual media persistence and tenant authorization on PostgreSQL/MinIO. Cleanup failures after a successful commit are logged for operator follow-up; no background orphan-reconciliation service was introduced.

The repository-wide failures above prevent an unconditional release PASS. They remain visible because resolving unrelated modules would exceed this review's scope.
