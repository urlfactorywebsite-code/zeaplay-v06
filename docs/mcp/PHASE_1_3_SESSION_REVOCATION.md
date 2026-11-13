# Phase 1.3: durable authentication sessions and revocation

Date: **11 November 2026, Asia/Calcutta**. Reviewed checkout: `b6a220a` plus the preserved Phase 1.1/1.2 working changes. **Implemented and tested locally with disposable PostgreSQL. No deployment or migration of an existing database was performed. No MCP or management UI was implemented.**

This report supersedes the durable-revocation blockers in [Phase 1.2](PHASE_1_2_AUTH_SECURITY.md) for the verified scope below. [Phase 1.1](PHASE_1_1_SECURITY_REMEDIATION.md), the [original findings](PHASE_1_SECURITY_REVIEW.md), and the [permission model](MCP_PERMISSION_MODEL.md) remain the authorization references. Their unrelated open findings are not closed by authentication changes.

**Independent acceptance decision: 14 scoped PASS, 1 BLOCKED, no remaining reproduced Phase 1.3 failure after the corrections below. GO for continued scoped security remediation; NO-GO for Phase 2/MCP or production release.** Browser acceptance, complete infrastructure integration and the other original findings remain gates. The independent audit below supersedes earlier acceptance claims; the later implementation-stage evidence is retained as history.

## Independent acceptance audit — 11 November 2026

Review boundary: current source at `b6a220aa7fcdac29fe34bfb4fd8b949ec29b154d` plus the preexisting uncommitted Phase 1 work. No commit, staging, production connection, installed-service restart or existing-database migration was performed. The audit reused the reviewed disposable infrastructure/fixtures, added adversarial assertions, reproduced defects before correcting them, and reran the implementation regressions. Documentation was not used as evidence of a PASS.

### Defects reproduced and corrected

| Finding | Before correction | Correction and verification |
|---|---|---|
| P13-A1: stale ORM refresh state | A session that had already loaded an unconsumed refresh row retained that object after another transaction consumed it. `SELECT FOR UPDATE` acquired the database lock but did not refresh the cached attributes; a second call to `rotate` succeeded. The new PostgreSQL test failed with `HTTPException not raised`. This is a service-level defect under a preloaded identity map; the ordinary HTTP handler does not currently preload this row. | Refresh-row locking now uses `populate_existing=True`, matching user/session locking. The reproduced case now returns 401, commits family revocation, and proves `_pair` was never called. Normal HTTP concurrency still produces exactly one 200 and one 401. |
| P13-A2: presence validation latency | Successful delayed responses recorded their arrival time as fresh authorization and scheduled another full 15-second delay. With almost three seconds of response delay and a subsequent three-second timeout, revocation could take almost 21 seconds after the previous authority decision. Admission also did not independently reject expiry during its authority request. Four controlled-clock tests failed. | Freshness is anchored to the validation request start. The next poll subtracts time already spent waiting, including admission latency. Overdue responses and credentials expiring during admission are denied. Four new deadline tests pass; existing profile/expiry/session tests and the real transport check pass. The 18-second target still assumes a responsive event loop and the configured three-second authority timeout. |

Before-fix evidence: [PostgreSQL reproduction](../../backend/checks/mcp-phase1-3-audit-before.txt) (six PASS, one FAIL; launcher exit 1) and [presence reproduction](../../backend/checks/mcp-phase1-3-audit-presence-before.txt) (zero PASS, four FAIL). These failures are resolved by the current source; they are not omitted from the audit trail.

Only two runtime files changed during this audit: `backend/app/services/auth_sessions.py` and `presence-server/src/auth.js`. The launcher gained `--audit` and TCP readiness checking; new tests and this report supply the remaining changes. No migration, domain route, frontend runtime feature or MCP implementation was added by this audit.

### Criterion-by-criterion disposition

PASS means actual verification within the stated boundary. BLOCKED means insufficient acceptance evidence, not an assertion that the implementation failed. Broader operational limits are explicit in each row and in the test-level table below.

