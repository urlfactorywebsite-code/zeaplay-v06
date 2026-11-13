# Phase 1.2 authentication security

Date: **11 November 2026, Asia/Calcutta**. Checkout: `F:\Projects\zeaplay-05\zea-play-08-05-26\zea-play`. HEAD at review: `b6a220a`, with the existing Phase 1.1 working changes preserved. This report describes local source and isolated tests; nothing was deployed. **Phase 2: NO-GO. Stop at Phase 1.2.**

| Issue | Status | Result |
|---|---|---|
| Tenant-change refresh validation | **PARTIAL** | Current tenant mismatch is **fixed and tested**: an A token cannot refresh while its user belongs to B. Durable invalidation across A->B->A remains blocked on persisted history/revision. |
| Presence JWT validation and profile separation | **FIXED**, isolated verification | Dedicated presence type, issuer, audience, expiry and identity validation; API/refresh credentials rejected; presence credentials rejected by REST. Client obtains/renews the correct profile. Full deployed transport is NOT RUN. |
| Durable session/token revocation | **BLOCKED pending approval** | Requires schema and token-contract changes. Implementation of this subsection stopped as requested. Design only below; no migration, revision/session field, revoke endpoint, rotation or reuse detector added. |
| Existing login/refresh and targeted regressions | **PASS**, tested scope | 64 Python methods, 45 Node tests and 46 frontend tests pass. Build passes. Passing lifecycle observations do not mean revocation works. |

The reference documents were reviewed: [feasibility report](../MCP_FEASIBILITY_REPORT.md), [original security findings](PHASE_1_SECURITY_REVIEW.md), [Phase 1.1 remediation/audit](PHASE_1_1_SECURITY_REMEDIATION.md), and [permission model](MCP_PERMISSION_MODEL.md). Earlier reports and evidence remain unchanged as historical records. This report supersedes their current-authentication conclusions only for the changes explicitly described here.

## 1. Verified root causes

1. `backend/app/routers/auth.py::refresh_token` previously decoded into `TokenPayload`, which has no tenant field, then looked up only the subject and minted claims from the current user. That could retarget an old tenant's refresh credential into a new tenant. Active-status rejection already existed from Phase 1.1 and is retained.
2. `presence-server/src/server.js::authenticateSocket` used signature verification without mandatory expiry, checked token type only when truthy, accepted the ordinary `access` profile, and used a `default` tenant fallback. It did not enforce an issuer/audience contract. The independent Phase 1.1 audit reproduced missing-expiry and missing/null/empty-type acceptance.
3. `GET /auth/presence-token` issued an ordinary access JWT with a `presence` scope label. The actual frontend `usePresence` bypassed that endpoint and sent its stored API access token. Fixing only the Node verifier would therefore break the current client.
4. No authentication session/family/token registry, monotonic authentication revision, refresh replay history or durable token denylist exists in the inspected models/migrations. The `revoked_at` field found in `PushSubscription` governs push-device subscriptions, not login credentials. Reporting `session_id` values also are not authentication sessions. Logout records an audit event. Password updates replace the password hash without invalidating JWTs. Profile `updated_at`, optional Redis and process memory cannot safely substitute for durable authentication state.

## 2. Authentication changes

### Refresh membership binding

The refresh handler now validates the signature/type/expiry with the existing common decoder, retains `TokenPayload` validation (including malformed scopes), and requires a nonempty string subject and signed UUID tenant. A conflicting `user_id` identity alias is rejected. Missing/malformed tenant claims return 401; no default or client-provided tenant is used.

The handler loads the current user with a row lock and `populate_existing`, checks the signed tenant against `User.tenant_id`, and rejects mismatch with 401. It retains inactive-user 403 and existing missing-user 404 behavior. It derives new roles and tenant claims only from the current database row. PostgreSQL row locking is present to serialize the read with membership/status writers; actual PostgreSQL concurrent execution is **NOT RUN**. This is not a session revocation mechanism.

Valid current-tenant login and refresh keep their response shapes, signing configuration, normal lifetime and refresh reuse behavior. Existing API/access/refresh issuer and decoder functions are AST-equivalent to the pre-Phase-1.2 snapshot; the Phase 1.1 expiry fix is retained.

