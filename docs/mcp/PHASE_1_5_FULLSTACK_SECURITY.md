# Phase 1.5: Department tenancy assessment and full-stack authentication

Date: **12 November 2026 (Asia/Calcutta)**. Checkout: `F:\Projects\zeaplay-05\zea-play-08-05-26\zea-play`, existing Phase 1.1–1.4 working changes preserved.

**Decision: NO-GO for the next OAuth/delegation implementation stage.** The authentication and representative authorization results below are local, disposable-stack evidence. Department isolation remains **BLOCKED pending product/data-ownership approval**: an authenticated tenant B Owner can rename/delete a department used by tenant A. No Department schema, business route, customer data, OAuth infrastructure, MCP implementation, or MCP Settings UI was changed.

The five requested reference documents were reviewed: [feasibility](../MCP_FEASIBILITY_REPORT.md), [security review](PHASE_1_SECURITY_REVIEW.md), [permission model](MCP_PERMISSION_MODEL.md), [session revocation](PHASE_1_3_SESSION_REVOCATION.md), and [tenant security](PHASE_1_4_TENANT_SECURITY.md). Findings were checked against current source and the actual disposable runtime; older documentation is not current test evidence.

## Independent refinement audit — 12 November 2026

**Final disposition: NO-GO for OAuth/delegation. Backend authentication/revocation and the additional expiry/presence checks pass; repeatable multi-tab recovery remains BLOCKED by an unexplained B02 timeout in the audit's complete rerun. Complete application tenant isolation also remains BLOCKED by the department ownership decision and the adjacent media review.** This section supersedes any broader interpretation of the implementation-stage PASS table below. A passing diagnostic confirms an exposure; it does not close the security finding.

The audit independently read the Phase 1.5 launcher, bootstrap, browser assertions, actual application session/refresh/presence implementation, Department model/CRUD, tenant predicates, migration sources and recorded logs. All three harness hashes recorded in the original `scope-final.json` matched the files at audit start. The original 14-case browser result and 51/53-method PostgreSQL logs are genuine completed results within their stated limits; initial failed R02 and audit-pagination assertions were retained and their corrections match current policies. [Hashes of the reviewed original evidence](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/reviewed-evidence-sha256.json) identify that input without overwriting it.

### Verified defect and evidence refinements

| ID | Independent finding | Disposition |
|---|---|---|
| **P15-A1 — false success when zero tests selected** | Running the real browser launcher with `ZEA_PHASE15_FILTER=^NO_MATCH_AUDIT_REPRODUCTION$` executed zero scenarios and exited 0 with `pass:0,fail:0`. | **Corrected.** The harness now writes execution mode/completeness/full-suite metadata and exits 2 for zero selected cases or an incomplete requested full suite. The same zero-match run now exits 2. [Before/after reproduction](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/zero-selection-reproduction.json). This defect does not invalidate the prior explicitly complete 14-case result. |
| **P15-A2 — presence disconnect attribution gap** | B07 observes a live connection closing and Redis membership disappearing, but its React client can also close the socket after an HTTP denial. It does not independently establish server-initiated idle revocation. | **Evidence strengthened.** A01 uses an additional native browser page containing only the real Socket.IO client, with reconnection disabled and no React/presence renewal or application packets. After real HTTP logout the server closes it with `io server disconnect` in **14,930 ms**. Presence validation returns 401 and reconnecting with the same credential fails. No presence runtime change was necessary. |
| **P15-A3 — absolute session expiry coverage gap** | B02 proves access expiry and successful rotation; it ends before the two-minute absolute session lifetime. It did not establish the frontend's behavior once refresh is also expired. | **Evidence strengthened.** A02 waits the actual two-minute session/presence expiry without changing the clock or token. The detached presence socket receives server disconnect at the signed expiry (measured offset **−1 ms**, within clock/timer precision); old access/refresh/presence authority requests return 401. Reload runs the actual React auth provider/Axios interceptor, routes to login and clears both stored tokens. Expired presence reconnect fails. |
| **P15-A4 — login helper races the landing redirect** | The initial independent 14-case rerun completed 13 PASS / 1 FAIL: B07 timed out before presence connected. The failure screenshot showed Tasks, and presence logs showed no Manager socket. `Login.tsx` navigates to `/`, then `App.tsx` redirects its index to `/tasks`; the helper accepted the intermediate `/` and immediately navigated to Users, allowing the pending index redirect to overwrite it. | **Corrected in the test helper.** Wait for a non-root authenticated landing URL before issuing the next test navigation. No delay increase, retry around the security assertion, route override or application change. [Failed full rerun](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/browser-audit-rerun.json) and screenshot are retained; [focused B07 rerun](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/browser-B07-corrected.json) passes. The final full suite below uses the corrected helper. |
| **P15-A5 — intermittent B02 recovery timeout** | The next complete rerun, with P15-A4 corrected, completed **13 PASS / 1 FAIL**: B02 timed out after two native lock waiters were observed and released. The session read after failure showed exactly two refresh rows, one consumed predecessor and an unrevoked successor family; the HTTP trace includes one successful rotation in this scenario. The earlier generic timeout did not identify whether token storage, route recovery or restored presence was the failed condition. | **BLOCKED, not explained away.** Added named B02 stages and safe failure diagnostics (route, session/expiry metadata, lock state, persisted counters; no bearer tokens). The [focused diagnostic rerun](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/browser-B02-diagnostic.json) passed in 98,738 ms, but does not establish a root cause or erase the [complete-run failure](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/browser-audit-final.json). [Persisted state](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/B02-session-diagnostic.json) supports atomic rotation, not a blanket frontend recovery PASS. No speculative runtime correction was made. |