| # | Criterion | Result | Evidence and implementation state |
|---|---|---|---|
| 1 | Session revocation is durable | **PASS** | Implemented and tested: committed logout/reuse/epoch revocations survive a fresh backend interpreter, which denies old credentials and accepts an independent active session against the same PostgreSQL database. Transaction rollback preserves the prior valid state. No production restart or backup-recovery test is claimed. |
| 2 | Refresh rotation is atomic | **PASS** | Implemented and tested: injected failure after flushing consumption and successor SQL rolls both back; the original credential remains usable. Normal commit stores exactly one consumed predecessor and its successor. Real PostgreSQL transactions, not mocked persistence. |
| 3 | Reused refresh cannot issue access | **PASS** | Implemented and tested after P13-A1: preloaded-row reuse raises 401 without calling the minting function, and the family remains durably revoked. Existing replay tests deny successor access/refresh while preserving another login family. |
| 4 | Concurrent refresh attempts cannot both succeed | **PASS** | Implemented and tested: two distinct PostgreSQL backend PIDs are observed blocked using `pg_blocking_pids` while the user row is held. Releasing the lock produces exactly one 200 and one 401, two total credential rows and one consumed predecessor. Separate ASGI applications also pass the concurrent HTTP test. Strict replay revokes the winner's family afterward. |
| 5 | Tenant A → B → A never restores old credentials | **PASS** | Implemented and tested: actual trigger advances epoch on both changes; old A and B credentials stay denied after return. An independently tested tenant writer blocks a waiting refresh, then the refresh denies after the tenant change commits. Fresh authorized login succeeds. |
| 6 | Deactivation/reactivation requires new sessions | **PASS** | Implemented and tested: inactive password login is 403; old access/refresh deny before and after reactivation. Newly authenticated login succeeds. No reset of the old epoch. |
| 7 | Logout invalidates the intended session | **PASS** | Implemented and tested: successful logout denies current-family access/refresh, preserves a separate login, and serializes with concurrent refresh. Logout-all invalidates all user sessions. Real frontend API/interceptor integration preserves the captured logout bearer even if a new login changes storage before dispatch. Offline/unsuccessful server logout remains local-only; it is not evidence of durable server revocation. |
| 8 | Password changes/admin resets invalidate according to policy | **PASS** | Implemented and tested: actual handlers change the password, the PostgreSQL trigger revokes every affected session, and only login with the new password succeeds. Generated API sessions also deny after password invalidation. Policy is all sessions, including the changing user's initiating session. |
| 9 | Access validation respects revocation | **PASS** | Implemented and tested: REST and socket admission/delivery use live session validation. A preloaded access identity map observes another transaction's logout. Terminating only the test's PostgreSQL connection produces a database exception rather than successful authorization; a fresh connection still validates the surviving session. Missing/invalid expiry/type/epoch/tenant and legacy profiles deny. Checks occur at admission; admitted in-flight work is not canceled retroactively. |
| 10 | Presence renewal/active connections match the contract | **PASS** | Implemented and tested after P13-A2: real PostgreSQL-backed Python handlers refuse renewal/validation after logout; 60 Node checks cover profile/expiry/authority/deadline behavior; real Socket.IO transport verifies active disconnect within 18 seconds and denied reconnect. Its HTTP authority is controlled, not the live FastAPI/Redis stack. Backend task sockets recheck on packets/delivery and 25-second heartbeat; idle chat/ticket sockets recheck before traffic, without an idle-close timer. |
| 11 | Existing frontend authentication remains functional | **BLOCKED** | Implemented and tested at unit/component/build level: 11 coordinator tests, nine presence lifecycle tests, five real Axios/API/storage component checks, targeted strict TypeScript and Vite build PASS. Full browser login/refresh/logout, native cross-tab Web Locks and unsupported-browser behavior are **NOT RUN**. A controlled lock and synthetic adapter cannot close this acceptance criterion. No frontend runtime changes were made in this audit. |
| 12 | Disposable PostgreSQL migration upgrade/downgrade is safe | **PASS** | Implemented and tested: actual incremental downgrade/upgrade preserves users and populated task/ticket/subtask rows. A conflicting table forces transactional rollback of partial DDL and revision state. A held user-table reader causes PostgreSQL lock timeout (`55P03`) and leaves the predecessor intact; upgrade then succeeds. The fixture builds current business metadata and stamps the predecessor; the entire historical migration chain is **NOT RUN**. Downgrade destroys auth history and is not an approved production rollback. |
| 13 | Indexes and cleanup are appropriate | **PASS** | Implemented and tested: inspect actual indexes/unique digest constraint; hold one expired family lock while two cleanup transactions each remove a different bounded batch via `SKIP LOCKED`. FK cascade removes refresh rows; live sessions, recent evidence and user epoch remain. Backup allowlists exclude security state. Automated cleanup scheduling/monitoring remains **designed but not implemented**; production volume/latency testing is NOT RUN. |
| 14 | Task, ticket and group functionality has not regressed | **PASS** | Scoped regression evidence: 23 real PostgreSQL business methods cover group visibility, creator/staff edits, assignee isolation, shared-write denial/rollback, multi-assignment creation, ticket workflows and subresources, nested relationships and notification checks. Another 37 frontend domain/cache/navigation/subtask/reward tests pass. These preserve the reviewed contracts; they do not certify every product screen or close the original unrelated findings. |
| 15 | No production database or services modified | **PASS** | Audit scope verified by connection/network/startup guards, owned tmpfs PostgreSQL and network-disabled Socket.IO containers, ownership-checked cleanup, before/after file hashes and container inventory. Nine local databases and the Git index remain unchanged. No installed/remote database was connected to, no production migration/deployment ran, and existing running-container IDs/state are preserved. This attests to audit actions, not unrelated third-party activity. |