**Limit:** current membership is insufficient to remember past membership. A->B rejects the old A credential; B->A can make the same still-unexpired A credential valid again. Same-tenant deactivation denies access/refresh while inactive, but reactivation also restores unrevoked credentials. Both observations are executed tests and explicit remaining gaps, not passing revocation tests.

### Presence-only credentials

`create_presence_token` now emits a separate signed profile. The external `TokenMintResponse` envelope remains `access_token`, `token_type: bearer`, `scopes`, timestamps, subject and label, so the client API response shape stays compatible. The signed JWT type is distinct from that envelope's bearer transport type.

| Claim/control | Normal REST access | Refresh | Presence |
|---|---|---|---|
| Signed `token_type` | `access` | `refresh` | `presence` |
| Signature/algorithm | Existing access key and configured algorithm | Existing refresh key and configured algorithm | Existing access signing key, matched by `PRESENCE_JWT_SECRET`; configured algorithm |
| Expiry | Mandatory integer, future | Mandatory integer, future | Mandatory safe integer, future; exact boundary denied |
| Subject/tenant | Existing live user/tenant dependency | Validated signed subject/tenant versus locked current user | Nonempty trimmed string subject and UUID tenant; no identity alias/default tenant fallback |
| Issuer/audience | Existing contract unchanged; no new required claims | Existing contract unchanged; no new required claims | Required `iss: zeaplay`, exact string `aud: zeaplay-presence` |
| Issued-at/lifetime | Existing contract unchanged | Existing contract unchanged | Mandatory integer `iat`, not in future; `exp > iat`, at most 3,600 seconds |
| Roles/scopes | Database roles remain authority; existing scope-label behavior unchanged | New claims use database role | Known role strings and exactly `scopes: [presence]`; these do not create new business permissions |

The old contract had no issuer/audience values to preserve. The two constants above are a new **presence-only** contract coordinated between its issuer and verifier, not a new OAuth issuer, discovery service or MCP integration. Normal login/refresh is not silently migrated to that profile. Presence audience arrays, extra scopes, unexpected claims/header extensions, malformed claim types, wrong signature/algorithm and insecure legacy profiles are denied. There is no insecure compatibility fallback.

Node validation is extracted into `presence-server/src/auth.js` and registered by the existing server. The actual `jsonwebtoken` library verifies signatures, issuer, audience and expiry; explicit checks enforce the stricter claim schema. No secrets or environment values are hardcoded in the implementation. Tests supply random synthetic signing keys. Existing shared signing-key trust remains a limitation: separate profiles do not isolate a compromised signer that possesses the API key.

### Presence connection lifecycle

The frontend calls the already existing authenticated presence-token endpoint, retains the credential in memory, opens Socket.IO with it, and renews 30 seconds before its one-hour expiry. Connection failures/disconnects trigger reacquisition after a five-second cooldown; API tokens are never a fallback. A normal API refresh preserves the client identity, while logout/account/tenant changes and canceled asynchronous requests discard stale credential responses. Timers/listeners are cleaned up on renewal and unmount. Existing presence events and 15-second pings are retained.

The server closes idle connections at signed expiry and checks expiry on incoming packets even if the timer is delayed. This is expiry enforcement, **not durable revocation**. A credential already minted for presence does not receive a live database status/membership check in Node: it can remain usable until its expiry after deactivation, password change or a tenant move. Backend issuance/renewal does check current authentication. Immediate revocation of existing presence credentials/streams requires the blocked design below.

## 3. Files changed in Phase 1.2

| File | Purpose |
|---|---|
| `backend/app/auth.py` | Add dedicated presence issuer/constants; retain existing API/refresh helpers. |
| `backend/app/routers/auth.py` | Enforce refresh tenant membership; issue the dedicated presence profile. |
| `presence-server/src/auth.js` (new) | Strict, independently testable presence authenticator and connection-expiry guard. |
| `presence-server/src/server.js` | Register the authenticator and expiry guard; preserve business event handlers. |
| `frontend/services/presenceConnection.ts` (new) | Credential acquisition, renewal/retry and asynchronous identity/cleanup guards. |
| `frontend/hooks/usePresence.ts` | Use the dedicated credential lifecycle and retain existing UI/event behavior. |
| `backend/security_tests/run_mcp_phase1_2.py`, `mcp_phase1_2_cases.py` (new) | Isolated API regressions and Python-to-Node credential fixture handoff. |
| `presence-server/test/auth.test.mjs` (new) | Real verifier/profile and session-expiry assertions. |
| `frontend/test/presence-auth.test.ts` (new) | Acquisition, renewal, logout/account races and failure/reconnect tests. |
| `presence-server/README.md` | Document the new credential contract, rollout requirement and revocation limit. |
| `docs/mcp/PHASE_1_2_AUTH_SECURITY.md` (new) | This report and migration design. |
| `backend/checks/mcp-phase1-2-*` (new) | Test/build output and scope-preservation evidence. |