The independent tests are in [mcp_phase1_5_audit.cjs](../../backend/security_tests/mcp_phase1_5_audit.cjs). They create separate synthetic users through authenticated user CRUD, submit their passwords through the real login form and use issued credentials without editing storage, overriding backend dependencies or intercepting authentication responses. Injecting the installed Socket.IO client into the detached page isolates server behavior; it does not mock the transport or authority. [Independent browser observations](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/independent-browser.json) contain timings and statuses, excluding bearer tokens/passwords.

No duplicate issuance, accepted replay, revived revoked session or tenant round-trip bypass was reproduced. The B02 timeout remains unclassified between browser/harness sequencing and frontend recovery; consistent multi-tab readiness is therefore not certified. Both executable corrections and added diagnostics are in the Phase 1.5 test harness. Department ownership, deletion policy and historical mapping were not guessed or implemented.

### Independent criterion-by-criterion assessment

| # | Audit requirement | Result | Evidence and limit |
|---|---|---|---|
| 1 | Department conclusions match current source | **PASS** | Global `id/name` model; unfiltered CRUD; string user/template/media FKs; UUID ticket/SLA fields without Department FK. D01 reproduces cross-tenant mutation and orphan retention. |
| 2 | Ownership assumptions explicit | **PASS** | Option A remains a recommendation. Shared/unknown ownership, Manager powers, IDs/names, archive/delete, historical attribution and mapping all require approval. |
| 3 | No unapproved Department migration executed | **PASS** | No new/modified migration or Department runtime file; fixture bootstrap runs only existing incremental auth/audit revisions against asserted-empty disposable PostgreSQL. Existing DB schema/data were not inspected or changed. |
| 4 | Full-stack tests disposable and isolated | **PASS** | Fresh five-container stack, new internal network, generated fixture credentials, tmpfs PG/Redis, read-only source mounts, loopback-only Nginx, guards. [Actual topology review](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/isolation-review.json). |
| 5 | Actual backend browser authentication | **PASS** | Real React login/password verifier, signed credentials and PostgreSQL session records; no authentication/clock mocks in browser suites. |
| 6 | Refresh rotation under concurrency | **BLOCKED — consistent browser recovery** | B09 and PostgreSQL contention/rollback checks PASS; observed rotation remains one predecessor/one successor. B02 passes in the first complete audit run and focused diagnostic run, but times out during recovery in the second complete run. P15-A5 remains unresolved; do not certify repeatable native multi-tab recovery from these mixed results. |
| 7 | Revoked sessions stay invalid | **PASS** | B01/B03/B04/B06/B09/B11, fresh-interpreter regression and A01; replay/deactivation/reactivation/password/role changes do not restore old credentials. |
| 8 | Tenant A → B → A cannot revive credentials | **PASS** | B05 and PostgreSQL trigger tests verify increasing epochs and rejection of both old A and B credentials after return. Tenant movement is a guarded fixture transaction, not a claim of a product tenant-switch UI. |
| 9 | Presence disconnect/expiry follows policy | **PASS** | A01 independently verifies server revocation under 18 seconds in this local measurement; A02 verifies natural expiry and denied reuse. B02/B07 verify real React renewal/reconnect and Redis. Runtime poll/timeout targets still assume a responsive event loop; idle chat/ticket channels are not certified. |
| 10 | Frontend handles expiry | **PASS — absolute-expiry denial** | A02 verifies absolute expiry, login redirect and cleared token storage on reload/next auth request; replay/status/password cases also deny and redirect. B02's repeated multi-tab recovery remains requirement 6 BLOCKED. No claim of immediate offline/background-tab UI erasure. |
| 11 | Cross-tenant restrictions remain effective | **BLOCKED — complete isolation** | Repaired task/group/ticket/transfer/audit/notice/cache/observer cases pass R01/R02 and retained regressions. Department CRUD still crosses tenants; the media-list source gap remains. Passing selected routes cannot certify all application tenant isolation. |
| 12 | Existing task/ticket functionality preserved | **PASS — targeted** | Positive/negative grouped assignment, transfer, ticket membership/workflow/approval and existing business regressions pass. No application runtime correction; exhaustive product/UI acceptance is NOT RUN. |
| 13 | Cleanup limited to resources created for this audit | **PASS** | Owned full-stack names/labels checked before removal; helper PostgreSQL/transport resources created for this audit also use fresh ownership labels. [Created resource inventory](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/created-resources-audit.json) and final before/after scope comparison. Prior abandoned test containers remain untouched. |
| 14 | No production DB/application service modified | **PASS for this audit** | Docker was already running; audit did not start/restart installed services, connect an installed DB, alter credentials, apply existing-DB migrations or deploy. Preexisting container IDs/states, volumes, networks and Git index are compared before/after. The earlier engine-start auto-resumption of Paradise is separately disclosed below; pre-engine preservation cannot be certified retrospectively. |

### Executed tests by level

Audit run: `d8958a4815604dd4adf00d556cf8c02b`. Evidence is separate from the original run.

| Level | Executed result | Scope |
|---|---|---|
| **Unit** | **20 PASS** frontend refresh/presence coordinator tests; **60 PASS** Node presence profile/deadline checks in retained auth launcher | Controlled storage/locks, fake socket/clock/authority cases. These are not browser acceptance. [Frontend units](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/frontend-units.txt). |
| **Component integration** | **5 PASS** | Real Axios/API/token-storage code with synthetic adapter and network denied. [Component log](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/frontend-components.txt); explicitly not live backend or browser. |
| **PostgreSQL integration/concurrency/migration** | **51 auth methods PASS** (8 independent + 43 retained), fresh-process revocation PASS; **53 tenant/business methods PASS**, including one Department diagnostic | Real row locks/transactions/triggers and actual incremental revision upgrade/downgrade checks on fresh helper databases. Suites overlap. [Auth rerun](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/auth-regressions-audit.txt), [tenant rerun](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/tenant-regressions-audit.txt). No full historical migration-chain certification. |
| **Socket transport integration** | **1 PASS** in auth launcher | Real Socket.IO client/server with controlled authority, network-disabled container. Separate from live A01/A02/B07 authority. |
| **Real browser/full stack** | **16 distinct scenarios exercised.** Two complete 14-case runs each report **13 PASS / 1 FAIL**; focused B07 and B02 runs each PASS; independent A01/A02 **2 PASS**. **No clean complete audit run is claimed.** | Current React/Nginx/FastAPI/PostgreSQL/Redis/presence; real wall-clock expiry and native Web Locks. [First complete run](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/browser-audit-rerun.json), [second complete run](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/browser-audit-final.json), [independent two-case result](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/independent-browser.json). Successful D01 reproduces BLOCKED Department isolation. P15-A4 is corrected; P15-A5 remains unresolved. |
| **Harness negative check** | Zero-match filter changes from exit 0 to **exit 2** | Intentional incomplete run; not counted as a failed application security scenario or browser-authentication test. |
| **Build/static/scope** | Isolated current Vite build, Node syntax, `git diff --check`, artifact secret scan and resource/file preservation checks | [Build](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/build.txt), [verification](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/verification-audit.json), final audit scope artifact. |

