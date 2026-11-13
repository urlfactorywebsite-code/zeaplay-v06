# Phase 1.1: Targeted security remediation

Date: **11 November 2026, Asia/Calcutta**. Starting source: `d8100d1`. Independently re-audited against working source at HEAD `b6a220a`; committed and uncommitted Phase 1.1 changes are both included.

**Independent acceptance result: NO-GO. Nine criteria PASS within the tested scope, three FAIL, and one is BLOCKED.** FastAPI group/ticket protections pass the isolated checks. Authentication is incomplete: the separate presence middleware still accepts nonexpiring/typeless tokens, refresh credentials can cross an account's tenant move, and explicit durable revocation does not exist. The acceptance matrix below supersedes any broader interpretation of the earlier remediation results. This audit changed only this report and added isolated test/evidence files; application source was not changed.

| Finding | Status | Scope of conclusion |
|---|---|---|
| S05 | **FIXED** | Group expansion, nested dependency disclosure, shared-field authorization, collateral sibling reconciliation and group event IDs repaired in source and isolated regressions. |
| S03 | **FIXED** | Ticket task/log authorization, linked-task filtering, UUID serialization and canonical/API read routing repaired in source and isolated regressions. |
| S07 | **PARTIAL / ACCEPTANCE FAIL** | FastAPI expiry/type checks and inactive refresh denial pass. Presence validation is inconsistent; old-tenant refresh credentials remain usable after tenant movement; persistent revocation is unimplemented. |
| Phase 2 | **NO-GO** | Durable revocation, delegated authentication and other applicable Phase 1 security findings remain prerequisites. |

These are local source/test results, not production certification. No MCP server, MCP Settings UI, deployment, dependency installation, signing-key rotation or database migration was performed. The checkout was clean at the initial status check. HEAD subsequently advanced to `b6a220a` during this session; review uses the recorded starting commit so that already committed edits are included. No commit, staging, reset, restore or push command was issued by this remediation work. Existing Phase 1 documents and both security-test files remain unchanged.

## Independent acceptance audit

PASS requires an executed assertion or measured source/file invariant. It is bounded by the named surfaces and synthetic fixtures. FAIL means a reproduced counterexample. BLOCKED means a required capability or safe test prerequisite is absent; it is not a pass. Successful diagnostic methods can reproduce a security failure. The independent Python and presence audit runners therefore exit **2** when their assertions succeed but security gates remain open.