### Executed tests, separated by level

| Level | Current audit result | Evidence / limits |
|---|---|---|
| PostgreSQL integration and concurrency | **51 test methods PASS:** eight new independent tests plus 43 retained tests (20 session/security, 23 business). Fresh-interpreter revocation check PASS; launcher exit 0. | [Complete audit log](../../backend/checks/mcp-phase1-3-audit-auth.txt). Real PostgreSQL 16, real Alembic, handlers, constraints, triggers, row locks and commits. Concurrency uses independent connections; no SQLite substitute. Injecting a commit exception tests a failure boundary, not a simulated lock outcome. |
| Node unit/profile/component | **60 PASS**, including four new delayed-authority/expiry tests. | Same audit log. Real Python-issued signatures in the existing profile tests; synthetic clocks/authority responses in deadline units. No live database in these Node units. |
| Socket transport integration | **1 PASS** | Real Socket.IO server/client handshake, packets, disconnect and reconnect in a network-disabled container; HTTP authority returns controlled 204/401. This is bounded transport integration, **not full-stack integration**. |
| Frontend unit/domain | **57 PASS** | [Frontend log](../../backend/checks/mcp-phase1-3-audit-frontend.txt): 11 refresh, nine presence and 37 existing domain methods. Controlled cross-tab lock, not native browser Web Locks. |
| Frontend Axios component integration | **5 PASS** | [HTTP component log](../../backend/checks/mcp-phase1-3-audit-http.txt): existing login envelope/storage, simultaneous 401 refresh, captured logout identity, ambiguous response with no retry, stale denial after account change. Real API methods/interceptors/storage; synthetic Axios transport with network denied. |
| Compilation/static checks | **PASS** | [Vite build](../../backend/checks/mcp-phase1-3-audit-build.txt), [targeted strict TypeScript](../../backend/checks/mcp-phase1-3-audit-typescript.txt), [Ruff/Node/diff checks](../../backend/checks/mcp-phase1-3-audit-static.txt). Build output is an owned temporary directory; installed assets untouched. No full-repository TypeScript-clean claim. |
| Full integration | **BLOCKED / NOT RUN** | No complete disposable browser + application-startup + PostgreSQL + presence + Redis + proxy/TLS topology was established. The guarded harness rejects installed endpoints and application startup. Existing services were not used to fill this evidence gap. Deployed routing, native browser coordination, Redis interaction and full login-to-presence flow therefore remain unverified. |

Reproduce the PostgreSQL/Node/transport audit from the repository root:

```powershell
.\backend\venv\Scripts\python.exe -B backend/security_tests/run_mcp_phase1_3.py --audit
```

The [independent test source](../../backend/security_tests/mcp_phase1_3_audit.py), [presence deadline tests](../../presence-server/test/session-deadline-audit.test.mjs) and [Axios component tests](../../frontend/test/session-http-audit.test.ts) preserve the new assertions. The [audit scope manifest](../../backend/checks/mcp-phase1-3-audit-scope.json) records the 2,034-file starting snapshot, final hashes, changes and service preservation. Original logs and unrelated dirty work are retained.

### Remaining acceptance gates and next phase