**Not executed:** production/TLS/deployed image equivalence; production database ownership census or restore; entire historical Alembic chain; real Department migration; external SMTP/push/webhook/storage/provider delivery; media presign/foreign-object HTTP flow; production performance/Redis outage/failover; exhaustive task/ticket UI regression; non-Chromium/no-Web-Locks/offline browser cases; idle chat/ticket socket-close guarantees; OAuth/MCP interoperability. Existing blocked CDN/Tailwind errors remain recorded, so there is no clean-console or visual-acceptance claim.

### Remaining decisions, migration risks and stage gate

**Department isolation remains BLOCKED.** Decide tenant ownership versus immutable templates plus tenant instances versus expressly restricted global metadata. Under recommended Option A, approve tenant administration rights, shared-ID splitting, normalized-name policy, deletion/archive behavior and an explicit `(legacy ID, tenant ID)` mapping before implementation. The currently global mutation behavior is a reproduced exposure; the policy-dependent repair is not part of this refinement.

Migration review confirms the major risks: legacy non-UUID IDs cannot be cast into ticket UUID columns; existing global-name uniqueness conflicts with tenant clones; current user/template/media `SET NULL` behavior differs from orphan-prone ticket/SLA fields; composite FKs need compatible types and must not null required tenant IDs; current identity does not prove historical ownership. Preserve ambiguous rows and audit attribution. Require a restored-copy rehearsal, bounded additive expansion/backfill/constraint validation, coordinated reader/writer/worker/import cutover and a rollback that retains isolation. A downgrade to global readers or merging independently edited tenant records is unsafe. Section 7 remains a design proposal, not an approved executable migration.

**Authentication readiness:** backend atomic rotation/durable revocation, tenant invalidation, absolute-expiry denial and independently measured server presence revocation/expiry PASS. **Consistent native multi-tab frontend recovery remains BLOCKED (P15-A5).** No application authentication change was made without a verified root cause. **OAuth/delegation implementation: NO-GO** while this browser gate, the ownership decision and media authorization review remain open. Dedicated issuer/audience/client/consent/grant/scope enforcement is still unimplemented and was not introduced here.

Audit changes are limited to this report, the completeness/landing-wait corrections and B02 diagnostics in `mcp_phase1_5_browser.cjs`, the new independent browser assertions in `mcp_phase1_5_audit.cjs`, and new evidence. Application runtime source, Department schema, existing migrations, Compose files, dependency manifests, credentials and staged work are preserved. See [final audit scope](../../backend/checks/phase1-5-d8958a4815604dd4adf00d556cf8c02b/scope-audit-final.json). Stop after refinement.

## 1. Department architecture findings

### Ownership and exposed operations