| # | Criterion | Verdict | Implementation / verification evidence |
|---|---|---|---|
| 1 | Unauthorized group siblings cannot be retrieved | **PASS** | Implemented and tested for canonical/API group/direct/list/Kanban reads, nested dependencies and in-process task-event payloads. Ordinary assignee/follower gets only authorized rows; denied sibling direct read is 403. Cross-tenant group-ID collision does not expand a foreign task. Real transport integration is NOT RUN. |
| 2 | Creators retain permitted grouped-task visibility | **PASS** | Implemented and tested. A creator downgraded to ordinary USER still sees their two independently authorized assignments. Separate assignment IDs, group IDs and child IDs are retained; no new group-owner privilege was introduced. |
| 3 | Assignees cannot read or modify unauthorized siblings | **PASS** | Implemented and tested. Denied direct/group reads, shared edits and group append; independent PATCH, complete, delete and child PATCH against a denied sibling return 403 on both aliases, with zero INSERT/UPDATE/DELETE statements. Existing S01/S10 policies are not certified by this result. |
| 4 | No unintended group-wide update propagation | **PASS** | Implemented and tested, sequential fixtures. Shared changes require every peer's write permission before DML; status/completion and transfer reconciliation affect only the anchor. Denied priority edit leaves both wallets at 145 and ledger at four entries; authorized creator HIGH-to-LOW change reconciles both to 115, combined ledger net 30. Foreign same-group row stays unchanged. PostgreSQL concurrency is NOT RUN. |
| 5 | Ticket logs require ticket object authorization | **PASS** | Implemented and tested on both aliases, including with no global navigation dependency. Non-member 403 / foreign 404; no protected audit-log query precedes denial. Current participants/followers/pending approvers and authorized staff retain access. Live Admin-to-USER demotion is enforced. |
| 6 | Ticket task subresources require ticket and task authorization | **PASS** | Implemented and tested. Ticket membership is checked before the task query; each linked task and dependency must pass the direct-task policy. An authorized ticket participant cannot see an otherwise denied linked task. UUID ticket IDs serialize to strings. This covers the remediated GET subresources, not approval/creation policy in S02. |
| 7 | Cross-tenant and unrelated same-tenant requests are denied | **FAIL** | Task/group/ticket resource denials PASS. Authentication counterexample: after moving a synthetic user from tenant A to B, the old access token is rejected (401), but the old A refresh token returns 200 and mints usable B access on both aliases. Refresh tenant/session binding remains unresolved. Broader S01/S02/S04/S06/S09/S10/S11 findings also remain open. |
| 8 | JWT tokens without expiration are rejected | **FAIL** | Implemented and tested in FastAPI: missing `exp` returns 401. Exact `presence-server/src/server.js::authenticateSocket` executed with real `jsonwebtoken@9.0.2` accepts a correctly signed token without `exp`. Presence source is unchanged from baseline; this is a remaining consumer gap, not a new regression. |
| 9 | JWT token type and expiry are validated consistently | **FAIL** | FastAPI access/refresh reject wrong signatures/algorithm, omitted/wrong type and malformed/expired expiry. Presence accepts omitted/null/empty type and fractional expiry; it rejects explicit refresh type and expired tokens. Issuing a valid presence token does not establish validation consistency at its consumer. |
| 10 | Reactivated users cannot reuse explicitly revoked tokens | **BLOCKED** | **Designed but not implemented.** No durable revoke operation/state exists, so the test using an explicitly revoked credential is **NOT RUN**. Executed lifecycle probe: logout 204, old access still 200; deactivated access/refresh 403; reactivated old access/refresh 200. These tokens were never explicitly revoked; deactivation/logout must not be mislabeled revocation. |
| 11 | Existing login and refresh remain functional | **PASS** | Implemented and tested: real password hashing, JSON login, form username/password login, both route aliases, refreshed resource access, invalid password 401, inactive 403 and existing reusable-refresh behavior. Browser storage/session handling and live proxy login are NOT RUN. |
| 12 | Existing task, ticket and gamification behavior is preserved | **PASS** | Targeted regressions executed: grouped creation, permitted shared edits, task views/history, ticket creation/task linkage/status/pending-task guard, transfer request/approval, reward reconciliation and completion idempotency. Repeating task completion across aliases pays HIGH 30+15 only once: wallet 100->145, completed count 1; sibling stays TODO/wallet 100. All 37 selected frontend contract tests pass. This is not exhaustive product, PostgreSQL or visual certification. |
| 13 | No production data, schema or unrelated source was modified | **PASS** | Scope/safety verification: before/after SHA-256 comparisons of 1,994 existing tracked/local-DB files (including nine local DB files), plus Git index, show no audit-time changes. The complete Phase 1.1 application diff contains 12 related files; ORM models, migrations, frontend and presence source have no baseline diff. Original Phase 1 tests are byte-equivalent after line-ending normalization; four extracted task policy functions are AST-equivalent to baseline. Runtime probes deny external networking/file DBs/startup; no production connection or mutation occurred. Remote production state was NOT INSPECTED, so this is no claim about unrelated external activity. |

### Independent evidence and reproduction

