# Phase 1.4 — Tenant and resource security

Date: 11 November 2026. Checkout: `F:\Projects\zeaplay-05\zea-play-08-05-26\zea-play`; HEAD `b6a220aa7fcdac29fe34bfb4fd8b949ec29b154d`, with the existing Phase 1.1–1.3 working changes preserved.

**GO for further scoped security remediation in Phase 1.5. NO-GO for MCP implementation or production release.** Department/configuration ownership remains unresolved, and disposable browser/full-stack authentication verification has not been executed. This report certifies only the named source and isolated tests; it does not certify the running installation or external integrations.

Read/reassessed: [feasibility report](../MCP_FEASIBILITY_REPORT.md), [original findings](PHASE_1_SECURITY_REVIEW.md), [permission model](MCP_PERMISSION_MODEL.md), and the [Phase 1.1](PHASE_1_1_SECURITY_REMEDIATION.md), [Phase 1.2](PHASE_1_2_AUTH_SECURITY.md), [Phase 1.3](PHASE_1_3_SESSION_REVOCATION.md) reports. Their earlier findings describe historical stages; the matrix below describes this phase.

## Independent acceptance audit — 11 November 2026

This audit supersedes the implementation-stage acceptance matrix below. It reviewed the current dirty checkout against the feasibility report, original S01–S11 findings, permission model and Phase 1.1–1.3 contracts. Prior modifications and staged work were preserved. Tests use synthetic fixtures; no installed application endpoint or existing database was used.

**Acceptance: 13 scoped PASS, one BLOCKED (department ownership), no remaining reproduced Phase 1.4 FAIL after correction.** Broader unexecuted acceptance checks remain explicitly NOT RUN.

**Decision: GO for the next scoped security remediation stage; NO-GO for MCP, OAuth delegation or production release.** Department/configuration ownership remains BLOCKED. Full browser/application-startup/Redis/presence/proxy/TLS acceptance remains NOT RUN. The real proxy checks below close a narrower routing and HTTP authentication gap, not the complete full-stack gate.

### Reproduced Phase 1.4 defects and corrections

| Finding | Independent before-fix evidence | Scoped correction and current result |
|---|---|---|
| P14-A1 — multiple ticket roles denied a legitimate writer | Inserting FOLLOWER then ASSIGNEE for the same ticket/user caused `create_ticket_task` to raise 403. The writer query took an arbitrary first participant before testing its role. Multiple roles are permitted by the existing model. | `backend/app/tickets/workflow_service.py::_ensure_ticket_task_access` filters active OWNER/ASSIGNEE roles **before** `LIMIT 1`. The same test creates the task successfully; deleting the writer grant while retaining FOLLOWER denies the next write. **Implemented and tested.** No new role permission was introduced. |
| P14-A2 — notification admission reused stale authority | Four independent PostgreSQL cases retained ORM identities while a separate transaction committed demotion, deactivation or actor tenant movement. Stored delivery called the recorded webhook boundary; ticket email selection called the recorded email boundary; two history-creation cases returned an unauthorized notification. No real message was sent. | `backend/app/services/notification_access.py` refreshes the recipient and current navigation policy and clears the per-session task-module decision before delivery authorization. `notification_dispatcher.py` refreshes actor and recipient before deriving tenant ownership. `backend/app/notifications/service.py` uses the same recipient refresh for ticket history/email admission. The four reproductions and additional Manager-department/module-policy checks pass. **Implemented and tested.** |

[Before-fix evidence](../../backend/checks/mcp-phase1-4-audit-before.txt): eight independent methods, three passing, four failing assertions and one unexpected authorization exception. These represent two corrected defects, not five unrelated findings. [Initial harness error](../../backend/checks/mcp-phase1-4-audit-harness-initial.txt) was a test-fixture inheritance mistake and supplies no security evidence. [Intermediate navigation fixture failure](../../backend/checks/mcp-phase1-4-audit-navigation-fixture.txt) left the dashboard enabled; the existing shared-resource contract intentionally permits task APIs through that page. The fixture now disables both task and dashboard entry points; production navigation policy was not changed.

### Criterion-by-criterion results

PASS means an executed assertion in the named scope. It does not certify every route, screen or deployment. Test names below are in [independent Phase 1.4 tests](../../backend/security_tests/mcp_phase1_4_audit.py), [retained Phase 1.4 tests](../../backend/security_tests/mcp_phase1_4_cases.py), the retained `BusinessRegressions` loaded by [Phase 1.3 fixtures](../../backend/security_tests/mcp_phase1_3_cases.py), or the explicitly linked authentication/proxy suites. All fourteen requested criteria are accounted for.