| Surface | Verified current behavior | Security/compatibility consequence |
|---|---|---|
| `backend/app/models.py::Department` | Only string `id` primary key and globally unique `name`; no `tenant_id`, owner, membership mapping, or archive state | Departments are globally shared operational records, not tenant-owned records. A UUID-looking ID conveys no ownership. |
| `routers/departments.py` | Active-user GET selects every Department. POST duplicate-name lookup, PATCH lookup, and DELETE lookup are global. Writes use `get_current_admin`, which includes Manager/Admin/Owner. The application navigation gate can restrict a route but supplies no department ownership predicate. | Tenant roles are not platform authority. Both `/departments` and mounted `/api/departments` use this router. Catalog names/IDs, duplicate-name errors, rename and deletion cross the intended tenant boundary. |
| User CRUD and serialization | `users.department_id` is nullable `VARCHAR(36)` with FK to `departments.id`, `ON DELETE SET NULL`. Create checks existence only; update assigns the ID subject to user-management permissions. User queries themselves have tenant predicates. | Both tenants can associate users with the same ID. User responses and directory/report labels expose the shared name. Deleting a shared department removes memberships in every tenant referencing it. |
| Registration / company creation | `routers/auth.py::_derive_tenant_id` accepts employer UUID or derives UUID5 from employer text. Registration locks and refuses an existing tenant, then stores supplied `department_id`. Authenticated `/users` creation uses the actor's tenant. No managed Company/Tenant table or CRUD ownership relation was found. | New tenant provisioning does not create an owned department catalog. Existing-tenant registration protection is preserved; employer text is not a department ownership authority. Do not invent a Company FK or select a tenant from request input. |
| Tickets / SLA | `tickets.department_id` is nullable PostgreSQL UUID; `ticket_sla_policies.department_id` is non-null UUID. Neither has a Department FK. Tickets and SLA policies separately have tenant IDs. Ticket setters do not establish department ownership. | Orphan IDs can survive department deletion. Matching a department ID does not prove it exists or belongs to the ticket tenant. There is also a legacy string/UUID type mismatch. |
| Default assignment | `tickets/service.py::_resolve_default_assignee` requires matching tenant, department, ACTIVE status and Manager role | Sharing a department does not by itself let this resolver choose a Manager from another tenant. Preserve this predicate during any migration. |
| Manager task/ticket/log access | `services/task_access.py` applies creator tenant before task department scope; `tickets/access.py` combines ticket tenant and Manager department; `routers/logs.py::_apply_scope_filters` applies event tenant and current resource/subject scope | Selected current task/ticket/audit protections remain effective even when department IDs are shared. Department removal immediately removes the applicable access; it need not invalidate the entire login session. |
| Transfers | `services/tenant_users.py` validates same-tenant users; Managers require matching nonempty source/target departments | Keep the Phase 1.4 preflight and object writer rules. Department migration must remap all members together to avoid accidentally granting/removing transfer rights. |
| Reports / filters | `frontend/pages/Reports.tsx` fetches tenant-filtered tasks/users and the global department catalog; filters/compare options use names and can fall back to free-text task teams. `pages/Users.tsx` also matches names as well as IDs. | Global metadata appears in options even without foreign tasks. Rename/split changes grouping labels and comparisons. Free-text `Task.team` is not a Department FK and must not be automatically rewritten. |
| Frontend cache | `services/mockApi.ts` has a department-name-to-ID resolver and a catalog cache keyed `departments` | A future tenant model needs tenant/session-aware catalog state and invalidation on account/tenant change, plus disambiguation within the current tenant. Current name lookup assumes one installation-wide name. |
| Notifications | Department CRUD enumerates all Owner/Admin IDs. Current `notification_dispatcher.create_history_notification` refreshes actor/recipient and suppresses differing tenants. `notification_access` rechecks tenant/status/resource policies. | The global recipient query is still inappropriate for a future owned catalog, but **it is not evidence that the current dispatcher delivers cross-tenant notices**. D01 verifies that the foreign inbox does not receive the created department notification. Department-specific ownership reauthorization does not exist. |
| Hooks | Department create/delete schedule `trigger_n8n_event` with the department payload; no Department tenant exists in that payload | Future attribution, routing and payload minimization need review. External dispatch was disabled/blocked in all tests. |
| Templates / media | `TaskTemplate.department_id` and `MediaFile.department_id` have string Department FKs with `SET NULL`; ownership is otherwise derived through creator/uploader | They must be included in inventory and mapping. Deletion can silently strip those labels too. |
| Backup/import | `backups/scope.py::SHARED` explicitly includes departments; registry exports `id name`; backup service describes shared reference datasets. Legacy `routers/data_admin.py` global operations first call `assert_isolated` and refuse ambiguous multi-tenant databases. | Update the actual backup scope, references and format when ownership is approved. Do not claim the guarded legacy reset/export is currently an unrestricted cross-tenant path. Old imports cannot overwrite another tenant's remapped department. |

The **D01 real HTTP diagnostic** created a department under tenant A, observed tenant B's duplicate-name rejection, linked synthetic users from both tenants, renamed it using tenant B, and deleted it using tenant B. Both users' Department FKs became NULL. A synthetic ticket created under tenant A retained the deleted department's ID and remained readable to its authorized Owner. The diagnostic passing means these risks were reproduced; **department isolation did not pass**.

### Other dependencies and limits found during assessment

- Seed departments use IDs such as `dept-1`, not only UUIDs (`backend/app/seed.py`). Blindly casting all IDs to UUID is unsafe. The UI and imports may already depend on these strings.
- The actual disposable PostgreSQL schema confirms the user/template/media FKs and absent ticket/SLA FKs; see [infrastructure evidence](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/infrastructure.json). This is not a catalog inspection of an existing customer database.
- `c9f9f2b9d2ad_create_ticket_system.py` introduced the UUID department columns without Department FKs. `5f2a7c3d1b0e_add_media_files.py` contains the media FK. `1a2b3c4d5e6f_add_reporting_module_tables.py` contains additional reporting department fields/indexes; inventory them if present in the target installation. No Department tenancy migration was found.
- `routers/pipelines.py` contains Department assumptions, but no registered pipeline router or matching Pipeline ORM class was found in the active application. Treat it as legacy source to inventory, not a demonstrated live exposure.
- **Adjacent source-confirmed risk:** `services/minio_media_service.py::list_media_files` filters Managers by department without uploader tenant; Owner/Admin have no tenant condition there. The `/media/list` route is registered. With shared departments this can select another tenant's media metadata. The presigned-URL path was **NOT RUN** because storage credentials/external storage were excluded. Department isolation alone would not fix the unscoped staff branch. This deserves a separately scoped media authorization review before broader delegation/release claims.
- Global Kanban and audit-retention configuration ownership remain separate Phase 1.4 decisions. This assessment does not resolve them or broaden the meaning of `OWNER`.

## 2. Isolation alternatives and recommendation

| Option | Security | Migration complexity | Scalability | Backward compatibility |
|---|---|---|---|---|
| **A — tenant-owned Department records** | Direct tenant predicate and tenant-qualified relationship constraints; independent tenant administration | Moderate/high: split shared records, remap references, reconcile string/UUID columns and imports | Straightforward tenant indexes; no cross-tenant mutable catalog contention | Preserve unambiguous legacy IDs where approved; use explicit mappings for shared IDs and old clients |
| **B — global templates plus tenant instances** | Safe only if operational users/tickets reference tenant instances; templates immutable/read-only to tenant admins | Highest: template lifecycle plus all A migration work and provenance | Good for standardized catalogs, with additional synchronization/version policy | Names may be familiar, but copying must not silently subscribe tenants to future template mutations |
| **C — intentionally global departments with restricted policy** | Requires explicit platform administration, tenant read policy, and prevention of cross-tenant side effects; current tenant Owner role is insufficient | Superficially low schema change, substantial policy/route/backup work | Central administration and shared name namespace become bottlenecks | Retains IDs but removes existing Manager/Owner global editing powers; independent customization remains impossible |