| Evidence | Actual result in this audit |
|---|---|
| [Existing Phase 1.1 suite rerun](../../backend/checks/mcp-phase1-1-audit-regressions.txt) | **53 methods PASS**, 18.859 seconds; six narrow original diagnostics PASS, launcher 0. Its reactivation method intentionally measures an open risk. |
| [Additional independent assertions](../../backend/checks/mcp-phase1-1-audit-independent.txt) | **14 methods PASS** (10 independent methods + 4 isolation controls), 5.153 seconds. Gate 7 FAIL / gate 10 BLOCKED; launcher 2. |
| [Exact presence middleware probes](../../backend/checks/mcp-phase1-1-audit-presence.txt) | **9 measured profiles + 2 network-denial controls**; gates 8 and 9 FAIL; runner 2. Extracted function SHA-256 and library version recorded. Full presence server, Socket.IO transport and Redis NOT RUN. |
| [Frontend contract regressions](../../backend/checks/mcp-phase1-1-audit-frontend.txt) | **37 PASS**, 782.3655 ms, exit 0; network/listener-denial preload enabled. No browser or installed API used. |
| [Scope and preservation manifest](../../backend/checks/mcp-phase1-1-audit-scope.json) | No protected-file/index changes, policy AST equivalence, no ORM/migration/frontend/presence diff, SHA-256 hashes for all 12 reviewed application files. |
| Static checks | Targeted Ruff F/E9 PASS on 12 application + 4 Python harness files; only preexisting `workflow_service.py:F811` excluded. `git diff d8100d1 --check` PASS. No full lint-clean claim. |

From the repository root:

```powershell
.\backend\venv\Scripts\python.exe backend/security_tests/run_mcp_phase1_1.py
.\backend\venv\Scripts\python.exe backend/security_tests/run_mcp_phase1_1_audit.py
node backend/security_tests/mcp_phase1_1_presence_audit.cjs
```

The second and third commands **must currently return 2** for the measured open gates; do not treat them as green release gates merely because the observation assertions succeed. Python probes reuse the reviewed isolation/fixture setup but define independent expectations, select their tests explicitly, use real guards/queries/writes and retain the original blocked-startup/network/file-DB protections. Transport/audit sink substitutions are the same bounded ones described below. The presence probe reads and evaluates only the exact two authentication functions, supplies random synthetic signing material and uses the already installed frontend `jsonwebtoken@9.0.2` (compatible with the presence manifest); it never imports or starts the service and installs no dependency.

From `frontend`, the audit rerun used:

```powershell
node --require ../backend/security_tests/phase1_1_network_guard.cjs --test --test-isolation=none --import tsx test/task-query-cache.test.ts test/task-navigation.test.ts test/task-information.test.ts test/task-activity.test.ts test/subtask-workflow.test.ts test/subtask-reward-summary.test.ts
```

### Implementation states and remaining verification

- **Implemented and tested:** S05 group filtering/atomic peer authorization/reconciliation limits; S03 ticket-then-task/log authorization and serialization; FastAPI strict JWT expiry/type validation and inactive refresh denial; the specific compatibility cases in criteria 11-12.
- **Implemented but not integration-tested:** production router registration/lifecycle, actual proxy/TLS behavior, PostgreSQL row locks/concurrent permission changes/group append, real WebSocket transports and Redis delivery, browser interaction, and external audit/email/push/webhook delivery. Source/in-process checks do not replace these tests. Existing registration/minting sites were inspected; full registration was not executed. These integration checks are **NOT RUN** in this audit because no verified disposable runtime was used.
- **Designed but not implemented:** durable per-user revision/session revocation, reactivation protection, tenant-move invalidation, refresh/revoke race handling and selective session logout. The design below is not working functionality. No migration/revoke endpoint is present.
- **Unresolved:** presence JWT validation parity, old-tenant refresh acceptance and persistent revocation; original unrelated security findings listed below remain open. The two reproduced authentication gaps predate this audit. No application fixes were applied by the audit.

**Recommendation: NO-GO for accepting Phase 1.1 and advancing through the next security-remediation acceptance gate.** First remediate presence token validation and refresh tenant binding, implement an approved durable revocation contract, then execute the explicit revoked-token/reactivation tests and the required isolated integration checks. Targeted corrective work is the next action; this audit does not authorize MCP implementation or deployment.

## Policy applied

The Phase 1.1 request explicitly requires individual assignment authorization. The existing direct-task policy therefore remains authoritative: creator/assignee/follower access; Owner/Admin access within the creator's tenant; Manager access through own/assigned/followed tasks or an assignee in the Manager's department. No additional privilege comes from a group ID. An ordinary creator continues to see every assignment they are independently authorized to read. Creating a group does not confer new access to another creator's rows.

Shared title/description/priority updates preserve the existing group operation. Every affected row must pass the existing **write** guard before any mutation or autoflush. If one peer is denied, the entire request is denied; there is no partial peer update. Ticket-task write restrictions still apply to staff. This follows the atomic repair proposed in the S05 review. General observer/Manager write-policy questions in S10 are unchanged.