- **Implemented and tested:** durable session/epoch storage, atomic rotation, reuse revocation, locking against security writers, access admission, bounded presence behavior, cleanup primitive, incremental migration and the scoped regressions above. Both reproduced defects are corrected and retested.
- **Implemented but not tested end to end:** browser authentication/native Web Locks and complete backend/presence/Redis/proxy deployment wiring. Criterion 11 stays BLOCKED; full integration stays NOT RUN.
- **Designed but not implemented:** automatic cleanup scheduling/monitoring and the proposed MCP OAuth/delegation authority. The existing legacy password endpoint and arbitrary API scope labels do not implement that authority. No MCP code was added.
- **Unresolved:** S01/S02/S04/S06/S09/S10/S11 authorization/relationship/cache gaps, unsupported-browser multi-tab guarantees, shared signer trust, long-lived generated API-token policy, deployment/recovery validation and production-scale performance. Read-only source review confirms remaining transfer-target, ticket relationship, global department/Kanban and ticket-cache patterns; this audit does not rerun or close every original finding.

**GO for further scoped security remediation. NO-GO for Phase 2/MCP or production release.** Complete the blocked browser/full-integration gates, resolve the applicable multi-tenant findings, and separately verify dedicated MCP issuer/audience/client/consent/grant revocation, scopes and object/field authorization before any MCP phase is accepted. Phase 1.3 session revocation does not supply delegated authorization. Do not deploy or downgrade production based solely on these local results.

## 1. Verified lifecycle and entry points

| Entry point / consumer | Phase 1.3 behavior |
|---|---|
| `POST /auth/register` | Creates a session with the new user in the registration transaction; unchanged response envelope. Inactive accounts cannot receive a usable session. Registration, access, refresh and logout are verified against PostgreSQL. |
| JSON/form `POST /auth/login` | Locks the user before checking password/status, creates a login family and initial credential digest, commits before returning the existing `{token,user}` envelope. |
| `POST /auth/refresh` | Validates the signed profile and database binding, atomically consumes one credential and issues its successor. Invalid credentials/sessions return 401. |
| `POST /auth/logout` | Revokes the presented session and commits before 204. Other sessions remain active. The frontend retains local logout when offline; server revocation requires the request to reach the server successfully. |
| `POST /auth/logout-all` (new) | Authenticated self-service security invalidation: advances the user's epoch and revokes all login/API sessions in the transaction. |
| `POST /auth/generate-token` | Existing Owner/Admin boundary and response shape retained. Creates a separate durable API session with the requested lifetime, without a refresh credential. Rechecks the invoking session under the user lock. |
| `POST /oauth2/token` | Mounted legacy password endpoint previously referenced a nonexistent password-hash attribute and a placeholder signing key. Now uses the shared password verifier, configured signing key and durable API-session service; preserves `{access_token,token_type}` and its one-hour lifetime. |
| `GET /auth/presence-token` | Issues a dedicated presence JWT bound to the caller's current session and epoch; expiry cannot exceed session expiry. |
| `POST /auth/presence/validate` (new) | Read-only presence JWT authentication and live PostgreSQL session validation; returns 204/401, no profile/data response. Normal REST/refresh JWTs are rejected. |
| REST dependencies / tenant dependency | Load the user and session in one current database snapshot; require active user, matching tenant/epoch, unrevoked and unexpired session, and bounded token expiry. No process or Redis authorization cache. |
| Backend task/chat/ticket WebSockets | Carry validated session claims into admission and existing delivery/packet checks. Task heartbeat checks every 25 seconds. Fanout groups separate sessions for the same user. Idle chat/ticket sockets recheck before traffic, not on a new idle timer. |
| Presence Socket.IO | Strict separate profile, backend authority on admission and every 15 seconds; three-second timeout and fail-closed disconnect. |
| Password change, admin reset, user updates | Existing handlers retain their business contracts; the database trigger invalidates sessions transactionally when security fields change. |
| Forgot-password stub | Still the existing enumeration-safe stub; no reset delivery or new password-reset workflow was implemented. |

Canonical routes and their existing `/api` aliases use the same routers. The middleware's signature-only decode for security-log attribution grants no access. The shared low-level JWT encoding helpers can still construct synthetic/legacy profiles, but authenticated consumers reject credentials without a valid durable session.

## 2. PostgreSQL authority and schema

New Alembic revision: **`l2b4d6f8a0c2`**, parent **`k1a3c5e7f9b1`**, in [migration source](../../backend/alembic/versions/l2b4d6f8a0c2_auth_sessions.py).

