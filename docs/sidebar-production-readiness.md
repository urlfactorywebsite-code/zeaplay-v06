# Sidebar Management production-readiness validation

2026-10-29. **Critical feature security: PASS locally. Overall production readiness: FAIL.** No deployment, shared-database migration, production infrastructure change, environment-file change, external delivery or credential rotation was performed.

## Security findings fixed

- **Page and endpoint permissions disagreed.** API administration now uses an explicit Owner/Admin capability shared by the backend registry and configuration dependencies. The old generic admin helper also admitted Managers, and provider metadata was readable by ordinary Users. User/Manager configuration requests now return 403. Admin already had backend configuration privileges; API page visibility now agrees. Master Control and availability/access-policy changes remain Owner-only. Admin may hide navigation and manage personal layout.
- **Credential configuration and webhook lookups were global.** Provider, SMTP, email-template and OAuth ownership is tenant-scoped. Queries, mutation, rotation, SMTP selection and server AI key lookup use authenticated tenant identity. Webhook creation, ID lookup, logs and delivery queueing are scoped; unscoped events cannot fan out across tenants. Tests use synthetic webhook data. Configuration audits are tenant-scoped; unattributed historical configuration audits remain stored but are hidden from tenant queries.
- **Frontend Settings permissions duplicated the server.** Its manifest now contains route identities only. Server metadata provides labels, permission ceilings and effective access. API and navigation administration are separate capabilities. Ticket role dependencies/socket checks use database roles, preventing stale JWT role claims from retaining privileges after demotion.
- **Real CRUD exposed defects hidden by mocks.** OAuth integer IDs now serialize to the existing string wire contract. Webhook route IDs are parsed as UUIDs before database lookup. Foreign-tenant mutations return 404.
- **Failure cases needed safeguards.** Read-only storage preserves readable legacy preferences. Malformed/incomplete navigation responses and corrupt stored policies fail closed. Audit failure rolls back policy and returns 503; genuine concurrent-save conflicts return 409.
- **Transport behavior needed coverage.** The global HTTP dependency now accepts HTTPConnection and leaves WebSocket handshakes to their existing authenticated guards. Connected ticket sockets recheck current object access and module policy. Logout captures its Authorization header before browser tokens are cleared.

## Requested end-to-end scenario

The readiness browser suite used production authentication, policy and configuration routers with real JWTs and database writes in an isolated local application. Those endpoints were not mocked. Unrelated page data and external services were isolated fixtures. Evidence: [sidebar-readiness-results.json](../frontend/checks/sidebar-readiness-results.json).

| Scenario | Result |
| --- | --- |
| Owner enables Settings | PASS: Settings is a protected, permanently enabled parent; the saved authenticated policy was checked. Its switch cannot be disabled. |
| Owner enables API and selects only Owner/Admin | PASS: actual editor Save persisted `enabled=true` and exactly `admin, owner`; Manager/User options were unavailable. |
| Owner logs out/in and sees API | PASS: real login/logout and persisted policy; logout endpoint returned 204. |
| Admin logs in and sees API | PASS: existing backend configuration capability permits it; configuration requests returned 200. |
| User/Manager do not see API | PASS: both actual logins had no API tab. |
| User manually opens `/settings/api` | PASS: protected Profile displayed an access-denied alert. Hash URLs are SPA navigation; actual configuration data endpoints returned HTTP 403. |
| User attempts provider/SMTP/OAuth endpoints | PASS: 403, without fixture credentials. Root and `/api` aliases are covered by integration tests. |
| Owner disables API | PASS: all four roles lost the tab and direct configuration requests returned 403. |
| Owner re-enables API | PASS: only Owner/Admin regained it after reload/login. |
| New browser and other tenant | PASS: a fresh browser saw global policy without copying personal storage; Tenant B remained enabled while Tenant A disabled API. |

Result: **10 scenario groups passed, zero failures, zero uncaught errors.** The wider mocked browser regression suite passed **77 checks, zero failures, zero uncaught errors**, covering original Settings functionality, navigation/history, legacy/encoded/case/trailing-slash URLs, unsaved forms, drag/arrow ordering, nested preferences, confirmations, conflicts and responsive/collapsed layouts. The count changed from 78 because Admin API denial is no longer an expected scenario. Evidence: [settings-navigation-results.json](../frontend/checks/settings-navigation-results.json).