Existing dirty/staged work in `main.py`, task/group/WebSocket code, prior tests/docs and audit artifacts was preserved. No ORM model, migration, dependency manifest, lockfile, signing key, normal token lifetime, unrelated feature or production configuration was changed. No commit, staging, reset, push, deployment or MCP implementation was performed.

## 4. Executed tests and results

| Verification | Result / evidence |
|---|---|
| Python real-handler suite | **64 PASS**, 29.812 seconds, exit 0. Includes 52 retained Phase 1/1.1 methods plus 12 Phase 1.2 methods. [Combined authentication output](../../backend/checks/mcp-phase1-2-auth.txt). |
| Node presence suite | **45 PASS**, 168.5835 ms, exit 0. Real Python-issued JWTs verified by the production authenticator with real `jsonwebtoken@9.0.2`; malformed profiles/signatures, API/refresh rejection, packet/idle expiry and source wiring checks. Same linked output. |
| Frontend suite | **46 PASS** (9 new presence lifecycle tests + 37 existing task/cache/navigation/history/workflow/reward tests), 646.3158 ms, exit 0. [Frontend output](../../backend/checks/mcp-phase1-2-frontend.txt). |
| Frontend production compilation | **PASS**, Vite 6.4.2, 12.61 seconds, output in a new owned temporary directory. Existing dependency `eval` and large-bundle warnings remain. [Build output](../../backend/checks/mcp-phase1-2-build.txt). |
| Targeted TypeScript | **PASS**, zero diagnostics for the new connection module and its test under strict compiler settings. This is not a full-repository TypeScript-clean claim. [Static-check output](../../backend/checks/mcp-phase1-2-static.txt). |
| Static checks | Targeted Ruff F/E9, Node syntax checks and `git diff --check` PASS. No full-repository lint-clean claim. Same linked static-check output. |
| Preservation | SHA-256 comparison of **1,712 unique existing files**, including **9 local database files**, plus the Git index: only the five expected existing source/README files changed. Two new runtime modules are separately hashed. Prior API/refresh helper ASTs are unchanged. [Scope manifest](../../backend/checks/mcp-phase1-2-scope.json). |
| NOT RUN | Explicitly revoked-token rejection, refresh rotation/replay/family invalidation, PostgreSQL concurrency, live browser/socket transport, installed backend lifecycle, full Socket.IO/Redis adapter/chat integration, actual proxy/TLS, external providers and production sessions. No revocation implementation or verified disposable full runtime was used; the local test tree has no installed Socket.IO server package. |

The retained suite excludes exactly one obsolete Phase 1.1 assertion: it required a presence token to decode as ordinary API access. The original file is preserved. The new tests replace that expectation with explicit profile-separation and legitimate-issuer tests. Historical Phase 1.1 audit scripts that assert the old defects are not release gates for this patch and were not edited to conceal their findings.

Python uses the previously reviewed guards before application imports: fresh process, sanitized environment, empty temporary working directory, random keys, in-memory SQLite, blocked direct/file/other-dialect database access, blocked external network/process access, and forbidden application startup/legacy-test/migration imports. Real handlers, database identities, authorization, transactions and serializers execute. Existing publication/webhook/asynchronous audit transport substitutions are confined to the fixture; real external delivery is not certified.

The launcher passes actual Python-issued credentials to Node only through an owned temporary file, then deletes the scratch directory. Credentials/signing material are not printed or committed. Node tests load the production auth module without starting the server, use the locally installed JWT library, and run with network/listener denial. Frontend tests use the same network guard and controlled clocks/sockets. The build also uses network denial and an external temporary output directory; the installed frontend bundle is not replaced.