| Storage | Fields and purpose |
|---|---|
| `users.auth_epoch` | Nonnegative bigint, initial zero. Monotonic per stable user ID; the trigger rejects decreases. Never reset on tenant return or reactivation. |
| `auth_sessions` | Random UUID-string `id` is both session/family ID and correlation ID; user FK, immutable issuing tenant, issuing epoch, `kind` (`login`/`api`), creation/absolute expiry/last rotation time, revocation timestamp/reason. |
| `auth_refresh_tokens` | Random UUID-string token ID, session FK, unique SHA-256 digest of the complete signed refresh credential, issue/expiry/consumed timestamps and successor ID. **No raw refresh credential is persisted.** |
| User invalidation trigger | `BEFORE UPDATE` of tenant, password hash, status, role or epoch; advances the epoch and revokes all unrevoked sessions for that user in the same transaction. Covers ORM, bulk SQL and maintenance writers that do not disable triggers. |

There is one refresh family per login session, so no redundant family table is needed. Refresh rows inherit revocation from their session. Session ID and predecessor/successor IDs correlate issuance, consumption and the durable revocation reason; general audit queue delivery remains best effort and is not the authority.

Indexes cover user/revoked lookups, session expiry/ID cleanup, refresh-family lookup and unique token digests. Foreign-key deletion cascades remove credentials only with their session/user. Session tenant history does not reference the user's mutable current tenant. User/session epochs and positive session lifetimes have database constraints.

The migration is PostgreSQL-only, with five-second lock and 120-second statement timeouts. Runtime startup performs a read-only table/column/trigger preflight and fails if authentication storage is absent. The new auth tables are excluded from runtime `metadata.create_all`; no auth column/table/trigger repair helper exists. Alembic metadata imports suppress the three preexisting database-import repair helpers. Other historical startup schema helpers were not redesigned.

Business backup/export/restore allowlists explicitly exclude both new tables and `users.auth_epoch`. They cannot export session digests, overwrite epochs or restore revoked authentication state. This preserves whole-workspace export discovery without expanding its data surface.

## 3. Rotation and revocation rules

All newly issued access, refresh and presence credentials carry signed `sid`, `jti`, `auth_epoch` and `iat`, alongside existing subject/tenant/expiry/profile claims. Presence retains exact type `presence`, issuer `zeaplay`, audience `zeaplay-presence`, known roles and exactly the presence scope. API, refresh and presence profiles are not interchangeable. Integer expiry is mandatory; missing, malformed, expired and legacy sessionless credentials are denied.

Login sessions have an **absolute lifetime equal to the configured refresh lifetime** (default seven days). Rotation does not extend it. Access expiry is the earlier of the configured access lifetime (default 24 hours) and session expiry. Presence expiry is the earlier of one hour and session expiry. Standalone generated API tokens retain the requested duration, including the preexisting long-duration option, but now have a durable session checked on every use. Arbitrary API scope labels still do not constitute a delegated permission model.

Refresh uses PostgreSQL row locks in the order **user -> session -> refresh row**. The transaction verifies current status/tenant/epoch, compares the credential digest, consumes the old row, links its successor and inserts the successor digest before commit. Issuance cannot race a security-field writer into retaining an older epoch. The digest, not only a presented token ID, must match.

**Strict replay policy:** presenting a previously consumed credential revokes that session/family, commits revocation, then returns 401. The entire family, including any just-issued access/refresh/presence credentials, becomes invalid. There is no grace period or idempotent replay response. Two simultaneous requests can produce **one 200 and one 401**; the 401 replay deliberately invalidates the successful response's credentials too. Other login families are unaffected. Expired/revoked/wrong-tenant/inactive refresh sessions all return 401; inactive password login retains its existing 403.

| Event | Durable effect |
|---|---|
| Successful logout | Current family revoked with `logout`; separate logins/API sessions remain valid. |
| Logout-all / explicit epoch increase | All user sessions revoked with `security_invalidation`. |
| Tenant A -> B -> A | Epoch advances at each change; all previous A and B sessions remain unusable. |
| Deactivation/reactivation | Each status change advances epoch; old tokens never revive. Fresh password login is required after reactivation. |
| Own password change / administrator reset | Password-hash change revokes all sessions, including the initiating session if it belongs to that user. |
| Role change | Security invalidation of existing sessions; subsequent login uses current database role. |
| Confirmed refresh reuse | Affected family revoked with `refresh_reuse`. |
| Database outage | No successful authorization fallback. REST may return a server error; presence disconnects on denied/unavailable validation. |

REST authorization is checked at request admission. An already admitted request is not retroactively canceled by a later concurrent logout; subsequent checks observe committed revocation. Refresh and revocation writers serialize on the user/session locks. There is no Redis-only invalidation dependency.