Ticket access uses `get_ticket_for_user` with the authenticated database role. Owner/Admin are tenant-scoped. Managers need a matching nonempty department; ordinary participant fallback is not substituted for the Manager branch. Ordinary creator/owner, current participants/followers and pending approvers retain their existing ticket access. A ticket viewer receives only individually visible linked tasks; omitted tasks do not cause the entire authorized ticket expansion to fail. This is the intersection required by the remediation request, not an expanded ticket permission.

## Root causes and changes

### S05

The group handler checked its anchor, then selected all same-tenant siblings. PATCH propagated shared fields and subsequently reconciled group rewards without authorizing each peer. Dependency summaries checked tenant only. Task WebSocket broadcasts could expose sibling IDs to other users in the tenant.

The unchanged direct-task guards and SQL predicate now live in `services/task_access.py`, with compatibility imports retained in the task router. Group reads use that predicate before loading/serializing results. An empty group key returns only the anchor instead of grouping unrelated records. Full task serialization uses the current actor to filter dependency summaries; existing tenant filtering and private-profile serialization remain in effect for nested users. Dependency relationships are eagerly loaded to avoid a per-dependency user lookup.

PATCH authorizes its complete shared write set under the existing group locks before mutation. Appending assignments also checks write access to existing group records. Reward reconciliation is limited to the actual, authorized write set: shared edits reconcile the authorized peers, while assignment-only edits and transfer reconciliation affect only the anchor. Reward formulas, history storage and group lock ordering were not changed. Template assignment was reviewed: it creates new groups, checks existing staff eligibility and restricts assignee candidates to the current tenant.

Task-event delivery independently filters `task_id` and every `task_ids` element using current database permissions. Denied/deleted objects produce an invalidation without their identifiers. Existing task notification inbox filtering continues to reauthorize linked assignments and has a regression check. No email/provider delivery was exercised. IDs, `task_group_id` relationships, separate assignment rows, frontend components and response shapes are retained.

### S03

The two workflow read handlers depended only on the token tenant. Navigation authorization did not establish membership in a specific ticket. The linked-task service selected every task with that ticket ID, and the log service queried private audit rows without first checking ticket access. Authorized task responses also failed validation because the ORM supplied a UUID where `TaskRead.ticket_id` expected a string.

Both handlers now require an active authenticated user. The services authorize the ticket before their protected task/log queries, deriving roles from that user. Linked tasks additionally use canonical task visibility and the shared nested serializer. `TaskRead` converts UUID ticket IDs to the existing JSON string/null contract; no database type changed. Log pagination and successful response envelopes are unchanged.

The existing `/api/tickets/{id}/tasks` and `/api/tickets/{id}/logs` routes remain. A small read-only router adds `/tickets/{id}/tasks` and `/tickets/{id}/logs`. It is registered explicitly in `main.py`, so the existing Nginx `/api/` prefix stripping reaches the same guarded handlers. No proxy configuration or other workflow route was changed. Route registration and rewrite equivalence were checked in process; actual Nginx/TLS execution was **NOT RUN**.

### S07

The common access decoder did not require `exp` and treated missing/empty token types as access tokens. The separate refresh decoder handled malformed claims inconsistently, and refresh issuance did not reject inactive users.

`auth.decode_token_claims` now validates the configured signature/algorithm, requires expiry, rejects expired or malformed expiry values, and requires exactly `access` or `refresh` for the selected decoder. Existing issuers produce integer NumericDate expirations; coercible strings, booleans, nulls and other malformed values are rejected. REST identity/tenant dependencies and backend WebSocket handshakes share this access decoder. Refresh decoding uses the same validation and maps malformed payloads to the existing 401 response. Inactive users cannot refresh.

Verified issuance sites are registration, JSON/form login, refresh, API token minting and presence-token minting through `auth._create_token`. Their signing keys, algorithms, lifetimes and issued claim format are unchanged. Login/refresh, minted-token and presence-token profile regressions pass. No compatibility exemption was added for typeless or nonexpiring tokens: no securely issued version of that profile was verified. The legacy OAuth password-grant implementation was neither reused nor modified.

