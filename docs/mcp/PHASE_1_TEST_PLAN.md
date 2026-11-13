# Phase 1 isolated security tests and remaining verification plan

Date: **11 November 2026, Asia/Calcutta**. Source baseline `8978158`. Status vocabulary: **PASS / FAIL / NOT RUN**. A source-confirmed vulnerability is an open finding, not a passing security check. No running/deployed installation is certified by this document.

## 1. Executed scope and result

Command from repository root, using existing installed dependencies:

```powershell
python -B backend/security_tests/run_mcp_phase1.py
```

Independent-review result: **20 unittest methods completed successfully, 0 failures/errors; security gate FAIL**. The final reviewed run reported `Ran 20 tests in 4.545s`, `OK`; the launcher intentionally exits **2** because diagnostics reproduce six failing observations across S03/S05/S07. Counts: 13 current-policy regression methods, 4 isolation methods and 3 diagnostic methods. A successful diagnostic is a completed measurement, not a passing permission check. No dependencies were installed.

The earlier 14-method, exit-0 Phase 1 run is historical and is superseded by this review. The review fixed synthetic emails rejected by the real full-task response validator and added tests of the actual candidate reads. It retained the real ticket-task UUID/string response failure as a separate observed defect rather than modifying application serialization. Temporary fixture-development failures are not counted as final results.

Launcher exit semantics: `0` means all **exercised** unit checks and diagnostic gates passed; `1` means fixture/regression execution failed; `2` means unit execution succeeded but an open security gate was observed. Neither exit 0 nor unittest `OK` certifies untested OAuth, PostgreSQL, clients, proxy paths or production. A wrapper captured the launcher subprocess return code as **2**; shell/tool aggregation of nonzero statuses must not be read as a clean run.

Files added:

- `backend/security_tests/run_mcp_phase1.py`: stdlib launcher, fresh child process, sanitized environment and disposable working directory.
- `backend/security_tests/mcp_phase1_cases.py`: isolation guards, synthetic two-tenant fixtures, actual FastAPI task/ticket routers, real JWT identity/tenant/role dependencies, app-wide navigation guard and focused assertions.

Runtime inventory: Python 3.14.3, FastAPI 0.141.1, Starlette 1.6.0, httpx 0.28.1, SQLAlchemy 2.0.52 and Pydantic 2.13.4. Warnings observed: installed Starlette/httpx test-client deprecation and existing `datetime.utcnow()` deprecations under Python 3.14. They did not fail the suite; no dependency replacement was performed. Local Python 3.14 is not proof of backend Docker Python 3.11 compatibility. PostgreSQL/full-text/production schema checks remain **NOT RUN**.

## 2. Isolation verified before application database imports

The launcher starts the test child with `-I -B`, an empty new `TemporaryDirectory`, a restricted environment containing only required OS execution variables, in-memory database URL, fresh synthetic signing keys and a test-only isolation marker. TEMP/TMP point inside that scratch directory. Existing `.env`/`.env.local`, production credentials, Redis and provider settings are not inherited. Repository root is added explicitly for source imports only; the child does not change into it.

Before importing database/models/routers, the child:

1. Verifies marker, exact `sqlite:///:memory:` URL and empty scratch working directory.
2. Installs an import blocker for `backend.app.main`, `app.main`, legacy `backend.tests` and Alembic. No pytest discovery/collection occurs.
3. Installs an SQLAlchemy `Dialect.do_connect` guard accepting only SQLite with `:memory:` connect argument, and a `sqlite3.connect` audit guard covering direct DBAPI calls. File SQLite and other SQLAlchemy database connections fail before DBAPI access to an existing database.
4. Blocks application TCP connections, UDP sends, listeners/binds, DNS, subprocesses and shell calls through an audit hook. Windows asyncio needs a private wakeup socketpair; only loopback bind-to-port-zero/connect calls made synchronously inside the wrapped Python socketpair constructor are allowed. Arbitrary application connections/binds/UDP sends to localhost remain blocked and are tested.
5. Resolves/validates test settings before the first database/router import: exact memory DB, no Redis/cache Redis and n8n forwarding disabled. Prints `ISOLATION PASS` before fixture DDL.

`backend/app/database.py` has import-time schema helper calls. In this child those can reach **only a new process-local memory database**, not an existing environment. Each test additionally owns a fresh memory engine/StaticPool and uses `Base.metadata.create_all` for fixture tables and existing metadata guards; there are **no Alembic migration calls, drop/reset operations or file databases**. SQLite's deterministic `to_tsvector` stub permits generated-column DDL only; it does not emulate PostgreSQL search.