## Critical security matrix

Test names below refer to [test_navigation_readiness.py](../backend/tests/test_navigation_readiness.py), [test_navigation_policy.py](../backend/tests/test_navigation_policy.py), [test_navigation_socket_auth.py](../backend/tests/test_navigation_socket_auth.py), [test_navigation_sockets.py](../backend/tests/test_navigation_sockets.py), [test_api_settings_migration.py](../backend/tests/test_api_settings_migration.py), and the frontend test/browser files.

| Requirement | Status | Evidence |
| --- | --- | --- |
| 1. Visibility is separate from authorization | PASS | `test_hidden_vs_forbidden_roles_are_independent_of_visibility`: hidden Admin API remains independently accessible; removing its role makes the endpoint return 403. Operation dependencies remain authoritative. |
| 2. Owner/Admin authority stays bounded | PASS | `test_admin_cannot_bypass_owner_policy_controls_or_protection`: Admin may hide links but cannot change availability or allowed roles. Unrelated Manager administration privileges remain unchanged. |
| 3. User/Manager cannot bypass API guards | PASS | `test_members_cannot_read_configuration_through_either_api_alias`, real browser direct-route checks, forged-role/wrong-tenant tests, and database-role demotion test. |
| 4. Nested tabs inherit parent state and independent ceilings | PASS | `test_parent_disable_blocks_child_and_hidden_parent_only_hides_navigation`, protected-parent validation, server registry role tests and frontend alternate-route tests. Parent visibility never grants child access. |
| 5. Recovery administrators cannot be locked out | PASS | Settings/Profile/Sidebar Management disable, hide and role-narrowing rejection matrix. Storage corruption/unavailability still requires operator repair; recovery never bypasses authentication. |
| 6. Tenant isolation | PASS | Real-login configuration/policy isolation; SMTP/OAuth guessed-ID 404s; webhook/log/queue tests; audit isolation; signed wrong-tenant rejection; migration single/multi-tenant fixtures. |
| 7. Concurrent saves do not overwrite silently | PASS | `test_real_concurrent_authenticated_saves_only_commit_one_version` on SQLite/PostgreSQL: overlapping first inserts and existing-row updates each produce one 200 and one 409. Policy and audit commit together. |
| 8. Personal preferences survive migration | PASS | Legacy source/order/label preservation, tenant/account isolation, read-only storage test, and browser save/reload checks. Only exact tenant/account v1 keys migrate automatically; ambiguous/unscoped keys remain untouched. |
| 9. Global persistence survives sessions and browsers | PASS | Real logout/login, refresh, new-browser scenario and independent database-session reads. Logout never deletes server policy. |
| 10. Policy changes preserve data and credentials | PASS | `test_switching_and_resetting_policies_does_not_change_config_data`, preserved migration IDs/secrets, atomic-audit rollback, and User/Manager 403/redaction assertions. Navigation PUT accepts rules only. |
| 11. Updates are authenticated and tenant-scoped | PASS for implemented revalidation | JWT-protected GET/PUT, wrong-tenant rejection, socket authentication/tenant/escalation tests and active-socket 1008 closure after disable. No configuration WebSocket was added: refresh runs on navigation, focus/visibility and every 30 seconds. Immediate push synchronization is not claimed. |
| 12. Reset Defaults cannot bypass security | PASS | Editor reset/confirmation test, protected-page matrix, invalid/expanded-role rejection and actual API ceiling tests. Reset remains a draft and uses the same server validation as every save. |

## Database and compatibility

`a8d6e4f2c0b1` creates tenant policy storage. New revision `b2c4d6e8f0a2` adds nullable tenant ownership to private configuration tables, tenant uniqueness for provider/primary SMTP and composite tenant/template-type uniqueness. Both revisions were executed against disposable PostgreSQL 15 schemas. The new revision also handles fresh installs and tables already created by application bootstrap, advancing singleton sequences past preserved IDs.

Legacy records are not deleted or copied across organizations. Exactly one tenant permits an unambiguous automatic backfill. Multi-tenant unowned credential/template records remain stored but inaccessible until an operator verifies ownership. Existing default-tenant webhook records also need review if their stored tenant does not match their workspace. Downgrade refuses to collapse tenant-owned secrets into a shared store; use a verified backup or explicit reconciliation.