**Audit correction:** this repair covers FastAPI consumers only. The separate presence service still uses `jwt.verify` without mandatory expiry and checks token type only when truthy. Its exact middleware accepts missing expiry and omitted/null/empty type in the independent execution above. Also, `TokenPayload` does not carry tenant binding into refresh authorization; refresh reloads the user and issues current-tenant claims. The independent tenant-move probe confirms old refresh credentials are retargeted. Neither gap is closed by this patch.

**Reactivation is not fixed.** Tests explicitly show that an old unexpired access token and refresh token work again after reactivation. Logout still has no durable token invalidation. Expiration bounds a token's lifetime; it is not revocation. Long-lived API tokens, unenforced scope labels and the absence of a dedicated MCP issuer/audience/grant boundary remain as documented in Phase 1. Refresh tenant-movement/session binding also requires the durable session design below; existing refresh behavior derives claims from the current user record.

## Revocation design and required approval

No safe durable revocation authority exists for these JWTs. They have no session identifier, `jti`, issue time or auth revision. `User.updated_at` also changes for unrelated profile/business updates. Push-subscription revocation is a different domain. Optional Redis or per-process memory would not provide reliable revocation across restarts, outages and replicas. Reusing those mechanisms would either revoke unrelated sessions or falsely promise security.

The proposed minimum is an additive, durable per-user authentication revision, owned by `(tenant_id, user_id)` and checked on access admission **and refresh**. This requires approved schema and token-contract work and is **not implemented** here:

1. Add an authentication revision with initial value zero. New tokens carry the current revision; validated pre-rollout tokens without it map to zero only while the stored revision is zero. Keep existing signing keys and expiry policy during this rollout. This preserves active existing sessions instead of globally logging everyone out.
2. Increment the revision atomically with deactivation, credential reset, tenant movement or an authorized revoke-all-sessions operation. Reactivation must never reset/decrement it. Seed already inactive accounts with a nonzero revision under an explicitly approved migration plan, so reactivation cannot revive old tokens. A tenant move must not retarget an old refresh token.
3. Read durable state on every protected request and refresh; fail closed when it cannot be checked. Do not rely on Redis invalidation alone. Serialize refresh issuance with revision changes so a concurrent refresh cannot mint a credential surviving a prior revocation. Revalidate active streams as required.
4. If individual-session logout is required, add session/family identifiers and a durable tenant/user-owned session registry. Store refresh/token digests, never raw tokens. Use refresh rotation/reuse detection. Handle old tokens through an explicitly approved compatibility path, such as a digest denylist through their expiry. Do not pretend a user-wide revision is selective session revocation.
5. Deploy readers to all replicas before enabling revision-changing operations/issuers. Keep the compatibility rule bounded and document the unusually long existing minted-token lifetimes. Test replica restart/outage, concurrent refresh/revoke, inactive-to-active transitions, old/new token coexistence and cross-tenant administrative denial in a disposable PostgreSQL environment.

No migration or revocation endpoint has been added. Approval is needed before implementing this design. This document is not authorization to deploy it.

## Modified files