| # | Criterion / result | Executed evidence and relevant source | Remaining risk / limit |
|---|---|---|---|
| 1 | Cross-tenant task transfers — **PASS** | `test_transfers_foreign_inactive_observer_and_department_denied`, `test_bulk_transfer_preflight_and_staff_success`, and real proxy checks deny foreign targets without changing assignments. Sources: `backend/app/routers/tasks.py`, `backend/app/services/tenant_users.py`. | Admission-time relationship checks do not promise cancellation of already authorized in-flight transactions. |
| 2 | Unauthorized transfer approval — **PASS** | `test_transfer_approval_object_scope_revalidation_and_valid_workflow` denies unrelated Manager, foreign staff and ordinary actors; rechecks a target moved after request creation. `test_concurrent_transfer_decisions_only_one_commits` uses separate PostgreSQL transactions and obtains one success/one 409. Same task/tenant helper paths as criterion 1. | No production workload/lock contention certification. |
| 3 | Foreign ticket identities — **PASS** | `test_ticket_relationship_create_and_update_reject_all_foreign_fields`, `test_ticket_participants_approvers_and_active_targets`, `test_all_approval_entrypoints_reject_foreign_and_valid_cycle_completes`, `test_linked_task_approver_and_assignee_tenant_integrity`. Sources: `backend/app/tickets/{service,workflow_service,approvals_service,task_engine_service,task_link_service}.py`, `services/tenant_users.py`. | Existing legacy relationships are not backfilled or deleted. Department ownership remains criterion 12. |
| 4 | User-specific ticket subresources — **PASS** | `test_ticket_subresource_role_matrix`, `test_ticket_denial_precedes_linked_task_and_log_queries`, `test_subresources_enforce_auth_without_global_navigation_guard`, plus real direct/proxy positive and negative reads. Sources: `backend/app/tickets/{access,workflow_router,workflow_service,task_engine_service}.py`. | Verified selected task/log expansions, not every future ticket subresource. |
| 5 | Audit tenant isolation — **PASS** | `test_audit_list_count_exports_retry_and_retention_are_tenant_scoped`, `test_audit_attribution_survives_tenant_move_and_cannot_be_overwritten`, actual proxy owner read excludes a populated foreign audit row. Sources: `backend/app/routers/logs.py`, `services/{audit_logger,audit_security}.py`, `backend/alembic/versions/m3c5e7f9a1d3_audit_tenant.py`. | Legacy null-attribution records stay hidden; installed schema/cutover and historical backfill are not verified. |
| 6 | Notifications restricted — **PASS**, after P14-A2 | `test_notifications_hide_legacy_and_currently_unauthorized_resources`, `test_notifications_require_membership_at_creation_and_delivery`, `test_delivery_admission_refreshes_preloaded_demoted_recipient`, `test_ticket_email_admission_refreshes_preloaded_demoted_recipient`, both `test_history_admission_refreshes_*` cases, `test_delivery_refreshes_manager_department`, `test_delivery_refreshes_navigation_policy_and_module_cache`. Sources: the three P14-A2 modules and `backend/app/services/workload_notifications.py`. | Actual SMTP/push/webhook delivery is NOT RUN. A message already admitted to an external transport cannot be retracted. |
| 7 | Reauthorization after membership/cache changes — **PASS** | `test_ticket_cache_never_serves_stale_membership_and_role_payloads`, `test_department_and_role_changes_revoke_cached_ticket_access`, `test_task_payload_cache_cannot_preserve_moved_creator_visibility`; changes commit through separate connections. Sources: `backend/app/routers/tasks.py`, `backend/app/tickets/{router,access}.py`. | Sensitive payload caches are bypassed; performance impact at production scale is unmeasured. |
| 8 | Observer task writes denied — **PASS** | `test_observers_read_but_cannot_edit_delete_or_impersonate`, `test_legacy_ticket_task_observer_write_and_foreign_assignment_denied`, multiple-role writer revocation test, real proxy follower PATCH denial. Sources: `backend/app/services/task_access.py`, `routers/comments.py`, `tickets/workflow_service.py`. | Operation-specific exceptions remain as documented; read permission alone is not write permission. |
| 9 | Group assignment visibility — **PASS** | `test_group_role_matrix_and_independent_direct_denials`, `test_ordinary_creator_retains_consolidated_group`, `test_nested_dependencies_do_not_disclose_denied_siblings`, `test_shared_edit_denied_atomically_before_any_write`, `test_transfer_changes_only_selected_assignment_with_distinct_target`. Sources: `backend/app/routers/tasks.py`, `services/task_access.py`. | The independent transfer uses a target different from the sibling assignee, so unchanged sibling assignment is an observed assertion. Browser/realtime-wide group UX remains outside this audit. |
| 10 | Legitimate workflows preserved — **PASS**, targeted regression scope | 23 retained `BusinessRegressions`; `test_valid_ticket_edits_and_sequential_approval_preserved`, valid transfer/bulk/parallel approval tests and `test_multiple_ticket_roles_preserve_writer_and_deleted_grants_do_not`. Sources: task/ticket service paths above; selected frontend task/subtask/reward/cache tests. | Exhaustive product and browser acceptance is **BLOCKED / NOT RUN**; this scoped PASS is not production readiness. |
| 11 | API alias bypass — **PASS**, reviewed routes | `test_aliases_ignore_forged_tenant_and_role_headers`, retained alias matrices and `test_direct_and_nginx_routes_enforce_same_current_authority` exercise canonical, direct `/api`, Nginx `/api` and Nginx `/api/api` paths. Sources: `backend/app/main.py` registrations, route modules, `frontend/nginx.conf`. | No claim about unrelated API endpoints, public TLS, external ingress or every URL-normalization variant. |
| 12 | Department tenancy explicitly addressed — **BLOCKED** | `test_global_department_ownership_is_reproduced_and_blocked` confirms both fixture tenants read the same catalog. Sources: `backend/app/models.py::Department`, `routers/departments.py`, shared Kanban configuration. Ownership/migration alternatives remain documented below. | The documentation requirement is fulfilled, but the tenant boundary itself is unresolved. No ownership policy was invented and no Department/Kanban code/schema was changed. |
| 13 | Session revocation retained — **PASS**, isolated scope | Reran all 51 Phase 1.3 PostgreSQL tests, including `test_postgresql_observed_lock_contention_allows_one_rotation`, `test_preloaded_refresh_record_cannot_hide_committed_consumption`, `test_tenant_round_trip_cannot_revive_tokens`, `test_deactivate_reactivate_requires_new_login`, `test_password_change_and_admin_reset_revoke_all`; fresh-process revocation, presence units/transport and real proxy login/refresh/logout checks. Sources: `backend/app/services/auth_sessions.py`, `routers/auth.py`, session migration and presence implementation; no auth runtime code changed here. | Full browser/native cross-tab/Redis authentication topology remains unverified. Existing generated-token/delegation policy gaps are not closed. |
| 14 | No production data/database/services modified — **PASS**, audit action scope | [Audit scope manifest](../../backend/checks/mcp-phase1-4-audit-scope.json): before/after hashes, local databases and Git index; installed container identity comparison; labeled disposable cleanup. Executed launchers: `run_mcp_phase1_4.py --audit`, `run_mcp_phase1_4_proxy.py`, `run_mcp_phase1_3.py --audit`. | Attests to these audit actions, not unrelated third-party activity. Remote production state was not queried. |