The miniature FastAPI app includes the real task/ticket routers at canonical and `/api` paths, then the API-only workflow router in main.py's relevant registration order, with real `enforce_navigation_policy`. Only `get_db` is overridden to the fixture session; JWT/current-user/ACTIVE/role/navigation dependencies are not replaced. `TestClient` runs requests in-process without a lifespan context, application server socket, `main.py`, installed startup, seeding or maintenance workers. Task event transport publication is suppressed; ORM authorization/query/serialization and domain guards remain real. A wrapping spy observes the actual ticket task query without changing its result/authorization. All synthetic tickets have no pending notices/SLA deadlines, avoiding external notification delivery in these tests. This is a focused resource authorization harness, not the full installed app or proxy.

The four isolation tests independently demonstrate SQLAlchemy and direct SQLite file-connection rejection before file creation, rejection of application TCP/UDP/bind operations, and rejection of main/legacy-test imports. These controls are regression safeguards for this reviewed import graph, not a general sandbox for arbitrary untrusted code or native database/network libraries. Run only this reviewed suite through its launcher. If required packages are absent, record a blocker instead of installing dependencies or falling back to broad pytest collection.

## 3. Implemented test map

Names below are methods of `Phase1Authorization` or `IsolationControls` in `mcp_phase1_cases.py`. Each loop/subtest exercises the same focused contract; 20 is the unittest method count, not the number of requests or passing security claims. Diagnostic methods measure current behavior and populate the separate FAIL gate output.

| ID | Test | Expected / assertion | Result |
|---|---|---|---|
| P1-01 | `test_cross_tenant_task_read_and_write_denied_on_both_aliases` | Foreign task summary and PATCH return 404 for both prefixes; stored title unchanged | PASS |
| P1-02 | `test_cross_tenant_assignment_denied_on_both_aliases` | Same-tenant Owner cannot PATCH a foreign assignee, 404 on both aliases; assignment unchanged | PASS |
| P1-03 | `test_group_id_does_not_grant_direct_or_list_sibling_access` | Ordinary assignee reads own summary, gets 403 on sibling summary, paginated items contain authorized assignment/ticket-task rows and exclude sibling/foreign task for both aliases | PASS |
| P1-04 | `test_manager_department_scope_and_ordinary_user_boundary` | Same-department Manager reads sibling; unrelated ordinary assignee and other-department Manager get 403, both aliases | PASS |
| P1-05 | `test_unrelated_user_cannot_patch_even_with_group_id` | PATCH sibling title returns 403 through both aliases and leaves stored title unchanged | PASS |
| P1-06 | `test_ticket_tenant_and_membership_authorization` | Own ticket 200; same-tenant non-member 403; foreign ticket 404, both aliases | PASS |
| P1-07 | `test_deactivation_denies_an_existing_token_while_inactive` | Token works, DEACTIVATED status denies 403 on both aliases, reactivation accepts the same token again; proves live status check, not durable revocation | PASS for status behavior; revocation unimplemented |
| P1-08 | `test_database_role_overrides_stale_manager_claim` | Manager reads department task; demote in database while retaining signed Manager role claim; same token denied 403 on both aliases | PASS |
| P1-09 | `test_forged_tenant_claim_is_rejected` | Valid test signature but wrong tenant for database subject returns 401, both aliases | PASS |
| P1-10 | `test_observer_cannot_write_activity` | Existing `_activity_context(write=True)` rejects ordinary follower with 403 and appends no AuditEvent | PASS |
| P1-11 | `test_missing_and_expired_bearer_rejected_on_both_aliases` | No bearer and validly signed expired bearer return 401 on both aliases | PASS |
| P1-12 | `test_first_read_candidates_preserve_resource_scope` | Own overview/subtask reads succeed, sibling 403/foreign 404, no sibling child in own output; overdue page contains only own overdue task on both aliases | PASS |
| P1-13 | `test_workload_subject_requires_current_reporting_authority` | Own workload allowed; unrelated peer/department-only Manager denied; foreign target 404; verified direct-report link permits Manager | PASS |
| P1-I1 | `IsolationControls.test_file_database_connection_is_refused_before_creation` | File database cannot connect; no file created | PASS |
| P1-I2 | `IsolationControls.test_application_network_connections_are_refused` | Local backend TCP connection, UDP send and application listener bind refused by audit guard | PASS |
| P1-I3 | `IsolationControls.test_installed_startup_and_legacy_test_imports_are_refused` | Import of installed app and unsafe legacy ticket test rejected | PASS |
| P1-I4 | `IsolationControls.test_direct_sqlite_connections_cannot_bypass_engine_guard` | Direct sqlite3 file connection refused before file creation | PASS |
| P1-D1 | `test_group_expansion_diagnostic_records_current_security_gate` | Measure direct sibling 403 versus group expansion results, independently for both aliases; reject any unexpected foreign task | PASS measurement; S05 gate **FAIL** |
| P1-D2 | `test_ticket_subresources_diagnostic_records_current_security_gate` | Measure non-member parent 403 versus task query/log response without substituting serializer results | PASS measurement; S03 gates **FAIL** |
| P1-D3 | `test_missing_expiry_diagnostic_records_current_security_gate` | Measure actual resource response to correctly signed synthetic token without exp on both aliases | PASS measurement; S07 gates **FAIL** |