`cleanup_expired(db, batch_size=500)` is an explicit operator/job primitive, not an automatically started job. It retains entire families, including consumed-token evidence, through absolute expiry **plus 30 days**, deletes at most 1,000 families per call using `SKIP LOCKED`, and relies on FK cascade for refresh rows. The caller commits. User epochs are never pruned. Scheduling and monitoring this cleanup job are **designed but not deployed**.

## 4. Frontend and presence boundary

The Axios refresh call remains a separate, single POST without response-interceptor retries. The coordinator shares in-flight work within a tab, uses Web Locks across cooperating tabs, rereads stored tokens after acquiring the lock and uses a successor already written by another tab. A local-storage attempt marker prevents reissuing the same credential after an ambiguous network result or a crashed tab. An unconfirmed refresh requires fresh sign-in; it is never retried automatically. Logout/account changes discard stale responses, and requests from different sessions do not share pending refresh results.

Web Locks require browser support and, normally, a secure context. The fallback retains per-tab coordination and the attempt marker but cannot guarantee atomic cross-tab coordination. Unsupported browsers or older client bundles can therefore trigger the strict replay policy and require sign-in. Full browser/native-Web-Locks validation is **NOT RUN**; the separate-tab coordinator test uses a controlled shared lock. A coordinated frontend reload is required at rollout.

Presence identity comparisons include session and epoch while remaining stable across ordinary refresh. Node has **no PostgreSQL connection or database credentials**. `PRESENCE_SESSION_VALIDATION_URL` points to the trusted backend's read-only validation endpoint. Compose source defaults it to `http://backend:7211/auth/presence/validate`; cross-host deployments must use TLS or an equivalently trusted private link. Redirects and URL credentials/query strings are refused. Authorization headers must be excluded from proxy/access logs.

Presence admission validates signature/profile locally and then requires backend 204. Existing connections poll every 15 seconds with a three-second timeout; denial/outage closes them. Target latency is **at most 18 seconds under a responsive event loop**. An overdue incoming-packet guard also fails closed. Expiry timers remain active. Process suspension/event-loop starvation can delay wall-clock disconnect; this is not a hard real-time guarantee. Shared API/presence signing-key trust is unchanged; profile separation does not isolate a compromised signer.

## 5. Implementation-stage evidence and dispositions (historical)

| Verification | Result | Evidence / limit |
|---|---|---|
| Registration/login/form/JSON and alias refresh; digest-only storage | **PASS — implemented and tested** | Real handlers and PostgreSQL transactions. |
| Single-use rotation and replay family invalidation | **PASS — implemented and tested** | Old digest consumed; successor usable until a replay revokes the family; independent login preserved. |
| Two simultaneous refresh requests | **PASS — implemented and tested** | Two ASGI app instances, concurrent threads and separate PostgreSQL transactions: exactly one 200 and one 401; winner then revoked. No mocked locking/concurrency result. |
| Logout and security invalidation | **PASS — implemented and tested** | Current-session and all-session revocation, followed by fresh login; concurrent logout/refresh leaves no surviving credential. |
| A -> B -> A and deactivation/reactivation | **PASS — implemented and tested** | Actual PostgreSQL trigger; prior credentials remain denied. |
| Own password and administrator reset | **PASS — implemented and tested** | Actual password handlers, password verification and trigger; all affected credentials denied. |
| Direct SQL invalidation and rollback | **PASS — implemented and tested** | SQL epoch change revokes; rollback restores the previous valid transaction state; epoch decrease rejected. |
| Expired sessions/JWT profile and legacy token rejection | **PASS — implemented and tested** | Missing/invalid expiry/type/session/epoch/tenant and wrong signature rejected; valid refresh still succeeds. |
| Other backend process / restart boundary | **PASS — implemented and tested** | Separate fresh Python interpreter observes previous process's revocations and accepts the surviving session. Production rolling deployment is NOT RUN. |
| Presence issue, renewal denial and backend validation | **PASS — implemented and tested** | Real Python handlers against PostgreSQL; REST/refresh/presence separation; logout prevents renewal and validation. |
| Python -> Node profiles and fail-closed revalidation | **PASS — implemented and tested** | 56 Node tests use actual Python-issued JWTs and real `jsonwebtoken`; malformed profiles, authority denial/outage and deadline/expiry handling. |
| Real Socket.IO transport | **PASS — implemented and tested, bounded integration** | Handshake, ping/ack, API-token denial, established disconnect and revoked reconnect denial. Test duration about 15.1 seconds; asserts disconnect within 18 seconds. A controlled HTTP authority returns 204/401; it is not a live backend/Redis stack. |
| Backend socket session separation | **PASS — implemented and tested** | Real DB-backed admission/delivery; two sessions of one user are independently allowed/closed. |
| Task/ticket/group and targeted gamification preservation | **PASS — tested scope** | 23 retained Phase 1.1 business regression methods execute on PostgreSQL; existing authorization assertions preserved. No exhaustive product certification. |
| Incremental migration upgrade/downgrade/upgrade | **PASS — implemented and tested** | Actual Alembic commands on newly owned PostgreSQL, preserving populated users. Fixture establishes business metadata and stamps the predecessor; full historical migration chain from an empty DB is NOT RUN. |
| Backup registry and retention cleanup | **PASS — implemented and tested** | Catalog excludes auth state; bounded cleanup preserves live replay evidence and removes expired family rows. |
| Frontend refresh/presence/domain regressions | **PASS — implemented and tested** | 57 tests: 11 refresh coordinator, 9 presence lifecycle and 37 existing domain/cache/navigation/workflow/reward tests. |
| Production frontend compilation and targeted TypeScript | **PASS — tested** | Vite build in an owned temporary directory; strict check of new refresh/presence modules/tests. Existing bundle-size/dependency-eval warnings remain. Not a full-repository TypeScript-clean claim. |
| Full browser/native locks, full server/Redis/proxy/TLS, external services | **BLOCKED / NOT RUN for acceptance** | No safe end-to-end installed environment was used. The bounded components and transport checks above do not certify the full deployed stack. |
| Production rollout | **BLOCKED / NOT RUN** | No migration/deployment authorized or performed. Actual production configuration requires the absent `.env.production`. Local Compose validates; production Compose structure and the authority URL validate with a disposable synthetic env file, not production values. |
| Original unrelated security findings / Phase 2 | **Unresolved — NO-GO** | S01/S02/S04/S06/S09/S10/S11 and delegated-authentication boundaries remain outside Phase 1.3. |