Reproduce from the repository root:

```powershell
.\backend\venv\Scripts\python.exe backend/security_tests/run_mcp_phase1_2.py
```

From `frontend`:

```powershell
node --require ../backend/security_tests/phase1_1_network_guard.cjs --test --test-isolation=none --import tsx test/presence-auth.test.ts test/task-query-cache.test.ts test/task-navigation.test.ts test/task-information.test.ts test/task-activity.test.ts test/subtask-workflow.test.ts test/subtask-reward-summary.test.ts
```

### Requested acceptance criteria

| # | Criterion | Evidence-based disposition |
|---|---|---|
| 1 | Old refresh tokens fail after tenant changes | **PARTIAL overall**: A->B denial PASS on both aliases; new-tenant login/current refresh PASS. A->B->A permanent invalidation is BLOCKED on durable state. |
| 2 | Missing-expiry presence tokens rejected | **PASS**, executed against the real verifier; no authenticated socket identity is attached. |
| 3 | Missing-type presence tokens rejected | **PASS**, including omitted/null/empty/wrong type and ordinary API/refresh tokens. |
| 4 | Valid presence sessions continue functioning | **PASS for isolated authentication/session/client lifecycle**: Python-issued credential accepted, valid packets admitted, renewal/reconnect tested. Full browser/Socket.IO/Redis runtime is **NOT RUN**, not production-certified. |
| 5 | Existing valid login/refresh remains operational | **PASS**, JSON/form login, both aliases, real password hashes, resource access after refresh, inactive denial, current database role, stale/malformed/expired credential rejection. |
| 6 | All new security tests pass | **PASS** for all executed new assertions; launcher and Node exits 0. Open-risk observations are deliberately labeled and do not close revocation. |
| 7 | Revocation verified or documented as blocked | **Documented BLOCKED as permitted by the request**; design is complete below. Revoked-token rejection is **NOT RUN**. |
| 8 | No production data/schema modified | **PASS for this work's scope/actions**: no production connection, no migration/model changes; protected local DB hashes unchanged. Remote production state was not inspected, so unrelated external activity is not attested. |

## 5. Durable revocation: design only, approval required

The request says: **"If implementing persistent revocation requires a database schema migration or changes to production token contracts, STOP implementation of that subsection."** Both are necessary. No implementation of this subsection was started. The following is a reviewable proposal, not executable migration code or authorization to apply it.

### Proposed schema and token contract

- Add a monotonic `users.auth_epoch` integer, initially zero, with constraints preventing negative values. It follows the stable user ID across tenant moves; do not reset it on reactivation or when returning to an earlier tenant. Do not use mutable profile timestamps or password hashes as a token-version surrogate.
- Add `auth_sessions`: random session/family ID, user ID, immutable issuing tenant ID, issuing epoch, created/absolute-expiry/last-used timestamps, revoked timestamp/reason and optional minimal device label. Keep tenant ownership on historical sessions even after the user moves. Do not use a cascading foreign key to the user's mutable current-tenant value that would rewrite or destroy revocation history.
- Add `auth_refresh_tokens`: random token ID, session/family ID, cryptographic digest of the token, parent/replacement token IDs, issued/expiry/consumed/revoked timestamps. Unique digest and token ID constraints; foreign keys and indexes for family lookup and expiry cleanup. Store digests, not raw bearer/refresh credentials.
- For supported selective revocation of legacy credentials without a session/token ID, add an explicitly approved digest denylist through token expiry, or choose documented revoke-all behavior. A user epoch alone cannot selectively revoke one old session.
- New access, refresh and presence profiles carry signed session ID, token ID, epoch and issue time. Tenant remains explicitly bound. The normal API and strict presence claim contracts must be updated together. Session/family admission checks happen on access **and refresh**, not merely at token issuance. This is a production token-contract change and is therefore deferred.

### Lifecycle decisions