### Executed evidence by test level

| Level | Result | Evidence / interpretation |
|---|---|---|
| PostgreSQL + FastAPI component and concurrency | **52 security/regression methods PASS; one S04 diagnostic confirms the blocker** | [Final Phase 1.4 audit log](../../backend/checks/mcp-phase1-4-audit-after.txt): 10 independent + 19 retained tenant + 23 business methods + one diagnostic = 53 methods. Real PostgreSQL 16, migrations, constraints, row locks, independent commits and actual handlers through TestClient. The diagnostic is not counted as a repaired security boundary. |
| Authentication PostgreSQL integration/concurrency | **51 PASS; fresh-process revocation PASS** | [Authentication rerun](../../backend/checks/mcp-phase1-4-audit-auth.txt): eight independent audit + 43 retained methods; actual database lock contention, atomic rollback, durable replay/logout/epoch revocation and incremental migration checks. Business cases repeated here are not new unique coverage. |
| Real reverse-proxy HTTP/database integration | **One scenario with 80 HTTP checks PASS** | [Proxy log](../../backend/checks/mcp-phase1-4-audit-proxy.txt), [test](../../backend/security_tests/mcp_phase1_4_proxy.py), [launcher](../../backend/security_tests/run_mcp_phase1_4_proxy.py). Actual Nginx, Uvicorn and PostgreSQL; four route forms; positive/negative resource reads, denied writes/relationships, populated tenant audit, inbox, login/refresh/logout/revoked reuse. This is not the earlier source-only rewrite simulation. |
| Presence unit/profile/component | **60 PASS** | Authentication rerun log. Includes controlled deadlines/authority responses, profile and expiry cases. |
| Socket.IO transport integration | **One PASS** | Authentication rerun log. Real client/server traffic and revocation disconnect; controlled HTTP authority, not live FastAPI + Redis. |
| Frontend unit/domain/component | **53 PASS** | [Frontend rerun](../../backend/checks/mcp-phase1-4-audit-frontend.txt): nine selected test files; real Axios/storage code with synthetic transport plus task/notification/subtask/reward checks. Network guard enabled. Not browser execution. |
| Static/scope checks | **PASS for changes** | [Static evidence](../../backend/checks/mcp-phase1-4-audit-static.json): eight Python files parse, no new Ruff F/E9 diagnostics against five hash-verified pre-audit files. One inherited duplicate-function diagnostic remains in `workflow_service.py`; no repository-wide lint-clean claim. Scope manifest records the exact final hashes. |
| Complete full-stack/browser/deployment | **BLOCKED / NOT RUN** | B01–B12 below remain browser acceptance work. No current frontend build + browser + real startup + Redis + presence + proxy/TLS topology or production-scale performance test was run. No installed schema migration or service restart was performed. |

The proxy launcher shares a single **network-none** namespace across three randomly named, ownership-labeled containers. It publishes no ports, mounts only application/migration/test source read-only, uses tmpfs PostgreSQL and fresh secrets, and removes only its owned containers. The copied Nginx configuration changes only upstream `backend:7211` to `127.0.0.1:7211`; prefix stripping and headers are unchanged. App startup is deliberately excluded; the server mounts the actual routers and dependencies in the reviewed fixture application. The IO guard permits only the two numeric loopback HTTP ports in that namespace, while PostgreSQL admission remains restricted to the exact disposable DSN. The Linux image lacks optional libmagic; the app's optional-import fallback is retained, and upload/media paths are NOT RUN. Existing bcrypt/Starlette warnings were recorded; HTTP password authentication nevertheless passed. [Initial proxy harness failure](../../backend/checks/mcp-phase1-4-audit-proxy-initial.txt) came from the optional dependency's linker subprocess hitting the IO guard, before any test execution.