Fixtures: distinct tenant UUIDs; same-tenant Owner, ordinary member/peer/follower, same-department Manager, other-department Manager; foreign Owner; separate grouped assignment rows and a foreign task; separate parent-bound children, one overdue task, owned/foreign tickets, a private linked task and private ticket audit row. Synthetic email addresses use an example.com subdomain so actual EmailStr response validation can execute; no email/network delivery is permitted. The suite does not include every role/action permutation (for example Admin, pending ticket approver, all user-management paths); the broader matrix below remains necessary.

### Observed open security gates

| Finding / target | Observed result | Security verdict |
|---|---|---|
| S05 canonical `/tasks/assigned/group` | Direct sibling summary 403; group 200 includes that sibling | FAIL |
| S05 `/api/tasks/assigned/group` | Same denied-sibling disclosure | FAIL |
| S03 `/api/tickets/{fixture}/logs` | Parent read 403 for peer; logs 200 returns private fixture audit row | FAIL |
| S03 `/api/tickets/{fixture}/tasks` | Parent read 403; unauthorized linked-task query executes; response fails validation on UUID ticket_id (effective 500) | FAIL authorization/query boundary; successful HTTP content disclosure NOT confirmed |
| S07 canonical task summary | Correctly signed access token without exp accepted, 200 | FAIL mandatory-expiry policy |
| S07 API task summary | Same missing-exp token acceptance, 200 | FAIL mandatory-expiry policy |

No security gap was repaired in application code. Fixing only the task response schema would not repair S03. The diagnostic fails the gate for the missing pre-query permission check and separately reports that no successful task-content disclosure was demonstrated. S05 diagnoses assignment-visibility inconsistency; its write/business-policy resolution still requires approval.

## 4. Existing tests inspected, not executed

| Test source | Relevant evidence and limit |
|---|---|
| `backend/tests/test_task_tabs_review.py` | Disposable task harness, tenant/direct write denial, foreign related-user/dependency rejection, cache demotion; overrides active identity, so does not replace new real-JWT checks |
| `backend/tests/test_task_activity.py`, `test_subtask_workflow.py` | Explicit observer/service and child workflow authorization |
| `backend/tests/test_task_information.py`, `test_task_information_review.py` | Authorized/minimized history, foreign relationship redaction, child scoping and observer projections |
| `backend/tests/test_ticket_tenant_permissions.py` | Top-level ticket isolation/selected transitions; imports installed main and calls drop_all/create_all on a relative file DB during collection — **unsafe to import here** |
| `backend/tests/test_generate_token.py`, `test_oauth2_server.py` | Legacy token/password-flow tests; not evidence of OAuth PKCE, audience, scope or revocation enforcement; no imports/execution |
| `backend/tests/test_navigation_readiness.py`, `test_navigation_policy.py`, `test_settings_security.py` | Current-role authority, configuration capability and configuration audit tenant scope; not proof of all ordinary logs |
| `backend/tests/test_workload_notifications.py`, `test_workload_notification_review.py` | Current task alert ownership/read/delivery revocation, schema guards and realtime checks; not full ticket legacy notice authorization |
| `backend/tests/test_final_api_contracts.py` | Route/schema contracts; path presence does not prove object authorization |
| `backend/tests/conftest.py` | SQLite compatibility listener and startup suppression fixture; autouse fixture runs too late to prevent all module-level import/reset behavior |