| Event/capability | Current state | Proposed approved behavior |
|---|---|---|
| Refresh rotation | Old token is reusable; this compatibility remains tested | Transactionally consume one refresh token and create its successor; stable session/family absolute expiry. |
| Refresh reuse detection | None | A replay of a consumed token revokes the affected family and requires fresh authentication; never issue another valid branch silently. |
| Session/token identifiers | Absent from normal login tokens | Random IDs bound to user, immutable tenant, session/family and epoch; token IDs unique. |
| Family revocation | None | Revoke session/family and enforce on every profile/replica; preserve consumed-token tombstones for replay detection. |
| Logout | Audit event only | Revoke the current session/family. Decide legacy selective-digest versus explicit logout-all semantics; do not disguise global logout as selective logout. |
| Tenant move | Current-mismatch refresh denied | In one transaction lock user, increment epoch, revoke old sessions/families and change tenant. Never revive prior-tenant sessions on a return move. |
| Deactivation | Live REST/refresh denial; Node credential can survive until expiry | Increment epoch and revoke sessions in the same transaction as status change. |
| Reactivation | Previously unexpired, unrevoked credentials work again | Change status only; never decrement/reset epoch or clear revocations. Require newly authenticated sessions. |
| Password change/reset | Hash changes; no durable invalidation | Increment epoch/revoke sessions atomically with password update. Product must decide whether to create a new session for the initiating client after proof. |
| Expired-token cleanup | No persistent auth-token records exist | Delete expired session/token records in bounded batches only after replay/revocation retention requirements are satisfied. Never delete/reset user epoch to reclaim storage. |

### Concurrent refresh and revocation

Use a consistent lock order: user -> session/family -> refresh token. Within one database transaction, re-read current tenant/status/epoch, verify unrevoked/nonexpired family and unconsumed digest, mark consumed, create the successor, and commit before returning it. Deactivation, password change, tenant move and revoke-all use the same user lock/epoch authority. A refresh must not mint a credential that survives a revocation committed before its admission; if refresh wins first, the subsequent epoch/session revocation must invalidate the newly minted token too.

The proposed default is strict single use with no permissive replay grace. Coordinate browser refresh calls across tabs and within each client before enabling rotation; otherwise legitimate concurrent retries can look like reuse and force reauthentication. An idempotent retry alternative requires an explicit bounded, client-bound replay key and a reviewed secure response-recovery design. Do not keep raw refresh tokens indefinitely or issue multiple successors to solve retries. This rollout behavior requires approval because it changes current reusable-refresh semantics.

### Multi-instance, Redis and presence

The database is authoritative. Every replica checks the same epoch/session authority; deny admission when authoritative state cannot be checked. An availability response may be 503 rather than pretending an invalid credential, but it must not grant access. Redis can distribute invalidation hints; process caches or Redis outages must never resurrect a token or supply an indefinite allow decision.

Presence requires a trusted backend admission/revalidation path or equivalent reviewed access to durable session authority. It must apply revocation to handshakes and established connections/delivery, with clear race semantics, not just trust its new signed epoch without looking up the current value. Redis invalidation messages improve latency but are not proof of current authorization. Tests must cover lost messages, restarts and unavailable authorities. No introspection service or new network trust boundary is implemented here.

### Existing-session handling and safe rollout

1. Approve the schema, credential lifetimes, logout semantics, retry policy, retention and user-impact plan. Back up the normal database and record source/image/schema versions. Rehearse only on a verified disposable PostgreSQL copy with synthetic identities before any production approval.
2. Use an additive migration. Preserve existing user/session data; no destructive backfill or guessed ownership. Initialize active users to epoch zero only under the approved legacy policy; initialize already inactive users to a nonzero epoch so reactivation cannot revive pre-migration credentials. Investigate known prior tenant/password changes separately. Historical changes cannot safely be inferred from generic `updated_at`.
3. Deploy epoch-aware readers to every backend/presence replica before enabling new issuers and revocation writers. For an approved bounded compatibility period, a valid legacy token without epoch/session may map to epoch zero **only while the durable user epoch remains zero**. A legacy path must still enforce expiry, exact token profile, tenant and active status. It must never override a nonzero epoch or an explicit digest denial.
4. Move login and refresh issuance to sessions/families and new profile claims, coordinating frontend single-flight behavior and Node claim allowlists. Enable revocation transitions only when no old verifier can bypass them. No unconditional rollback to old readers is safe after this point.
5. End legacy compatibility at an approved deadline. Existing minted API tokens can have unusually long lifetimes; do not silently promise transparent migration or retain legacy acceptance for years. A targeted reauthentication/reissue plan may be necessary. If historical ownership/revocation cannot be established safely, require an explicit policy decision rather than fabricating state.