Reproduce this audit from the repository root:

```powershell
.\backend\venv\Scripts\python.exe -I -B backend/security_tests/run_mcp_phase1_4.py --audit
.\backend\venv\Scripts\python.exe -I -B backend/security_tests/run_mcp_phase1_4_proxy.py
.\backend\venv\Scripts\python.exe -I -B backend/security_tests/run_mcp_phase1_3.py --audit
```

### Final disposition and next-stage gates

- **Implemented and tested:** Phase 1.4 tenant/object/cache/observer repairs in the named scope, both independently reproduced corrections, grouped-task regressions, incremental audit migration, retained durable sessions and actual HTTP proxy enforcement.
- **Implemented but not tested end to end:** current full application startup/deployment wiring, browser authentication/native cross-tab behavior, browser business flows, Redis/presence composition and real external notification delivery. No readiness claim is based on their design or existing documentation.
- **Designed but not implemented:** department/configuration ownership migration, automated session cleanup scheduling, and dedicated MCP OAuth/delegation/consent/grant enforcement. This audit implements none of them and adds no Settings interface.
- **Unresolved:** S04 ownership and legacy mapping, full-stack/browser gates, installed-schema lineage/backup/cutover validation, and S07's remaining delegated identity/audience/client/consent/scope/revocation requirements. S08 read-side effects still require an explicit contract for any future read-only MCP tool.

**GO for a scoped next security stage** to settle department/configuration ownership and complete disposable full-stack/database/authentication acceptance. **NO-GO for MCP implementation or production release.** Ordinary application sessions and these REST checks do not establish OAuth delegation. Resolve the multi-tenant blocker and independently verify issuer/audience/resource binding, client/subject linkage, consent/scopes, durable grant revocation and delegated backend enforcement before considering an MCP stage.

## Implementation-stage acceptance matrix (historical)

PASS means an executed assertion within the stated scope. BLOCKED is not a security pass. A diagnostic that confirms a known gap is not counted as a successful security boundary.

| # | Criterion | Result | Evidence / limits |
|---|---|---|---|
| 1 | Cross-tenant task transfers denied | PASS | Foreign targets denied for User, Manager, Admin and Owner; inactive targets, unrelated actors and Managers without a department denied. Rejected requests leave assignments and request counts unchanged. Bulk transfer preflight tested. |
| 2 | Unauthorized transfer approvals denied | PASS | Unrelated Manager, foreign staff and ordinary actors denied; target tenant rechecked at approval; valid department Manager succeeds. Two PostgreSQL sessions racing the same request yield one success and one 409. Replays cannot act twice. |
| 3 | Ticket-related user references tenant scoped | PASS | Owner/assignee/follower/participant/approver grants rejected for foreign users; inactive grants rejected. Default Manager assignment is tenant scoped. All three approval implementations, linked task creation and legacy ticket-task assignees covered. Relationship removal and valid updates exercised. |
| 4 | Ticket subresources enforce object permissions | PASS | Retained S03 role/tenant matrix, both aliases, parent denial before protected queries, linked-task/dependency filtering, and behavior without the global navigation dependency pass. Legacy ticket-task writes also require parent access and writer membership. |
| 5 | Audit logs tenant isolated | PASS | Event-time ownership, immutable PostgreSQL attribution, list totals, JSON/CSV exports, retry, retention application, Manager resource scope, legacy exclusion and credential-field redaction tested. Actor tenant moves cannot move the event or expose the actor's new profile. |
| 6 | Notifications tenant/object authorized | PASS | Own inbox plus current ticket/task access; foreign, forged, unlinked and null-tenant notices hidden from lists/counts/read/delete. Creation, push/webhook dispatch and ticket email selection reject unauthorized recipients. Actual external delivery is NOT RUN. |
| 7 | Cache cannot bypass current permissions | PASS | Sensitive ticket/task payload cache reads bypassed. Membership removal committed in a separate connection, department change, Admin demotion and deactivation tested. Old role-bound credentials return 401; newly authorized credentials see only current scope. |
| 8 | Read-only users cannot perform unauthorized writes | PASS | Task follower may read but cannot PATCH/delete/comment. Staff cannot impersonate comment authors; unrelated Managers denied; authorized Manager self-authored comment succeeds. Legacy ticket-task follower writes denied. |
| 9 | Grouped visibility remains correct | PASS | Retained creator/assignee/follower/staff matrix; hidden siblings and nested dependencies; all-peer shared-write preflight; independent status updates and preserved group/assignment IDs pass. |
| 10 | Valid task/ticket workflows preserved | PASS | 23 retained domain regressions, valid single/bulk transfers, participant add/remove, default assignment, ticket edit, parallel and sequential approval, linked tasks and existing scoring assertions pass. This is targeted regression coverage, not exhaustive product certification. |
| 11 | Department ownership safely implemented or explicitly blocked | BLOCKED | Explicit stop under Step 7. Diagnostic confirms both tenants read the shared catalog. Model/routes not changed; proposed ownership/migration and approval decisions below. The requested documentation alternative is fulfilled, but S04 remains open. |
| 12 | Relevant isolated security tests pass | PASS | Final Phase 1.4 run: 42 security/regression methods plus one S04 diagnostic; Phase 1.3 rerun: 51 PostgreSQL methods, fresh-process check, 60 presence checks and one controlled Socket.IO transport check; 53 selected frontend checks. See evidence and isolation limits below. |
| 13 | Browser/full-stack verification | BLOCKED — NOT RUN | Separate execution plan below. No disposable stack with backend, frontend, PostgreSQL, Redis, proxy and presence was available. Existing local services were not used as test targets. |
| 14 | No production systems modified | PASS, action scope | Test runners only created/remigrated their own random tmpfs PostgreSQL containers. File hashes, Git index and existing-container identity checks recorded in the scope evidence. No deployment, existing-database migration, service restart, credentials change or production request performed. Remote production state was not inspected. |