The earlier implementation-stage PostgreSQL suite reported **43 PASS** (20 session/security methods and 23 business methods), zero failures/errors, **90.824 seconds**, followed by the separate-process PASS, 56 Node PASS and one real Socket.IO PASS. The directly captured launcher exits **0**; the earlier PowerShell redirection status discrepancy is resolved. See [auth/PostgreSQL/Node/transport log](../../backend/checks/mcp-phase1-3-auth.txt), [frontend log](../../backend/checks/mcp-phase1-3-frontend.txt), [build log](../../backend/checks/mcp-phase1-3-build.txt), [TypeScript result](../../backend/checks/mcp-phase1-3-typescript.txt), [static checks](../../backend/checks/mcp-phase1-3-static.txt), [Compose checks](../../backend/checks/mcp-phase1-3-compose.txt) and [scope manifest](../../backend/checks/mcp-phase1-3-scope.json).

Targeted Ruff F/E9 and Node syntax checks pass; two existing unused-import diagnostics in `ws/chat.py` are excluded and were not cleaned up as unrelated work. `git diff --check` passes. Earlier failed fixture attempts exposed existing append-only TRUNCATE protection and a fixture object-lifetime issue; the final harness rebuilds only its disposable schema and keeps domain protections enabled.

The launcher owns a randomly named PostgreSQL 16 container, fresh keys/password, loopback ephemeral port, tmpfs data and no host-data mounts. It supplies a sanitized child environment and temporary working directory. Native driver/SQLAlchemy guards restrict connections to that database; Python network/process/startup guards block installed services. No `app.main` or destructive legacy test collection is imported. Only general asynchronous audit/external publication transports are captured; real business guards, database triggers, password handlers, transactions and serializers run. The Socket.IO test runs in a separate `--network none` container with read-only fixture/dependency mounts, Node 20 and no Redis/installed-service access. Ownership labels gate cleanup. Both containers are removed.

Reproduce from the repository root:

```powershell
.\backend\venv\Scripts\python.exe -B backend/security_tests/run_mcp_phase1_3.py
```

Required locally: Docker, cached `postgres:16-alpine` and `zeaplay_v1-presence:latest` images, backend virtualenv and frontend installed dependencies. Missing infrastructure returns NOT RUN/BLOCKED, never a mocked PostgreSQL PASS.

## 6. Files and preservation