**Recommend A: tenant-owned operational departments.** This aligns with existing user/ticket tenant boundaries and tenant-admin workflows. B is reasonable only if product explicitly needs standardized templates; it is not required to isolate operational data. C is not safe under the current mutable CRUD policy.

A single global label can be reused safely as an immutable template. A mutable operational department cannot safely be shared just by attaching it to several tenants: ownership, edit/delete rights, membership, historical references and notification scope must be explicit. Merely adding a tenant-department association table while retaining global rename/delete is insufficient.

## 3. Required product decisions — implementation STOPPED

Approval is required for the following concrete choices before any Department code/schema/backfill work:

1. Adopt A, B, or a fully specified C policy. Under A, confirm tenant ownership and whether Managers may create/rename/archive departments or only Owner/Admin may do so.
2. Approve an explicit mapping for each shared/unknown legacy department and every referenced tenant. Decide which, if any, tenant retains an existing ID. Do not infer ownership from the first/current user, name, email domain, or first ticket.
3. Choose preservation rules for old IDs, name case/whitespace uniqueness, API/CSV compatibility and seeded non-UUID IDs. Confirm whether historical labels are snapshots or reflect the current name.
4. Choose deletion behavior: recommend archive/restrict while referenced, with explicit authorized unlinking. Current global `SET NULL`/orphan behavior must not be copied accidentally into a composite FK.
5. Approve treatment of orphan ticket/SLA IDs, unreferenced departments, contradictory creator/uploader ownership, old reporting rows and historical tenant movement. Unknown rows remain preserved and quarantined from tenant access pending review.
6. Approve migration window, mapping manifest, tenant permission comparison, backup/restore rehearsal and rollback operator responsibility. Resolve shared Kanban/retention policy separately.

No approval is assumed. The stop applies to department implementation; the independently authorized disposable authentication/regression verification was completed.

## 4. Disposable full-stack environment

Launcher: [run_mcp_phase1_5.py](../../backend/security_tests/run_mcp_phase1_5.py); guarded bootstrap/inspection: [mcp_phase1_5_backend.py](../../backend/security_tests/mcp_phase1_5_backend.py); real browser suite: [mcp_phase1_5_browser.cjs](../../backend/security_tests/mcp_phase1_5_browser.cjs).

Run ID: `37bfda6ed3814a9d87ccc2f75fe43c0d`. New evidence is kept in its own directory; preexisting Phase 1.5 artifacts are preserved and are not counted as this run's results.

| Component | Configuration and safety boundary |
|---|---|
| Backend | Existing dependency image `zeaplay_v1-backend:latest`, current `backend/app` mounted read-only at `/source/app`; real `app.main:app`, routers, startup, workers and middleware under Uvicorn on internal 7211. Read-only root, scratch/tmp tmpfs. No dependency overrides or mocked authentication. |
| PostgreSQL | New `postgres:16-alpine`, observed **16.15**; `zea_phase15` fixture DB and generated throwaway credential; data on tmpfs, no published DB port, no existing volume. |
| Redis | New `redis:7-alpine`, observed **7.4.11**; internal 6379, persistence disabled and `/data` tmpfs. Backend cache/events and Node presence use this Redis. |
| Presence | Existing dependency image `zeaplay_v1-presence:latest` with current `src` and package manifest mounted read-only; internal 7212; real `/auth/presence/validate` authority; no controlled validation stub in the browser suite. |
| React | Current Vite production build into an owned temporary `www` directory. Sanitized child environment, `envDir` explicitly set to empty scratch, config's `loadEnv('.')` also runs there. No repository `.env` is loaded. Build [PASS](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/build.txt). |
| Proxy | Fresh Nginx uses repository frontend proxy config plus a test-only `/socket.io/` upstream. `/api/` strips one prefix, `/ws/` upgrades to FastAPI. Browser tests reach canonical and `/api` aliases through `/api/...` and `/api/api/...`. No deployment config changed. |
| Network | Backend/PG/Redis/presence use a new Docker **internal** network. Only Nginx is also on a new ingress network; its random host port binds **127.0.0.1 only**. No container is attached to an existing application network. |
| Credentials and delivery | Fresh signing keys, fixture password and DB credential; no production secrets mounted or supplied. n8n/AI webhook disabled, no external integration credentials. Python audit hook permits only fixture PG/Redis connections and rejects SQLite, external DNS and external TCP; an attempted TEST-NET address is rejected before connection. Browser external resource requests are aborted. |
| Token lifetimes | Access 1 minute, session/refresh 2 minutes, using real issuance and wall-clock expiry. Existing presence issuer remains unchanged; session expiry caps its token, exercising the React renewal timer at expiry minus 30 seconds. These are test-only settings. |
| Data | Two synthetic tenants, eight initial synthetic users, grouped/foreign tasks, private/foreign tickets and audit/notification fixtures. No existing DB, export, customer record, credential or email transport was used. |
| Migration boundary | Empty-DB assertion, fixture database/user/host assertions, run-ID guard table. Build business metadata, construct the predecessor shape, stamp `k1a3c5e7f9b1`, then execute actual incremental auth/audit revisions through `m3c5e7f9a1d3`. This is **not** verification of the entire historical migration chain. No existing DB migration occurred. |
| Cleanup | Only this run's random-name, label-verified containers/networks are removed; tmpfs is disposable. No named test volume is created. Existing containers, volumes and prior abandoned test resources are retained. See [resource baseline](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/resources-before.json) and final scope evidence. |

Docker Desktop was initially stopped and was started locally. Its configured auto-start behavior resumed the local Paradise containers; no manual changes, tests or migrations targeted that application. The preservation inventory was captured after Docker became available. Do not interpret it as proof of pre-start container runtime states or a production deployment check.