No past test result from memory or existing evidence files is counted as a current result. Do not run `pytest backend/tests` or import `main.py` for OpenAPI until a separate isolation review covers the entire collected graph.

## 5. Pending security verification matrix

The full acceptance matrix below is **NOT RUN**. Narrow S03/S05 read probes and S07 missing-expiry observations above are now executed FAIL gates; they do not complete these broader role/tenant/repair acceptance scenarios. The rows describe remaining acceptance work after policy/implementation approval. See [security review](PHASE_1_SECURITY_REVIEW.md) for fixes and regressions.

| ID / finding | Required fixtures and procedure | Expected result / blocker |
|---|---|---|
| P1-P01 / S01 transfer target | Both tenants; ordinary/Manager/Admin/Owner; no managed children and managed children; inject foreign/missing/deactivated target into create/auto-approve/decision and bulk route | Foreign target denied before mutation/notifications; target-active eligibility requires approval; managed failure fully rolls back |
| P1-P02 / S01 approval | Pending request in same/foreign tenant; department Manager, unrelated Manager, no-department Manager; act approve and reject | Foreign task rejected by existing tenant lock; same-tenant operation authority follows approved rule. No false claim foreign decision succeeds |
| P1-P03 / S02 relationships | Every ticket owner/assignee/follower/participant/approver setter, sequential approval, linked task; mixed valid/foreign nested arrays and restored rows | Tenant integrity before write/fanout; no partial changes; active/historical-user policy settled first |
| P1-P04 / S03 subresources | Related/unrelated same-tenant user, pending approver, Manager and foreign user; ticket tasks/logs paths including linked task invisible by task policy | Ticket and child authorization, accurate filtered totals; expansion omission-versus-denial decision required |
| P1-P05 / S04 department/config | Two tenants share/reference departments; exercise CRUD, default assignment, user/ticket references and Kanban config | Ownership model/global administrator authority approved first; do not assert a nonexistent Department.tenant_id |
| P1-P06 / S05 group reads | Creator, each assignee, observer, staff, unrelated/foreign user; /group, lists/counts/nested information/dependencies/export/socket/email/cache | Same approved assignment policy everywhere; group ID never alone authorizes data. Broader group rule awaits approval |
| P1-P07 / S05 group writes | Shared title/description/priority, group append/template assignment, concurrent edits and accounting children | Approved actor/peer rule; atomic authorization, unchanged IDs/group UX, consistent rewards/notifications. No partial peer update |
| P1-P08 / S06 logs | Ordinary/system/config logs from two tenants, actorless/deleted-user/mixed provenance; list/export/retry and staff role variants | Only attributable authorized tenant records; ambiguous history withheld; retention ownership separately approved |
| P1-P09 / S07 OAuth | Wrong issuer/audience/algorithm/key/client/grant, missing exp/profile claims, invalid/expired/reused code, bad verifier/redirect, consent denial and tenant-link spoofing | Reject before tool execution; missing-exp legacy diagnostic already FAIL; full OAuth needs actual AS/subject/grant/delegation implementation |
| P1-P10 / S07 revocation | Active calls on multiple replicas, stale refresh family, client/connection disable, role/status/tenant change, key rotation, authority outage | Shared immediate deny on subsequent execution/emission; refresh reuse revokes family; outage denies; completed writes audited accurately |
| P1-P11 / S07 delegation | Trusted service exchange with mismatched subject/client/grant or over-broad tool; use delegated token directly against wrong endpoint/method/field and every alias; attempt management/admin access and fallback to legacy validator | Verified same-user/client/grant exchange, no authority amplification; backend rejects even if MCP bypassed; mandatory expiry capped to subject/grant; no unscoped JWT substitute |
| P1-P12 / S09 ticket cache | Warm lists as Admin/Manager/member; demote/change department/remove follower/participant; miss invalidation and simulate Redis outage | Cached bodies/counts never retain revoked access. Requires safe ticket cache fix |
| P1-P13 / S10 parent/comments | Follower parent PATCH/delete/complete versus activity; unrelated Manager comments, staff author delegation, ticket staff edits | Exact approved operation matrix; existing activity denial preserved; no silent authorization redesign |
| P1-P14 / S11 notifications | Legacy null-tenant and ticket-linked bodies, removed participant, pending approver, task reassignment, account-only balance adjustment; list/count/actions/delivery | Current resource access and consistent counts, no foreign bodies/delivery, preserved account-only semantics; legacy policy needed |
| P1-P15 / S08 read purity | Snapshot notification/read/SLA/audit/business tables before/after each declared read tool, include overdue/expired fixtures | No unintended side effects; ticket GET cannot be labeled read-only without approved new contract |
| P1-P16 / aliases/proxy | Same principal/ID/body across canonical, /api and actual Nginx paths; include API-only ticket workflow and hidden task route collisions | Same authorization and intended handler/contract; no SPA HTML masquerading as MCP/API success |
| P1-P17 / concurrency | Interleave tenants/users/clients/grants, request cancellation, stream resumption and a revoked grant during buffered response | No identity/token/cache leakage; session IDs are never authentication |
| P1-P18 / data minimization | Nested user/dependency/history rows, oversized descriptions/results, malformed upstream response, upstream errors containing synthetic secrets | Schema-bounded outputs, coverage/truncation preserved; no secret/private profile/error leakage |
| P1-P19 / Settings | Six sections/all roles, foreign IDs, shared-AS-client versus tenant approval mutations/revocation, navigation denial, revision/idempotency, Admin indirect write-scope/tool/client escalation, forged/replayed/stale/cross-user step-up receipt, revocation while MCP disabled | Tenant client revoke cannot affect another tenant/shared registration; before/after capability checks and bound Owner proof; personal revoke/emergency independent of enabled gate; current Settings paths/accessibility preserved; no UI/endpoints exist yet |
| P1-P20 / operations | Disposable PostgreSQL/Redis, verified selected Compose topology, fixed egress, audit failure, quota/load/backpressure, TLS/Host/Origin/proxy streaming | Explicit approved SLOs/runbooks pass without existing volumes/data. No deployment or Docker changes in this phase |