### Cleanup and rollback constraints

Retain consumed refresh-token digests/tombstones through family absolute expiry plus the chosen replay/clock window; retain any selective legacy denial through that token's expiry. Do not remove a revocation while a corresponding credential can still be accepted. Handle very long-lived API tokens by the approved epoch/cutoff policy. Keep minimal security-event metadata under the agreed retention policy; never export raw credentials.

Rollback after revocation activation must preserve the database authority, epochs, session revocations and new readers. Roll back presentation/non-auth code or backport a compatible verifier; otherwise suspend affected authentication surfaces until a safe fix exists. Do not downgrade/drop the new tables or restore pre-revocation state that resurrects sessions. Rehearse forward recovery, database restore and mixed-version fail-closed behavior before deployment approval.

### Required future security acceptance tests — all NOT RUN

- Explicit revoke -> access/refresh/presence denied -> user reactivated -> still denied; new authenticated login works.
- A->B->A and password change/reset never restore old credentials; cross-tenant revoke attempts denied.
- Rotation single use, consumed-token replay, family containment, concurrent refresh, refresh versus logout/revoke/deactivation/move and retry behavior.
- Same results across replicas and after process/database restart; Redis loss/missed invalidation cannot grant access; authority outage fails closed.
- Existing active legacy session compatibility, nonzero-epoch denial, initially inactive migration, legacy cutoff and long-lived API-token handling.
- Presence handshake, established streams and outgoing delivery stop under the approved revocation race contract.
- Cleanup cannot resurrect tokens; backup/restore/rollback preserve revocations; no raw secrets in logs, database exports or tests.

## 6. Compatibility, deployment and rollback

Normal valid API login/refresh sessions are not globally invalidated by Phase 1.2. Stale-tenant refreshes now return 401; malformed/missing-tenant credentials receive no fallback. A legitimate user who moves to another tenant must authenticate for that tenant. Inactive current-tenant users retain 403. Browser session storage and normal token lifetimes are unchanged.

The presence protocol changes intentionally: prior API-style presence tokens and old clients that send API tokens are rejected. The updated client obtains the new profile using its valid existing API session, so it does not need a global forced logout. Deployment must coordinate backend issuer, Node verifier and frontend; mixed old/new workers can produce predictable presence authentication failures. Use a controlled presence maintenance/drain or a verified coordinated cutover, then have clients load the updated bundle. Keep signing configuration aligned and clocks synchronized; no skew tolerance was introduced. No dependency installation, key rotation or schema operation is needed for the implemented patch.

Before any separately approved deployment, validate the exact artifact in a disposable full stack: real Socket.IO connection/renewal, Redis adapter, presence events/chat compatibility, browser login/refresh/logout/account switching, actual proxy aliases/TLS and PostgreSQL membership races. The repository has existing startup schema helpers; review schema readiness before starting a backend even though this patch adds no migration. Preserve previous source/image digests and take normal backups. Deployment is **NOT PERFORMED** here.

Rollback is a reviewed source/image operation, never a broad working-tree reset. Reverting presence issuer/client/verifier independently can break connectivity; reverting all of them reopens the original validation flaws. Prefer a forward fix, or keep presence disabled while recovering. Retain the refresh tenant check. There is no Phase 1.2 database downgrade. Do not use rollback guidance as authorization to deploy or modify production.

## 7. Remaining blockers and recommendation

Durable revocation, tenant-return/session invalidation, logout/password-change invalidation, refresh rotation/reuse detection and immediate presence revocation remain blocked on the approved design. PostgreSQL concurrency and full transport/browser integration remain unverified. Shared signing-key exposure, long-lived API tokens and ordinary scope labels are not solved by a presence audience. Original S01/S02/S04/S06/S09/S10/S11 findings and future delegated authentication requirements remain outside this patch.

**NO-GO for Phase 2.** The current-tenant refresh and presence-profile repairs are implemented and pass their isolated tests. Complete the approved revocation work and outstanding security/integration gates before advancing. No MCP server, Settings UI or Phase 2 implementation was created.