## Findings and implementation

| Finding | Baseline behavior and affected source/endpoints | Minimum repair and current state |
|---|---|---|
| S01 | `routers/tasks.py`: bulk `/tasks/transfer`, task transfer request and decision routes (also `/api`). Request creation checked read access and target existence; decision checked staff role, but not task write scope. Recipient queries could select foreign staff. | Implemented and tested: same-tenant source/target, active target, independent task writer gate and Manager source/target department checks. Entire bulk batch locked/checked before assignment mutation. Decision acquires task lock then refreshes request under `FOR UPDATE`; checks pending status, current source assignment and current target eligibility. Notifications filtered to eligible approvers and current readers. |
| S02 | `tickets/service.py`, `approvals_service.py`, `workflow_service.py`, `task_engine_service.py`, `task_link_service.py`: create/update relationships, participants, three approval representations and linked/legacy tasks accepted unscoped IDs. Default department Manager query lacked tenant. | Implemented and tested: shared `require_tenant_users` preflight before grants; identity-map refresh; tenant-bound default selection. Every supplied owner and assignee is validated even when field precedence would discard one. Existing follower history may retain inactive same-tenant members; new/restored grants require active users. Invalid links can be removed without granting new access. Existing task completion cannot credit a foreign tenant's wallet. |
| S03 | Prior fixes protected `/tickets/{id}/logs` and `/tickets/{id}/tasks`, including aliases and nested task expansion. | Preserved and regressed. Shared ticket predicate used for current read scope; legacy ticket-task mutation also checks parent and writer scope. |
| S04 | `Department` has global ID/name and globally unique name; no tenant. Department list/admin routes and Kanban configuration are shared. | **Unresolved / explicitly blocked.** No Department or Kanban model, route, ID or migration change. See decision section. |
| S05 | Prior fixes authorize each grouped assignment and every peer affected by shared edits. | Preserved and regressed. Transfer reconciliation still affects the selected assignment only. No new group privilege or group-wide assignment propagation. |
| S06 | `AuditLog` had no tenant column; `/logs/audit` Owner/Admin queries were effectively global except configuration exceptions. Manager actor/target department matching could cross tenants. Retry and retention had global paths. | Implemented and tested: nullable event-time `tenant_id`, immutable update trigger and tenant/date index; shared query predicate before pagination/count/export/retry. Owner/Admin retain tenant-wide audit visibility. Manager task/ticket/subtask/approval/notification audit scope follows current resources; other actor/target scope is tenant/dept bounded. Tenant retention application cannot mark another tenant's logs. Global retention configuration PATCH returns 409 pending ownership decision. |
| S09 | Ticket cache hit returned before current object/membership filtering; staff task cache could outlive creator tenant changes. | Implemented and tested: bypass authorization-sensitive task/list/Kanban/calendar and ticket list payload caches. Existing invalidation remains. No claim that a TTL, user key or role label alone establishes authorization. No new authorization-generation mechanism invented. |
| S10 | Ordinary task update reused read policy, deletion used read permission, comments allowed every same-tenant Manager and staff-selected authors. | Implemented and tested: canonical editor gate separates followers from writers; explicit deletion guard; scoped Manager comments and self-authorship. Ticket-linked global tasks retain the existing creator/assignee-only write restriction, including for staff. |
| S11 | Inbox accepted null-tenant legacy rows; ticket bodies and entity-only task references lacked current object checks. Generic dispatcher did not bind tenant or verify recipient access. | Implemented and tested: shared SQL resource predicate applies before counts/pagination/actions, including approval references. Null-tenant/unlinked resource notices retained but hidden. Generic history creation, stored push/webhook delivery and ticket email selection check current recipient tenant/status/resource/module access. Ticket approval producers now include canonical ticket links. |

The original vulnerabilities were confirmed by source review; this phase's executed security tests assert the repaired behavior. It does not claim a separate executable baseline reproduction for each repaired finding. S04 was explicitly reproduced on disposable fixtures. Initial test-development failures are retained separately and do not count as security passes.