External CDN blocking causes the existing HTML's `tailwind.config` statement to raise `tailwind is not defined`; these page errors are retained in evidence. Login controls and tested React flows still execute. This is authentication/integration evidence, **not visual acceptance or a zero-console-error claim**. TLS, production proxy configuration, other browsers, unsupported Web Locks environments, offline tabs, production load and external SMTP/storage/provider interoperability are NOT RUN.

## 5. Browser and authentication lifecycle results

The final run is recorded in [browser-final.json](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/browser-final.json) and [console results](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/browser-final.txt): **13 authentication/authorization scenarios PASS, plus 1 successfully reproduced department diagnostic; zero failed test scenarios**. Chromium is real/headless; requests use the actual Nginx/FastAPI/PostgreSQL/Redis/presence stack. `page.evaluate(fetch)` is real HTTP, not an intercepted response. UI login/logout/password change and navigation/reload behavior are exercised with Playwright selectors. Administrative changes use authorized real HTTP; tenant movement uses a guarded fixture DB transaction because no tenant-switch product endpoint exists.

| Test | Observed assertion | Result |
|---|---|---|
| B01 | UI login, reload and `/auth/me` 200; UI logout 204; old access/refresh 401; persisted session marked revoked | PASS |
| B02 | Natural access expiry returns 401. Two actual tabs wait on native Web Locks; after release exactly one refresh POST succeeds, both use the successor. PostgreSQL stores two refresh records, one consumed predecessor, unrevoked family. Real presence renewal timer succeeds and Redis socket membership returns for both tabs. | PASS |
| B03 | Reuse of consumed refresh returns 401, revokes the successor family durably, and reload returns to login | PASS |
| B04 | Deactivation forces login; inactive password login is 403. Reactivation does not restore old access/refresh; fresh login works | PASS |
| B05 | Tenant A → B → A commits increase epoch twice; reload invalidates UI each time; old A and B access/refresh remain 401; B cannot read A's task; fresh A login succeeds | PASS |
| B06 | UI password change 204 invalidates old access; administrative password reset 204 invalidates the next refresh; login using the final password succeeds | PASS |
| B07 | Live Socket.IO connects and Redis tracks membership. Deactivation causes real socket close and removes membership within the asserted 20-second measurement bound. Reactivation leaves old access denied; fresh login reconnects | PASS |
| B08 | Logout clears shared token storage and the second open tab reaches login without a test-issued reload/manual request; normal app background behavior remains active | PASS |
| B09 | Two concurrent real refresh HTTP requests using one credential return exactly 200/401; strict replay revokes the winner's family and its access then returns 401 | PASS |
| B10 | Native browser task WebSocket connects through Nginx. A separate page with no React lifecycle remains idle after HTTP logout; server heartbeat closes it with 1008 (about 25 seconds). Revoked reconnect is denied; fresh login reconnects | PASS |
| B11 | Manager → User role change advances persisted epoch, rejects old access/refresh and requires fresh browser login; demoted user cannot read another assignment | PASS |
| R01 | Representative cross-tenant HTTP matrix below, both API route aliases | PASS |
| R02 | Same Manager bearer immediately loses task/ticket scope after department removal (403 / empty list); `/auth/me` stays 200 and epoch unchanged. Restoring the department restores the current authorized scope. Shared department still grants no foreign task/ticket access (404) | PASS |
| D01 | Global CRUD, duplicate-name coupling, multi-tenant memberships, cross-tenant rename/delete, user unlink and retained orphan ticket ID reproduced; foreign notification suppressed | Diagnostic reproduced; isolation BLOCKED |

**Important distinction:** identity changes (tenant, role, status, password and explicit epoch revocation) invalidate sessions. Department/ticket membership changes are enforced as current object authorization on the next request. The preexisting draft R02 incorrectly expected 401 for department removal; it now requires **403**, a still-valid `/auth/me`, unchanged epoch and no cached ticket access. No application behavior or security rule was relaxed. The initial failed assertion is retained in [browser-initial.json](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/browser-initial.json).

The extended test's new positive audit assertion initially looked only at the newest 50 events after many synthetic logins. It was corrected to request `action=PHASE15_FIXTURE`, then require the own-tenant event and exclude the foreign event in both directions. [browser-extended.json](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/browser-extended.json) retains that harness failure. It was not an application authorization failure.

Presence B07 measures a bounded local test, not a hard guarantee under every event-loop/network failure. Task heartbeat is about 25 seconds. Existing idle chat/ticket sockets revalidate on packets/delivery rather than an idle timer; idle closure for those channels was NOT RUN and is not certified by B10.

## 6. Cross-tenant and retained regression verification

| Protection | Real HTTP evidence |
|---|---|
| Task visibility | Authorized assignment 200; unrelated same-tenant sibling denied; foreign tenant task reads 404; shared department does not bypass tenant gate |
| Grouped assignments | Ordinary assignee group expansion excludes sibling; creator expansion includes legitimate sibling; transfer affects selected assignment while peer assignment remains intact |
| Ticket access | Authorized logs/tasks return 200; unrelated peer denied; foreign ticket subresources 404 on both aliases |
| Transfer authorization | Foreign target denied; unrelated transfer approver denied; authorized Owner approval succeeds |
| Ticket relationships | Foreign ticket owner creation denied before grant |
| Audit | Tenant A event visible only to A; tenant B event visible only to B, with positive and negative checks on both route aliases |
| Notifications | Foreign-tenant notice addressed to a local user remains hidden; department dispatcher suppresses notice to foreign Owner |
| Sensitive caches | Ticket follower grant then removal changes the same user's next list immediately; Manager department removal removes task/ticket scope with the same bearer. Current source bypasses sensitive task/ticket response-body caches. Redis is running, but authorization is PostgreSQL-backed. |
| Observer writes | Follower PATCH denied with 403 on both aliases |
| Permission/session changes | R02 current department authorization; B11 durable role-change revocation; B04/B05 status/tenant changes |

Additional retained suites were executed against separately created, guarded disposable PostgreSQL instances, never the installed application:

- [Authentication regressions](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/auth-regressions.txt): **51 PostgreSQL methods PASS** (8 audit + 43 retained), fresh-interpreter revocation PASS, **60 Node presence checks PASS**, **1 Socket.IO transport test PASS**. Controlled authority/clock cases remain unit/transport evidence, separate from B02/B07's live full stack.
- [Tenant/business regressions](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/tenant-regressions.txt): **53 methods PASS**, including one diagnostic reproducing global departments. Real database and router/service tests; not counted as browser tests. Business coverage overlaps the authentication suite, so these counts are not 104 unique behaviors.
- PostgreSQL integration covers actual revision DDL, enabled invalidation/audit triggers, row locking, refresh records, commits, replay and durable revocation. Redis integration covers live presence membership, disconnect removal/reconnect and application startup/cache/event connections. Redis outage/failover was NOT RUN.

## 7. Department migration readiness — design only

No migration file or speculative backfill was generated. The following is the reviewable proposal for Option A, contingent on Section 3 approval.

### Schema, constraints and indexes

1. Add nullable UUID `departments.tenant_id` during expansion, retaining string `id`. Do not invent a FK to a nonexistent Tenant table. Define authoritative tenant identity/provisioning explicitly.
2. Add tenant-scoped name uniqueness (exact versus normalized name requires approval), plus unique `(tenant_id, id)` to support composite references. Preserve global ID uniqueness for API compatibility. NULL-owned rows are quarantined and not returned through tenant routes.
3. Replace the installation-wide name constraint only after every exposed reader/writer is tenant-aware and old application instances are drained. Controlled tenant clones may share names; tenants must not discover each other through global duplicate errors.
4. Users can ultimately reference `(tenant_id, department_id)` → Department `(tenant_id, id)`. Add child lookup indexes on those columns. Prefer RESTRICT/explicit transactional unlink or archive. A generic composite `ON DELETE SET NULL` would also threaten required tenant identity; do not copy it from today's single-column FK.
5. Ticket/SLA UUID columns cannot reference arbitrary legacy string IDs directly. Prefer additive string `department_ref_id` shadow columns, backfilled through the approved mapping, with tenant-qualified FKs; maintain approved compatibility until old readers are retired. Do not blindly cast `dept-1` to UUID or convert live columns in place. After cutover, agree on the public field/type contract before contraction.
6. Template/media relationships need enforceable tenant provenance: either add and validate tenant columns derived from an approved creator/uploader mapping, or adopt another explicitly reviewed relational constraint strategy. A bare global Department FK is insufficient. Include installed reporting fields and import/export reference metadata.
7. Index tenant/name lookup and tenant/department child lookups. Tickets already have `(tenant_id, department_id)`; shadow-column indexes are additional during transition. Create/validate large indexes and FKs in separately rehearsed bounded operations; inspect locks and table size before deployment.

### Backfill and integrity rules

- Build a reviewed manifest keyed **(legacy department ID, tenant ID)**, with target department ID, approved name, references/counts, evidence, decision owner and disposition. Classify unreferenced, single-tenant, multi-tenant, malformed and orphan records. Even one observed tenant is only evidence for approval, not automatic legal ownership.
- For approved single-tenant records, retain IDs if feasible. For approved shared records, create independent operational rows per tenant and remap all references consistently. Retaining the old ID for one tenant requires an explicit choice; otherwise use a tenant-qualified compatibility mapping.
- Use explicit ticket/SLA tenant IDs; validate user tenant and creator/uploader provenance. Do not infer historical event ownership from current user tenant. Conflicting or unattributable references stay preserved in a review queue, inaccessible under the new tenant policy until resolved.
- Include users, tickets, SLA, templates, media, installed reporting rows, exports/imports, notifications and historical department references. Keep immutable audit history; use an authorized historical mapping rather than rewriting event attribution. Do not rename free-text task teams automatically.
- Compare before/after record counts and mapping cardinality; require every non-null active reference to resolve to exactly one same-tenant department. Check orphans, duplicate normalized names, invalid legacy IDs and unintended nulls; confirm no unrelated assignment/status/scoring/audit fields changed.
- Re-run role/tenant permission matrices, Manager task/ticket/default-assignee/transfer behavior, notifications, caches, reports, backup round trips and UI names/filters on synthetic fixtures and on a separately approved restored copy. No customer restore was used in this phase.

### Expand/contract and deployment order

1. Approve policy/mapping and inventory the target schema read-only. Back up and verify a restore in an isolated rehearsal environment.
2. Expand with nullable ownership/shadow references and supporting indexes; retain legacy columns/IDs. Stage a tenant-aware compatibility release that fails closed on unresolved ownership and validates every new write.
3. Freeze affected legacy writes for the reviewed backfill/cutover window, or deploy an explicitly reviewed dual-write strategy. Drain old API/worker/import writers before relaxing global uniqueness. Never expose a mixed fleet whose old readers still return global catalogs.
4. Apply the approved, resumable mapping in bounded transactions; validate reconciliation and foreign references. Enable new readers/writers, tenant-aware cache namespaces, notification attribution, seeds, UI ID resolution and backup format together. Confirm Manager behavior before reopening writes.
5. Validate composite constraints; make ownership non-null for active operational rows once ambiguities are resolved. Monitor denied/unmapped references. Retain compatibility mapping and old columns for the agreed rollback window.
6. Contract only after old clients/import formats/workers are retired and a restore rehearsal is accepted. Archive preserved ambiguous history according to the approved policy; do not silently delete it.

Rollback after tenants independently rename/create departments is **not** a simple merge or downgrade: names and formerly shared IDs may now conflict, and restoring old global readers reopens the exposure. Preserve additive columns, mappings and ownership, prefer forward fixes or maintenance mode, and reconcile any post-cutover writes before a reviewed restore. Session/permission invalidation during membership remapping must follow an approved policy; current department changes reauthorize objects without advancing login epoch.