| File | Purpose |
|---|---|
| `backend/app/auth.py` | Shared strict JWT claim validation. |
| `backend/app/dependencies.py` | Route common access decoding through that validator. |
| `backend/app/routers/auth.py` | Deny refresh for inactive accounts. |
| `backend/app/services/task_access.py` (new) | Existing task object/query guards shared across expansions. |
| `backend/app/services/task_serialization.py` (new) | Actor-aware dependency summaries and shared full-task serialization. |
| `backend/app/routers/tasks.py` | Group filtering, peer-write preflight, authorized reconciliation and serializer reuse. |
| `backend/app/ws/tasks.py` | Per-recipient filtering of group event IDs. |
| `backend/app/tickets/task_engine_service.py` | Ticket authorization before task query, then individual task filtering. |
| `backend/app/tickets/workflow_service.py` | Ticket authorization before log queries. |
| `backend/app/tickets/workflow_router.py` | Active-user dependencies and guarded canonical read aliases. |
| `backend/app/main.py` | Register the canonical ticket read router. |
| `backend/app/schemas.py` | UUID-to-string conversion for the existing task ticket-ID response field. |
| `backend/security_tests/run_mcp_phase1_1.py` (new) | Sanitized disposable child-process launcher. |
| `backend/security_tests/mcp_phase1_1_cases.py` (new) | Security and compatibility regressions using original isolation controls. |
| `backend/checks/mcp-phase1-1-latest.txt` (new) | Final expanded-suite output, with no token values. |
| `docs/mcp/PHASE_1_1_SECURITY_REMEDIATION.md` (new) | This report, updated by the acceptance audit. |
| `backend/security_tests/run_mcp_phase1_1_audit.py`, `mcp_phase1_1_audit_cases.py` (new) | Independent isolated expectations and explicit open-gate exit status. |
| `backend/security_tests/mcp_phase1_1_presence_audit.cjs`, `phase1_1_network_guard.cjs` (new) | Exact presence auth probe and Node network/listener guard. |
| `backend/checks/mcp-phase1-1-audit-*` (new) | Current audit outputs and preservation/source manifest linked above. |

## Original remediation regression evidence

This section retains the implementation-stage evidence. Current independent reruns and acceptance verdicts are above; earlier build/lint results were not independently rerun unless explicitly stated there.

The expanded runner executes the **20 unchanged Phase 1 methods plus 33 new methods: 53 PASS, zero failures/errors**, final measured run **18.747 seconds**, launcher exit **0**. All six original S03/S05/S07 diagnostic observations now report PASS. Their S07 measurement covers missing expiry only; it does not close the larger revocation finding. The suite prints an explicit `OPEN_RISK S07` message for reactivation.

Command, from the repository root:

```powershell
.\backend\venv\Scripts\python.exe backend/security_tests/run_mcp_phase1_1.py
```

Isolation is established before application imports: empty temporary working directory, sanitized child environment, randomly generated signing keys, memory-only SQLite, SQLAlchemy and direct SQLite connection guards, network/process denial and blocked application startup/legacy-test/migration imports. The original files are executed unchanged through `runpy` and their unittest classes remain in the suite. New request Sessions bind to a connection so StaticPool's single SQLite connection cannot be rolled back by a second SQLAlchemy inspector handle. Real domain guards, queries, serializers, transaction hooks and history execute. Redis publication, external webhook delivery and the asynchronous general audit sink are captured/suppressed; these external delivery systems are not certified.

| Coverage | Result |
|---|---|
| Ordinary creator consolidated access; assignee/follower isolation; authorized staff; departmental Manager limits; denied direct/group reads; foreign tenant; independent empty groups | PASS |
| Nested denied dependencies, foreign assignee/follower minimization and sibling child exclusion | PASS |
| Atomic shared title/description/priority denial before any DML; authorized creator/staff propagation; ticket-peer write restriction; guarded group append | PASS |
| Independent status change with an unrelated sibling reward-policy problem; preserved assignment/group/child IDs and task history | PASS |
| Multiple-assignee creation, separate IDs, shared group, list/grid data and Kanban API contracts | PASS |
| Ticket participant/follower/pending approver, Owner/Admin/Manager, same-tenant non-member, foreign/inactive/missing/deleted ticket | PASS |
| No protected linked-task/audit-log queries on denied ticket requests; individual linked-task and dependency filtering; string ticket ID contract | PASS |
| Ticket creation, linked-task creation, status transition, pending-task resolution guard and audit-log retrieval | PASS |
| Canonical/API route parity, explicit dependencies without global navigation, in-process Nginx prefix rewrite model | PASS |
| Missing/expired/malformed expiry and missing/wrong access/refresh type; real password login and refresh; inactive login/access/refresh | PASS |
| Existing API/presence issuance profile; database role authority and tenant mismatch regression | PASS |
| Reactivation accepts prior unexpired credentials | PASS measurement; **security gap OPEN** |
| Independent primary/batch WebSocket task-ID filtering; assignment-aware notification inbox | PASS, in-process fixtures |
| Existing frontend task/activity/history/subtask/reward/cache/navigation tests | **37 PASS**, zero failures |
| Frontend production build | PASS, Vite 6.4.2, **13.11 seconds**; dependency `eval` and large-bundle warnings remain. |
| Targeted Ruff `--isolated --select F,E9` on changed Python files | PASS with the existing `workflow_service.py` duplicate-function F811 explicitly excluded. |
| Full ambient Ruff configuration | FAIL: initial check reported 98 style/import/modernization diagnostics on the selected files, including existing code and isolation-harness import-order conventions. No general lint-clean claim. |
| `git diff d8100d1 --check`; original Phase 1 test-file diff | PASS; original files unchanged. |
| Real PostgreSQL locking/concurrency, installed API startup, live Nginx/TLS, Redis/multi-replica delivery, full browser visual/manual flows, external email/push/webhook delivery, production sessions | **NOT RUN** |