One adjacent defect in the edited ticket-update function used undefined `update_fields` when notifying the creator. It now tests the existing `changes` mapping. A successful authorized ticket update regression covers this correction. No scoring formula or award amount was changed.

## Authorization contract

| Operation | Current rule |
|---|---|
| Ordinary task read | Existing creator-tenant gate; Owner/Admin tenant-wide, Manager own/assigned/followed or assignee department, ordinary creator/assignee/follower. |
| Ordinary task edit/delete | Creator or assignee; Owner/Admin within tenant; Manager with matching nonempty assignee department. Following alone grants no write. Immutable-history delete restrictions remain. |
| Ticket-linked global task write | Creator/assignee only, regardless of staff role. |
| Task transfer | Above writer rule plus same-tenant source/target, active target. Manager requires nonempty department matching source and target. Staff retains auto-approval only when these checks pass; ordinary permitted writers create pending requests. |
| Comment | Current task editor rule, author must be the authenticated user. Delete retains own-author/staff moderation check plus task writer authorization. No delegated author impersonation. |
| Ticket read | Tenant first; Owner/Admin tenant-wide. Manager must match nonempty ticket department, before participant fallback. Ordinary creator/owner, live participant/follower or pending approver. SQL predicate includes cycle, legacy and sequential pending approvals so recipients can use their authorized workflows. |
| Ticket writes | Existing operation-specific creator/owner/assignee/staff rules retained; no universal Manager write grant. Legacy ticket-task followers are read-only. Approval decisions retain named approver/turn/role checks and now recheck ticket scope. |
| Relationship changes | Validate all new linked IDs before any domain mutation. New/restored references require active same-tenant users. Existing historical rows are not silently reassigned or backfilled. |
| Audit | Persist event-time tenant from authenticated server context or explicit server-owned resource context. Never infer historical ownership from an actor's current tenant. Unknown ownership is hidden. |
| Notification | Active recipient in stored tenant, own inbox and current referenced-object access. Resource notifications missing canonical attribution are hidden. Existing task-deletion tombstones retain their explicit tenant-bound deletion policy. |

Revocation is evaluated at request/delivery admission. An already authorized in-flight request or external message cannot be retroactively retracted. The cache test proves a request after a committed membership change sees the change; it does not claim serializable cancellation of all in-flight reads.

## Audit migration and compatibility

New revision: [`m3c5e7f9a1d3_audit_tenant.py`](../../backend/alembic/versions/m3c5e7f9a1d3_audit_tenant.py), parent `l2b4d6f8a0c2`.

- Adds nullable UUID `audit_logs.tenant_id` and `(tenant_id, created_at)` index. It does not rewrite any existing audit/user/task/ticket record.
- Installs a PostgreSQL trigger prohibiting tenant-attribution changes. Legacy NULL remains NULL; no actor-based backfill.
- Read-only startup preflight requires the column and enabled trigger before existing startup helpers run. It performs no migration or repair. Backup/export registry includes the new tenant field.
- HTTP audit producers use authenticated context. Login/registration/reset, ticket services, notification delivery and webhook workers record explicit trusted tenant when available. Truly unattributed system/legacy events remain stored and excluded from tenant views.
- Structured payloads redact credential-like keys recursively and bearer/JWT strings. Opaque legacy `old_value`/`new_value` strings are redacted on output. Actor profiles are suppressed after actor tenant movement. This preserves stored history while reducing the UI/export view.
- Owner/Admin audit access remains tenant-wide. Global retention configuration changes are blocked; retention application is tenant scoped and leaves unattributed/foreign rows intact. Choosing a tenant-specific retention configuration model is a remaining product decision.
- Upgrade/downgrade/upgrade was executed only on disposable PostgreSQL, preserving fixture users and audit rows. Enabled/disabled trigger startup checks and immutable attribution were exercised. The test constructs predecessor-compatible tables from metadata then executes the actual incremental revisions; it does **not** verify the entire historical Alembic chain from an empty database.

**No existing database was migrated.** The local recovery described in [Phase 1.3 startup recovery](PHASE_1_3_LOCAL_STARTUP_RECOVERY.md) was separately authorized earlier and does not authorize Phase 1.4 deployment. That installation was historically unversioned; do not stamp it or blindly run the full Alembic chain. Before a separately approved rollout, inspect lineage/drift, back up, restore a disposable copy and rehearse the exact additive change. Index creation takes a table lock; review table size and the migration's 5-second lock / 120-second statement limits during the rehearsal.

Do not deploy new source before the audit migration. Old readers must not remain exposed after cutover because they lack these authorization gates. Downgrade removes event ownership and is suitable only for disposable verification; it is not a secure production rollback plan. Preserve the attribution column/trigger and forward-fix with an enforcing release.

Compatibility changes are intentional: inactive/foreign relationship grants fail; no-department Managers cannot transfer; observers cannot edit/delete/comment as writers; staff comments require self-authorship; stale resource notices and unattributed audit history disappear from views without being deleted; sensitive audit values are redacted; global retention setting edits return 409. Payload-cache bypass may increase database reads. Production load/performance testing is NOT RUN.

## Department/configuration decision — STOPPED