## 8. Implementation-stage acceptance criteria and remaining blockers

This implementation-stage table is retained for traceability. The independent audit above supersedes broad security interpretation, notably its **BLOCKED** assessments for repeatable multi-tab recovery and complete cross-tenant isolation. PASS here describes the original run only; it does not certify every application feature, repeatability or production deployment.

| # | Requested criterion | Status | Qualification |
|---|---|---|---|
| 1 | Department ownership accurately analyzed | PASS | Global records and actual cross-tenant CRUD reproduced |
| 2 | Security implications documented | PASS | Metadata, mutation, membership, orphan IDs, media/report/import dependencies |
| 3 | Migration impact understood | PASS | Type mismatch, constraints, mapping, compatibility, rollout and rollback assessed; actual customer mapping remains BLOCKED |
| 4 | No speculative tenancy migration | PASS | Design only; department implementation stopped |
| 5 | Disposable environment isolated | PASS | New private network, tmpfs PG/Redis, loopback proxy, synthetic fixtures, connection guards |
| 6 | Browser login/logout | PASS | B01 and related lifecycle scenarios |
| 7 | Rotation and revocation | PASS | B02–B07, B09/B11 and persisted PG state |
| 8 | Multi-tab authentication | PASS | Chromium native Web Locks and open-tab logout; unsupported browsers/offline tabs NOT RUN |
| 9 | Tenant-change invalidation | PASS | B05, two committed epoch changes; no old credential resurrection |
| 10 | Presence disconnect/reconnection | PASS | B02/B07 live authority and Redis; B10 additionally tests FastAPI task sockets |
| 11 | Cross-tenant regressions | PASS | Listed Phase 1.1–1.4 repaired task/ticket/audit/notice/cache/observer protections; global Department isolation remains BLOCKED, not a PASS |
| 12 | Existing user/task/ticket behavior preserved | PASS | Scoped positive/negative regressions; no runtime application change. Exhaustive product acceptance NOT RUN |
| 13 | No production data/infrastructure changes | PASS | Only local disposable test targets; no existing DB migration, deployment, production credentials or external delivery |
| 14 | Outstanding blockers reported | PASS | Decisions/limitations below are explicit |

Outstanding blockers:

- **BLOCKED:** Department ownership approval and safe migration/mapping. Current global mutation is a reproduced security failure, not resolved by the passing diagnostic.
- **BLOCKED:** independent ownership policy for Kanban/shared configuration; media tenant predicate review before broad delegation exposure.
- **NOT RUN:** production/TLS deployment equivalence, full historical migration chain, customer ownership census/restore, external provider/storage/email, production load/failover, full UI regression and non-Chromium/no-Web-Locks clients.
- **NOT IMPLEMENTED:** dedicated OAuth/delegation issuer/audience/client/consent/grant/scopes and restricted token exchange. Current durable browser sessions do not supply delegated authorization; arbitrary legacy API scope labels are not an enforcement boundary. No implementation started here.

**NO-GO for the next OAuth implementation stage under the unresolved tenancy gate. Stop after Phase 1.5.** Approve and close applicable data-ownership/security decisions, then separately authorize the OAuth/delegation stage. Passing local authentication does not approve production rollout or MCP exposure.

## 9. Files changed and reproduction

Only this report and the preexisting Phase 1.5 harness were changed in this turn:

- `backend/security_tests/run_mcp_phase1_5.py`: per-run evidence directory, explicit empty Vite env directory, preservation of old artifacts.
- `backend/security_tests/mcp_phase1_5_backend.py`: guarded read-only schema/infrastructure inspection and network-denial assertion.
- `backend/security_tests/mcp_phase1_5_browser.cjs`: per-run evidence/provenance, task-WebSocket and role-change tests, stronger department/audit assertions, corrected department-permission expectation.
- `docs/mcp/PHASE_1_5_FULLSTACK_SECURITY.md`: this report.
- New `backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/` artifacts: build, browser, PostgreSQL/Node regression, safety and scope evidence. Initial failures are retained.

No backend/frontend/presence **application runtime** file, migration, Compose file, package manifest/lockfile or Git index was changed in this turn. Starting uncommitted work remains in place; these statements concern the delta from the initial hash snapshot, not all files shown by `git status`.

[Final scope evidence](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/scope-final.json) verifies only the three harness files changed among the initial files, all preexisting container identities/statuses (after engine startup) and volumes remain, and this run's five full-stack containers/two networks were removed. The separate regression launchers also completed their owned-resource cleanup. [Static/artifact verification](../../backend/checks/phase1-5-37bfda6ed3814a9d87ccc2f75fe43c0d/verification.json) records Python/Node syntax, `git diff --check`, component versions and a clean artifact scan for JWTs, bcrypt hashes and the fixture password.

Reproduction (requires the existing dependency images, frontend packages and a local Playwright/Chromium installation):

```powershell
python -B backend/security_tests/run_mcp_phase1_5.py start
# Use the newly printed owned state.json path. It contains a generated fixture
# password; never copy it into source control, a report, or a shared artifact.
$env:ZEA_PLAYWRIGHT_MODULE = '<installed playwright-core directory>'
$env:ZEA_CHROMIUM_EXE = '<installed Chromium executable>'
node backend/security_tests/mcp_phase1_5_browser.cjs '<owned state.json>'
node backend/security_tests/mcp_phase1_5_audit.cjs '<owned state.json>'
python -B backend/security_tests/run_mcp_phase1_5.py stop '<owned state.json>'

.\backend\venv\Scripts\python.exe -B backend/security_tests/run_mcp_phase1_3.py --audit
.\backend\venv\Scripts\python.exe -B backend/security_tests/run_mcp_phase1_4.py --audit
```

The launcher accepts only `start` or `stop <owned-state.json>`; it does not use the installed Compose project or any existing application database. Cleanup verifies resource ownership labels before removal and removes the fixture password from the retained scratch state.