## 6. Future environment prerequisites

For PostgreSQL/cache/migration acceptance, first verify a newly created disposable database/schema and credentials with no production reachability, no existing volumes, fresh names, denied cross-environment network access and reviewed fixture imports. Record target identity and scope **before** imports/DDL/startup. Version-match the selected source Docker target (development PostgreSQL 16 versus production file PostgreSQL 15); do not select from historical notes. Any future schema/migration tests need separate authorization and disposable targets; none were run here.

For OAuth/client interoperability, maintain a recorded matrix of selected SDK/AS version, protocol revision, client name/version, discovery/registration/redirect support, scopes, PKCE, refresh/revoke, structured results, Origin/Host and streaming/proxy behavior. All live ChatGPT/Claude/Cursor/VS Code/custom/n8n compatibility checks remain **NOT RUN**. No named client version is certified by a design document.

## 7. Phase 1 acceptance and stop condition

| Requirement | Status / evidence |
|---|---|
| Architecture/service boundaries and delegated OAuth design | PASS — `PHASE_1_ARCHITECTURE.md` |
| Requested security findings verified against source with fixes/regressions/decisions | PASS — `PHASE_1_SECURITY_REVIEW.md`; open risks are not fixed |
| Actual versus missing permission layers and eight proposed scopes | PASS — `MCP_PERMISSION_MODEL.md` |
| Native Settings integration and six-section API/role contracts designed | PASS — `MCP_SETTINGS_DESIGN.md`; no UI/routes implemented |
| Focused tests written/executed safely for explicit current policies | PASS — 20 unittest methods complete; six diagnostic security observations FAIL; overall launcher exit 2 |
| Existing behavior/auth/schema/configuration/data preserved | PASS — changes restricted to five documents and two standalone test files; only synthetic memory database DDL/DML occurred |
| Deployment, migrations, installation, Docker edits or MCP/UI implementation | NOT RUN — intentionally outside authorized scope |
| Remaining blockers/approval decisions recorded | PASS — security review, architecture and permission/Settings decisions |
| Existing tenant/user bypass prevention and grouped-assignment visibility | FAIL — S03/S05 diagnostics and other source-confirmed gaps remain |
| Remote MCP release / beginning Phase 2 service under feasibility roadmap | FAIL / NO-GO — actual auth bridge, delegated enforcement, applicable read security repairs and negative tests are prerequisite; OAuth/protocol/client interoperability NOT RUN |

The independent security review contains the twelve-criterion PASS/FAIL table. Scoped documentation delivery is distinct from the feasibility report's broader security-preparation exit; those prerequisites are unfinished. **Stop after Phase 1; not production-ready.** Documentation completion does not authorize implementing the MCP server, Settings interface, endpoints, login changes, migrations, dependency installation or deployment.