Verified model: `models.Department` contains only `id` and globally unique `name`; Users reference it by string ID. Tickets and SLA policies also carry department IDs. Manager permissions, filters, default assignee resolution, department transfers and notification recipient selection depend on these references. `KanbanColumn` is similarly global configuration. The isolated diagnostic confirms two unrelated tenant owners receive the same Department catalog.

Recommended future model: tenant-owned operational departments with tenant-scoped uniqueness and validated user/ticket/SLA references. If a global catalog is intentional, separate immutable shared catalog entries from tenant-owned operational department membership and customization. This is a recommendation, not an implemented model.

Proposed migration, requiring approval first:

1. Inventory departments and all referencing tenants on a restored disposable copy; classify unreferenced, single-tenant and multi-tenant departments. Do not infer ownership from a single current user or ticket.
2. Approve how multi-tenant departments are split or represented, how duplicate names behave and whether IDs must remain stable. Produce an explicit mapping manifest covering users, tickets, SLA configuration, filters and imports/exports.
3. Rehearse an additive compatibility period, tenant-qualified foreign references and scoped uniqueness. Validate historical records and Manager permissions before switching readers/writers. Plan a rollback that does not merge tenant data.
4. Review Kanban and global retention configuration separately; department ownership is not automatic approval to change every global configuration table.

Required decisions: intentional global versus tenant ownership; treatment of shared/unknown rows; ID and name compatibility; Manager policy across migrations; ownership of global retention settings; operator approval of the reviewed mapping and deployment window. Risks include changed Manager visibility, broken imports/bookmarks, ambiguous historical references and accidental cross-tenant remapping. **No department column, reference, name, ID, route or migration was changed here.**

## Implementation-stage verification and boundaries

Evidence:

- [`mcp-phase1-4-security.txt`](../../backend/checks/mcp-phase1-4-security.txt): final PostgreSQL suite; 42 security/regression methods and one explicit S04 diagnostic. Diagnostic success means the global-catalog gap was confirmed, not fixed.
- [`mcp-phase1-4-first-run.txt`](../../backend/checks/mcp-phase1-4-first-run.txt): six fixture failures from the initial 37-method run. Required enum/field inputs, module ceiling and preexisting fixture alerts were corrected; no authorization assertion was loosened to accept an insecure response.
- [`mcp-phase1-4-auth-regression.txt`](../../backend/checks/mcp-phase1-4-auth-regression.txt): retained independent Phase 1.3 audit, 8 + 43 PostgreSQL methods, fresh interpreter revocation check, 60 presence checks, one real Socket.IO transport check with controlled authority.
- [`mcp-phase1-4-frontend.txt`](../../backend/checks/mcp-phase1-4-frontend.txt): 53 selected Node/TypeScript unit/domain/component assertions; includes real Axios interceptors/storage with synthetic transport. These are not browser tests.
- [`mcp-phase1-4-static.json`](../../backend/checks/mcp-phase1-4-static.json): 27 changed/new Python files parse; no new Ruff F/E9 diagnostics against hash-verified source baseline. 25 preexisting diagnostics remain, including duplicate definitions and unreachable legacy code. No claim of a clean repository-wide lint/typecheck.
- [`mcp-phase1-4-scope.json`](../../backend/checks/mcp-phase1-4-scope.json): preservation and action-scope evidence.

Run the isolated suite from repository root:

```powershell
.\backend\venv\Scripts\python.exe -I -B backend/security_tests/run_mcp_phase1_4.py
.\backend\venv\Scripts\python.exe -I -B backend/security_tests/run_mcp_phase1_3.py --audit
```

Each launcher owns a random labeled PostgreSQL 16 container with tmpfs data, no host data mounts and an ephemeral loopback port. Children run in an empty scratch directory with sanitized environment/fresh keys. Guards block installed application startup, legacy test collection, SQLite, external TCP/UDP/DNS and subprocess execution; psycopg2/SQLAlchemy admit only the exact owned database. Cleanup validates ownership labels. Fixture emails, passwords and identities are synthetic. No delivery credentials are loaded.

PostgreSQL coverage uses actual SQL, row locks, migration operations and independent connections. FastAPI handlers execute through TestClient in process; this is HTTP-component/database integration, not a deployed server/proxy test. Outbound side effects are disabled or replaced with recording boundaries. The Socket.IO test runs in an isolated container with a controlled authorization endpoint, not the installed FastAPI/Redis topology. Tests shared between phase runners are repetitions, not additional unique coverage.

## Separate browser/full-stack authentication plan

**Execution: NOT RUN.** Blocker: no disposable full stack with seeded users, backend, frontend, PostgreSQL, Redis, proxy, presence and controlled delivery services was available. A working installed local application is not a disposable fixture. Do not point these tests at it.

Provisioning prerequisites: unique Compose project/network/ports, ephemeral databases/Redis, scratch uploads, fresh signing keys, synthetic SMTP/webhook sink, two seeded tenants and all four roles, installed migrations, current compiled frontend/presence, and deny outbound delivery. Record image/source digests and destroy only owned labeled resources.