Frontend test command, from `frontend`:

```powershell
node --test --import tsx test/task-query-cache.test.ts test/task-navigation.test.ts test/task-information.test.ts test/task-activity.test.ts test/subtask-workflow.test.ts test/subtask-reward-summary.test.ts
npm run build
```

The build and contract tests provide regression evidence for existing UI consumers. They are not a claim that grouped cards, list/grid layouts or Kanban drag interactions were visually exercised in a browser. No frontend source was changed.

## Compatibility and remaining risks

- An ordinary assignee can now receive fewer group members and dependency summaries. Shared-field edits return 403 if any peer is not writable; independent status changes remain permitted. Clients submitting unchanged shared fields still request a shared operation and must meet that authorization check.
- Invalid/typeless/nonexpiring tokens now return 401. Verified existing issued access/refresh tokens retain the same keys, types and lifetime; no global session invalidation occurs. Unverified historical issuers require a controlled compatibility inventory, without logging tokens.
- Inactive refresh now returns 403. Reactivation/logout/revocation remain S07 blockers; no revoked-token test is represented as passing against an unimplemented mechanism.
- Canonical ticket reads are newly available behind the current prefix-stripping proxy; they have the same guards as the existing API aliases. Other API-only workflow proxy paths were not redesigned.
- Group updates retain existing locks. PostgreSQL race behavior, concurrent group append and permission changes during requests need staging verification; SQLite does not prove those semantics.
- S01 transfer authority/related-user issues, S02 ticket relationships, S04 global ownership, S06 general audit scope, S09 ticket caching, S10 broader writes and S11 legacy notification issues remain outside this remediation. Restricting collateral transfer reconciliation does not close S01. No broad MCP permission or tenant-isolation certification is implied.
- Previously delivered/cached data cannot be recalled by a server fix. Use a controlled client refresh when rolling out; no production cache was flushed here.

## Deployment and rollback guidance

Deployment was **not performed**. For a separately approved rollout, preserve the current source/image digest and configuration, take the normal database backup, then validate this exact patch against a disposable PostgreSQL installation. Check all affected routes both directly and through the actual proxy, normal browser login/refresh and task/ticket workflows, current role changes, and concurrent group writes. Confirm the existing installation schema is ready before startup: this repository has automatic schema helpers, even though this patch adds no migration.

Deploy the backend changes together; the new shared policy/serializer modules and read-router registration are required. No key rotation, token lifetime change, dependency upgrade or schema operation is part of this patch. Monitor authorization failures and response-validation errors without token/request-body logging. Keep MCP disabled.

Rollback is source/image-only: restore the preserved backend artifact and matching code as a reviewed unit. There is no database downgrade or data cleanup for this patch. Reverting reopens the original authorization and token-validation gaps, so restrict the affected routes during rollback and prefer a forward fix where practical. Do not use a broad working-tree reset or overwrite unrelated staged/committed work. Future revocation storage, once approved, must not be removed or rolled back in a way that resurrects revoked sessions.

**Readiness recommendation: NO-GO for the next acceptance gate and for Phase 2 MCP.** S05/S03 targeted regressions pass, but the independent audit found three failed authentication-related criteria and one blocked revocation criterion. Correct those gaps and execute the missing isolated integration checks before declaring Phase 1.1 accepted. The future delegated-authentication boundary and all applicable original findings also remain prerequisites for MCP.