**Neither migration was applied to the running installation.** Back up and review ownership before an approved release. Existing URLs and account-scoped browser preferences remain compatible. Server environment provider pools remain operator-controlled and are not exposed in navigation metadata.

## Commands and results

Frontend working directory: `frontend/`.

| Command | Result |
| --- | --- |
| `npm test` | PASS, exit 0: 22 tests |
| `npm run lint` | FAIL, exit 1: Missing script: lint |
| `npx tsc --noEmit --pretty false` | FAIL, exit 2: 118 existing diagnostics; none in reviewed navigation implementation |
| `npx tsc --noEmit --pretty false --noUnusedLocals --noUnusedParameters` | FAIL globally, exit 2: 216 diagnostics; no reviewed navigation unused-symbol diagnostics |
| `npm run build` | PASS, exit 0; 33.24 seconds; existing Lottie eval/large-chunk warnings |
| `node checks/check-provider-credentials.mjs` | PASS, exit 0: 41 artifacts, zero provider credential matches |
| `git diff --check` from root | PASS, exit 0 |

Backend commands ran from repository root with `VEE_DATABASE_URL=sqlite:///:memory:`, `VEE_ENVIRONMENT=test`, and `PYTHONDONTWRITEBYTECODE=1`. Each transaction test used a private temporary database.

```powershell
.\backend\venv\Scripts\python.exe -m pytest backend/tests/test_navigation_policy.py backend/tests/test_navigation_sockets.py backend/tests/test_settings_security.py backend/tests/test_navigation_readiness.py backend/tests/test_navigation_socket_auth.py backend/tests/test_api_settings_migration.py backend/tests/test_time_bonus.py -q --tb=short
```

PASS, exit 0: **125 tests**, 612 existing deprecation warnings, 51.44 seconds.

For the PostgreSQL profile, `ZEA_REVIEW_POSTGRES_URL` pointed only at a new Docker Desktop PostgreSQL 15 fixture, `zea_review`, on a loopback-only ephemeral port. Every test created and removed a private schema; the fixture rejects a PostgreSQL target outside that local review database.

```powershell
.\backend\venv\Scripts\python.exe -m pytest backend/tests/test_api_settings_migration.py backend/tests/test_navigation_readiness.py backend/tests/test_navigation_socket_auth.py -q --tb=short
```

PASS, exit 0: **36 checks**, 593 deprecation warnings, 65.06 seconds. This profile contains 33 live PostgreSQL migration/auth/transaction/socket checks, two SQLite fresh/bootstrap cases and one offline PostgreSQL DDL case.

```powershell
.\backend\venv\Scripts\python.exe backend/checks/run_legacy_regressions.py
```

FAIL, exit 2: four collection errors, `sqlite3.OperationalError: no such function: to_tsvector`, in the existing legacy integration harness. Its runner uses a disposable directory and blocks external sockets. Those tests did not execute and are not counted as passes.

Browser reproduction: start `npm run dev -- --host 127.0.0.1 --port 6319 --strictPort` and `backend/checks/serve_navigation_fixture.py` at 6321 with the isolated test environment above. Pass the saved `.browser.js` file to Playwright `browser_run_code_unsafe`. The broad suite mocks services; the readiness suite forwards auth/policy/configuration only to the disposable local backend.

## Files and release decision

New review files: backend capability constants, tenant-configuration migration, disposable real-router app/server, authenticated readiness/socket/migration tests; frontend access-response validator and tests, real-backend browser scenario/results; this report. Existing registry, dependencies, HTTP/socket guards, config/AI/mail/webhook queries, audit scope, Settings route manifest, preference migration, logout and related tests were updated. Pre-existing dirty work was preserved; no dependencies were added.

**FAIL for production release.** Critical feature checks pass locally, but TypeScript, lint and the legacy integration harness are not green. Migrations/ambiguous ownership mapping remain pending. Live SMTP/OAuth/storage/AI delivery, production startup/worker topology, destructive owner operations and performance under load were not certified. The fixture uses production routers/guards without production startup seeds or workers; it does not certify every existing business module.