| ID | Scenario | Required browser/transport evidence | Status |
|---|---|---|---|
| B01 | Login/logout | Valid JSON/form login through proxy; protected page works; logout clears storage and old REST/presence credentials fail. | NOT RUN |
| B02 | Refresh rotation | Expired access refreshes once; both stored tokens rotate; old refresh replay fails and family revokes. | NOT RUN |
| B03 | Reload | Reload authenticated routes before/after refresh without token loops or stale page data. | NOT RUN |
| B04 | Multi-tab | Simultaneous 401s coordinate one refresh; logout/session change propagates; storage events do not restore old tokens. | NOT RUN |
| B05 | Session expiration | Absolute expiry and expired presence token terminate access; retries do not create infinite loops. | NOT RUN |
| B06 | Deactivate/reactivate | Active HTTP/socket traffic loses access; reactivation requires a new authorized session. | NOT RUN |
| B07 | Tenant A → B → A | Old browser and presence credentials fail at both moves; lists, inbox and caches never restore old authority. | NOT RUN |
| B08 | Socket connection/reconnection | Task/chat/ticket and presence connections reject revoked sessions; reconnect uses a fresh permitted credential. | NOT RUN |
| B09 | Presence renewal | Renewal before expiry, delayed response, backend outage, recovery and stale response race obey the bounded revocation contract. | NOT RUN |
| B10 | Password change/reset | Self-change/admin reset invalidate the policy's sessions; fresh login works; old tabs cannot refresh. | NOT RUN |
| B11 | Resource revocation | Remove ticket follower/participant, change Manager department/role; open pages, counts, inbox and reconnect show current scope. | NOT RUN |
| B12 | Business smoke | Creator group view, individual assignee updates, permitted transfers, ticket approvals and existing scoring UI remain usable. | NOT RUN |

Capture status codes, request IDs, socket disconnect timing and redacted browser traces. Never record token values. Each scenario needs an observed result; plans and unit tests cannot substitute for browser execution.

## Implementation-stage changed files and preserved scope

This is the original implementation inventory. The independent audit subsequently changed only four runtime modules, extended the Phase 1.4 test launcher, added three audit/proxy test files, and updated this report/evidence. See the audit scope manifest for that separate delta.

Twenty existing Python files changed during implementation:

- `backend/app/{models.py,main.py,dependencies.py}` and `backups/registry.py`: audit attribution, preflight/context and backup field.
- `backend/app/routers/{auth.py,comments.py,logs.py,tasks.py}`: explicit auth audit tenant, task/transfer/comment authorization, scoped audit endpoints.
- `backend/app/services/{task_access.py,audit_logger.py,notification_dispatcher.py,workload_notifications.py}`: writer policy, event capture, notification creation/delivery/query policy.
- `backend/app/tickets/{service.py,router.py,approvals_service.py,workflow_service.py,task_engine_service.py,task_link_service.py}`: relationship preflight, current ticket policy and cache bypass.
- `backend/app/notifications/service.py`, `webhooks/dispatcher.py`: ticket recipient checks and worker audit attribution.

Seven new Python files: `services/{tenant_users.py,audit_security.py,notification_access.py}`, `tickets/access.py`, migration `m3c5e7f9a1d3_audit_tenant.py`, and `security_tests/{run_mcp_phase1_4.py,mcp_phase1_4_cases.py}`. This report and Phase 1.4 evidence files are also new.

The start-of-phase manifest covers 2,047 existing files, including nine local database files and the Git index. Preservation is checked against that manifest rather than HEAD alone because prior work was already dirty/staged. No reset, staging, commit, dependency install, frontend/presence source change, Compose edit, MCP implementation or deployment was performed in this phase.

## Remaining gates and Phase 1.5 prerequisites

**Implemented and tested:** S01/S02/S06/S09/S10/S11 repairs on the named surfaces; S03/S05 regressions; additive audit migration on disposable PostgreSQL; retained Phase 1.3 authentication behavior.

**Implemented but not tested in a full deployed stack:** proxy/browser behavior of these changes, real Redis/presence/backend integration, push/email/webhook delivery, backup restore with new audit attribution and production-scale performance. No production migration or application startup was exercised.

**Designed but not implemented:** department/Kanban/retention ownership migration; reviewed attribution of historical records; authorization-generation caching; disposable browser environment/plan execution. Existing legacy rows are retained rather than silently migrated.

**Unresolved:** S04 product/ownership decision, complete browser authentication gate, safe installed-schema lineage/cutover, and the MCP delegated-security boundary. Phase 1.4 does not turn existing JWT scopes into OAuth delegation.

The independent audit above is complete within its stated scope. Phase 1.5 should obtain the department/configuration decisions, run the disposable full-stack plan and rehearse installed-schema/backup compatibility on a copy. Before any MCP phase, separately approve and implement issuer/identity linkage, audience/resource-bound OAuth tokens, per-client consent/scopes, durable grant revocation, backend enforcement of delegated authority, trusted write approval/idempotency, and tool/output allowlists. Review token exchange versus passthrough explicitly. Ordinary application sessions are not MCP grants.

**GO: continue bounded Phase 1.5 remediation and verification. NO-GO: MCP implementation, MCP Settings/OAuth UI, production release or migration until the outstanding gates are resolved and separately authorized.**