Existing source changed: `backend/app/auth.py`, `dependencies.py`, `models.py`, `database.py`, `main.py`, `routers/auth.py`, `routers/oauth2_server.py`, `services/navigation_sockets.py`, `ws/{tasks,chat,ticket_chat}.py`, `backups/registry.py`, `backend/alembic/env.py`; `frontend/services/{mockApi,presenceConnection}.ts`, `frontend/test/presence-auth.test.ts`; `presence-server/src/{auth,server}.js`, its README; both base/production Compose files (only the session-validation URL wiring).

New source: `backend/app/session_models.py`, `backend/app/services/auth_sessions.py`, the migration above, `frontend/services/sessionRefresh.ts`. New tests: `backend/security_tests/{run_mcp_phase1_3,mcp_phase1_3_cases}.py`, `frontend/test/session-refresh.test.ts`, `presence-server/test/{sessions.test.mjs,socket-transport.cjs}`. This report and `backend/checks/mcp-phase1-3-*` contain evidence.

The implementation-stage starting manifest covers **2,017 existing files**, including **nine local database files and the Git index**. Exactly 21 expected existing files changed; no existing file was removed. All nine databases, the index and unrelated source—including the prior dirty task-router work—remain byte-identical to the start-of-phase snapshot. No staging, commit, reset, production data/schema change or running-service restart was performed. This attests to this work's actions and local files, not unrelated remote activity.

## 7. Transition, rollout and rollback

**Legacy credentials are not grandfathered. All existing users and API integrations must sign in or mint replacement credentials after cutover.** Token keys do not rotate automatically. Existing login/refresh JSON envelopes remain compatible, but refresh credentials are single-use, session expiry is absolute, inactive refresh is now 401, and password/status/tenant/role changes require new login. Old frontend bundles can cause replay revocation and must reload.

For a separately approved production rollout:

1. Back up PostgreSQL/configuration and preserve current image digests. Inspect the installed Alembic revision and schema drift without running application startup repair. Verify the predecessor lineage; the tests do not certify every historical migration. Review long-lived API clients and forced-login communication.
2. Verify `.env.production`/secrets and the trusted presence-validation URL, signing algorithm/key match, routing, synchronized clocks, database privileges and backup exclusions. Ensure Authorization headers/request bodies are not logged. Application roles must not disable triggers or rewrite security history.
3. **Expand:** apply the additive migration explicitly through the approved migration process. From the configured backend directory the target is `alembic upgrade l2b4d6f8a0c2`; resolve the installed predecessor first. This command was not run against an existing installation. Never substitute application startup for this migration.
4. Drain authentication traffic and old WebSockets; switch all backend replicas, presence services and frontend to the session-aware release as one coordinated cutover. Do not run old stateless readers alongside the new authority under user traffic. Only release traffic after every reader enforces sessions and the presence endpoint is reachable. No compatibility flag permits legacy tokens.
5. Verify fresh login, one refresh, logout, tenant/status/password invalidation, long-lived API clients, presence reconnect/expiry and existing task/ticket flows through the real proxy. Monitor 401s, reuse counts, session-table growth, lock waits and validation latency without logging bearer credentials. Schedule bounded retention cleanup with reviewed permissions.
6. **Contract:** retain epochs and revocation history permanently as part of the supported authentication schema; prune only expired families by the documented retention rule. There is no automatic destructive contract migration.

**Rollback limitations:** database downgrade removes security history and is suitable only for disposable tests. It is not a production rollback plan. Preserve the migrated tables, epochs and trigger. Roll back only to a release that still enforces the same session authority; otherwise keep authentication disabled/drained and forward-fix. Restoring an older database snapshot can resurrect revoked credentials: recovery must require credential invalidation (for example reviewed signing-key rotation plus forced reauthentication) before reopening traffic. Never return to an old stateless reader while claiming durable revocation.

## 8. Remaining gates

Implemented and tested: session storage, strict profile checks, atomic rotation/replay, transactionally durable invalidation, REST/backend-socket admission, presence checks, coordinator logic, incremental migration and scoped regressions. Implemented but not exercised end to end: full installed deployment wiring. Designed but not implemented as an automated job: cleanup scheduling; the bounded cleanup primitive itself is implemented and tested. Designed but not executed: production cutover/monitoring and operational rollback/recovery. Unresolved: unsupported-browser multi-tab coordination limits, full production-topology validation, shared signer trust, preexisting long API-token durations and the other original authorization findings.

**Stop at Phase 1.3. The independent audit above governs acceptance: GO for further scoped remediation; NO-GO for Phase 2/MCP and production release while browser/integration and authorization gates remain open.**
