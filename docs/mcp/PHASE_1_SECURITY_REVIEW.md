# Phase 1 security review

Date: **11 November 2026, Asia/Calcutta**. Baseline: `8978158` and current source. Starting point: [feasibility report, section 9](../MCP_FEASIBILITY_REPORT.md). **All findings below remain open; no production authorization behavior was changed.** Verified means source-confirmed unless a specific isolated test is cited. The independent review additionally reproduced S03/S05/S07 observations against synthetic in-process fixtures only; no production installation or existing database was exercised.

Companion documents: [architecture/authentication](PHASE_1_ARCHITECTURE.md), [permission policy](MCP_PERMISSION_MODEL.md), [test results and pending cases](PHASE_1_TEST_PLAN.md). All canonical paths below also have `/api` aliases when their router is registered twice. `tickets/workflow_router.py` is already `/api`-prefixed and is registered once; do not invent non-prefixed aliases for it.

## Verification summary

| ID | Current-source determination | MCP disposition |
|---|---|---|
| S01 | Confirmed target integrity and same-tenant approval/object gaps; foreign-task decisions are additionally guarded by locking before mutation, refining the report | Exclude transfer workflows; critical release blocker for assignment tools |
| S02 | Confirmed missing same-tenant related-user validation across multiple ticket setters | Exclude ticket writes and affected expansions |
| S03 | Confirmed tenant-only ticket task/log reads without ticket membership. Isolated non-member reads return private logs; task query runs before response validation fails on UUID ticket ID | Exclude these subresources; fix authorization and schema contract independently |
| S04 | Confirmed global Department and Kanban configuration model/query scope | No department/configuration MCP administration |
| S05 | Confirmed anchor-only group read and unchecked shared-field peer writes; denied sibling disclosure reproduced through both group aliases | Group assignment visibility FAIL; no group tool/shared-field write until approved policy and repair |
| S06 | Confirmed ordinary audit scope is broader than tenant | No ordinary audit export/reuse for MCP activity |
| S07 | Confirmed REST scope/audience/grant-revocation gaps; signed token with no expiry accepted on both task aliases. Status denial reverses on reactivation | OAuth/delegation is a mandatory new boundary; status checks are not persistent revocation |
| S09 | Confirmed ticket list cache returns before service object filtering; current user still authenticates first | Withhold ticket list adapter pending cache fix |
| S10 | Confirmed different parent, activity and comment write boundaries | No observer/parent write assumptions |
| S11 | Confirmed current task checks coexist with legacy null-tenant and ticket-body gaps | Withhold notification export |

The independent review's isolated suite reports **20 successful unittest methods**: 13 current-policy regression methods, 4 isolation methods and 3 diagnostic methods. The diagnostics report **six FAIL observations for three open findings**, and the launcher intentionally exits **2**. A successful diagnostic means it measured the behavior, not that security passed. S05 group aliases, S03 task/log subresources and S07 missing-expiry aliases remain failed gates. Existing legacy tests named below were inspected, **NOT RUN** in this review. See the test plan for the exact results and scope.

## S01 — Task transfer authorization

**Root cause/evidence.** `routers/tasks.py::create_task_transfer_request` fetches/locks the task and checks `_ensure_task_access`, but only checks that `to_user_id` exists. It does not validate target tenant or active status. Manager/Admin/Owner immediately auto-approve and replace `assigned_to_id`. The pending-request recipient queries select Managers and Admins/Owners globally. `act_on_transfer_request` checks staff role, pending status and task existence/lock, but never `_ensure_task_access` or an operation-specific approval rule.

**Important correction to the starting report.** `_fetch_task_or_404(..., lock=True, actor=current_user)` invokes `subtask_rewards.lock_scope(..., tenant_id=actor.tenant_id)`, which rejects a foreign-tenant task **before** assignment/decision mutation. Later `_reconcile(authorized_parent_write=True)` also checks active actor and creator tenant. Thus this is not evidence that foreign staff can complete a foreign-task approval. The same-tenant unrelated Manager/object gap remains. `_reconcile` returns before target-assignee validation if the task has no children using the managed point policy; a foreign target is therefore not comprehensively rejected by downstream accounting. Atomic rollback must still be tested for managed-child failures.

**Affected paths/services.** `POST /tasks/{task_id}/transfer-requests`, `POST /tasks/transfer-requests/{request_id}/approve`, `GET /tasks/{task_id}/transfer-requests`, and notification delivery created by these paths. `POST /tasks/transfer` is a different bulk handler: it already checks both user tenants and staff role; Manager department restriction runs only when the Manager has a department. It needs its own policy/tests, not the claim that all transfer APIs have the same omission.

**Expected policy.** Same-tenant target and actor, authorized task operation and approver, no foreign recipients. Active target eligibility and who approves/auto-approves within a department need an explicit policy decision. Read access/follower membership is not silently redefined as transfer authority.

**Existing tests.** `test_task_tabs_review.py::test_task_updates_reject_cross_tenant_members_and_dependencies` covers canonical PATCH relationships, not transfer decisions. Targeted search found no focused transfer-workflow negative test in `backend/tests`. New Phase 1 cross-tenant PATCH assignment denial passes; it does not test transfer safety.

**Smallest proposed fix.** Before creating/acting on a request, validate task tenant and target tenant through one shared guard; restrict recipient candidates by tenant and actual approval authority. Add operation authorization to both auto-approval and decision handlers, preserving pre-change actor access and accounting locks. Resolve Manager/follower approval policy before changing those rules. Recheck target on decision to handle account changes. No fix was applied.

**Regressions to protect.** Legitimate departmental delegation; former assignee access after reassignment; pending request deduplication; approval notifications; group/reward locking and atomic rollback; target deactivation between request/decision; bulk versus single transfer parity. Existing queue/email payloads may retain data even when inbox visibility later hides a notification.

## S02 — Ticket relationship tenant isolation

**Root cause/evidence.** `tickets/service.py::create_ticket` copies owner/assigned-user and approver IDs after format/count checks, without loading every user inside the ticket tenant. `update_ticket` similarly assigns owner/assignee and approver arrays. `_set_followers` inserts IDs directly; `update_participants` checks actor authority but inserts/restores related participant IDs without same-tenant lookup. `_resolve_default_assignee` filters active department Managers without a tenant predicate. `tickets/task_engine_service.py::create_ticket_task` checks approver existence only. `tickets/approvals_service.py::request_ticket_approvals_sequential` builds generic approval rows from selected IDs without a per-user tenant lookup.

**Affected paths/services.** `POST /tickets`, `PATCH /tickets/{id}`, `POST /tickets/{id}/participants`, approval request/create variants in `tickets/router.py` and `workflow_router.py`, and `POST /api/tickets/{id}/tasks`. Ticket transfer selects a global department and is also constrained by S04. Ticket participants/followers/approvals, notification destinations, task links and rich ticket reads may consume malformed relationships. A row having `tenant_id` does not prove its linked user belongs to that tenant.

**Expected policy.** Related users must belong to the ticket tenant; actor must be authorized for the operation. Active account eligibility, whether current inactive historical members remain visible, and eligible approver roles need approval. Preserve historical relationships rather than silently deleting them.

**Existing tests.** `test_ticket_tenant_permissions.py::test_ticket_tenant_isolation` checks top-level ticket boundaries and `test_ticket_permissions_close_reopen_delete` checks selected transitions. That module imports `main` and drops/creates a relative file DB at collection: it was not imported/run. No comprehensive negative matrix for every relationship setter was found in the inspected tests. New suite verifies top-level same-tenant membership and foreign-ticket denial only.

**Smallest proposed fix.** A shared tenant-aware relationship resolver used by each create/update/approval/task-link setter **before** mutation or notification. Keep field shapes and workflow semantics; validate all nested arrays and restorations. Pass tenant into default-assignee resolution. Until Department ownership is decided, do not pretend a same-tenant department can be verified from its present schema.

**Regressions to protect.** Auto-assignment, creator-following, participant restoration/removal, maximum-five approvers/sequential order, duplicate IDs, legacy inactive/foreign links, notification/approval fanout and rollback of partially valid arrays.

## S03 — Ticket subresource permissions

**Root cause/evidence.** `tickets/workflow_router.py::list_ticket_tasks_handler` and `list_ticket_logs_handler` accept `get_tenant_id` but no current user/object authorization. App-wide navigation normally authenticates an ACTIVE user for ticket module access; it does not prove membership in this ticket. `task_engine_service.list_ticket_tasks` calls tenant-aware `get_ticket` and loads all matching tasks without per-task visibility. `workflow_service.list_ticket_logs` filters log tenant/ticket and bounds pagination but does not call `get_ticket_for_user` (or establish ticket existence).

**Affected paths.** `GET /api/tickets/{ticket_id}/tasks`, `GET /api/tickets/{ticket_id}/logs`. Only prefixed routes are registered for these handlers. Proxy prefix stripping may make the public URL unavailable or reach a different path; that is not an authorization repair. Task-link writers and other expansions need the same actor-aware boundary when reused.

**Independent isolated observation.** A peer denied 403 on the parent ticket receives a stored synthetic private audit row from `/api/tickets/{id}/logs` with 200. The task endpoint invokes the actual linked-task query for the same non-member, then raises response validation because ORM `Task.ticket_id` is a UUID while `schemas.TaskRead.ticket_id` expects a string. That route's content disclosure was **not confirmed** through a successful HTTP response. It still lacks the required pre-query authorization; serialization failure is not a permission boundary and fixing only serialization would unmask it. The test observes the real query/serializer without changing production code or coercing the UUID to manufacture a 200 response.

**Expected policy.** First authorize the ticket with `get_ticket_for_user`, then enforce the chosen task-expansion policy. Canonical task visibility must not be broadened because a caller can view its ticket unless that broader access is explicitly approved. Ticket log access inherits current ticket visibility and a reviewed field-redaction policy.

**Existing tests.** `test_final_api_contracts.py` checks path/schema existence, not negative object permissions. Top-level ticket tenant tests do not establish subresource safety. The independent Phase 1 diagnostic now exercises both missing-membership paths; its FAIL gates do not replace the broader pending role/tenant/expansion matrix.

**Smallest proposed fix.** Pass authenticated active user/current roles to the services, call `get_ticket_for_user` before querying, and filter nested tasks using the canonical task policy. Reuse the guard rather than adding a role-only exception. Decide whether unauthorized nested tasks are omitted or cause a denied expansion before rollout.

**Regressions to protect.** Pending approver access; Manager department behavior; deleted/foreign ticket existence semantics; pagination totals matching authorized items; alias/collision/proxy behavior; partial expansions and task/ticket membership disagreement.

## S04 — Global department scope

**Root cause/evidence.** `models.py::Department` has only id/name and user relationships, no tenant ownership. `routers/departments.py` lists/updates/deletes globally and its admin-recipient lookup is global. `models.py::KanbanColumn` and `routers/kanban.py` are also global configuration. Attaching a user or ticket tenant to a global ID does not establish ownership of that department.

**Affected paths/services.** All `/departments` CRUD and aliases, `/kanban` configuration, ticket default assignment/department transfer, Manager task/ticket/log filters, user department selection. The issue extends beyond a single list filter.

**Expected policy/decision.** Determine whether these entities are intentionally installation-wide metadata or tenant-owned. The source does not prove a company owner. If global is intended, explicitly define who may modify global data; a tenant Owner is not automatically a platform operator.

**Existing tests.** Task and ticket tests use department fixtures but do not establish ownership. Navigation and profile tests cover role ceilings/related-user behavior, not a tenant-owned Department model. No ownership assertion can safely be added as an existing-policy regression now.

**Smallest proposed fix.** Immediately withhold these tools from any future MCP catalog. For REST repair, choose either explicit global administration policy or separately approved additive ownership/mapping work. Do not add an arbitrary tenant filter or derive department ownership from its first user. No schema change/backfill is authorized here.

**Regressions to protect.** Shared department names/unique constraints; existing Manager scopes, notifications, user/ticket references, Kanban labels and status enums, multi-tenant legacy data mapping and deletes. This blocker requires product/data-ownership approval.

## S05 — Grouped-task sibling visibility and updates

**Root cause/evidence.** `routers/tasks.py::get_task_group` checks the anchor then selects every same-tenant row with its `task_group_id`, without per-sibling `_ensure_task_access`. `update_task` propagates shared title/description/priority to peer rows using group/tenant predicates only. Accounting's `authorized_parent_write=True` validates tenant and active actor, not each peer's operation access. Group creation/merging also touches existing group records and must be included in later authorization review. A group ID is not an assignment permission.

**Affected paths/services.** `GET /tasks/{id}/group`, `PATCH /tasks/{id}`, grouped `POST /tasks`/template assignment, serializers, group-aware reward locks/reconciliation and notification/event consumers. Full downstream expansion/WebSocket/email/export parity must be tested before any fix is called complete.

**Expected policy/decision.** Canonical direct/list task checks already distinguish creator, individual assignee, observer and department Manager. That unambiguous boundary is tested here. Whether every assignee intentionally sees all sibling assignments, and who may change shared group fields, is unresolved in this checkout. Prior fixes in other checkouts are not evidence of this checkout's intended policy. Do not silently change existing group UX/workflow.

**Existing tests.** `test_task_tabs_review.py` tests direct tenant/unrelated-user denial and foreign relationship minimization; it is not proof of group policy. Phase 1 tests show that an ordinary assignee can read its row, cannot directly read its sibling, and sees its authorized rows only in `/tasks/page`, for both aliases. The independent diagnostic additionally reproduces `/tasks/{anchor}/group` and `/api/tasks/{anchor}/group` returning that directly denied sibling. Both are reported **FAIL**, not treated as an approved broader visibility policy. No group mutation or production behavior was changed.

**Smallest proposed fix after approval.** Define one assignment/group authorization policy and apply it to group selection, all nested outputs and each shared-field write. Preserve creator/authorized staff access and existing group IDs. Reject an unauthorized shared mutation atomically rather than partially updating peers. Keep group lock ordering and accounting semantics; do not redesign group records.

**Regressions to protect.** Grouped cards, creator multi-assignee control, partial visible groups/counts, dependency/user expansions, shared-field consistency, multi-peer rewards and notifications, filters, cache/event/email payloads, template assignment and concurrent edits. No task-group behavior changed in Phase 1.

## S06 — Audit log tenant isolation

**Root cause/evidence.** `routers/logs.py::_apply_scope_filters` tenant-restricts selected configuration records using `entity_id`, then returns other records unchanged for Owner/Admin. Manager actor/target department lookup omits a tenant predicate. `models.py::AuditLog` does not provide a universal trustworthy tenant field; `entity_id` often names a task/user/resource and cannot generally be compared to tenant ID. The safer v2 `AuditEvent` records used by task activity are a different storage contract.

**Affected paths/services.** `/logs/audit` listing and `/logs/audit/export` use the shared query; `/logs/audit/{log_id}/retry` looks up the log globally and checks staff role/automation category without tenant provenance, so it needs the same ownership guard. Audit retention/configuration endpoints are global administration and must stay excluded. Do not confuse `/logs` reward logs with ordinary audit logs.

**Expected policy.** Tenant administrators see only attributable tenant audit records; Managers see only their approved tenant/department scope, ordinary users only approved own events. Legacy unattributed records must not be assigned to a tenant by guesswork. Durable MCP audit needs explicit provenance and redaction.

**Existing tests.** `test_navigation_readiness.py::test_configuration_audit_metadata_does_not_cross_tenants` and `test_navigation_policy.py::test_navigation_audit_records_never_cross_tenants` cover the already protected configuration subset. They do not establish ordinary audit isolation. New tests do not cover ordinary logs.

**Smallest proposed fix.** For safely attributable rows, use canonical resource/actor tenant provenance and same-tenant joins across list/export/retry; exclude ambiguous rows from tenant views. Actor-only filtering cannot safely attribute system events or malformed mixed-tenant relationships. Explicit audit ownership and legacy handling may require future approved schema/data work; no blanket backfill now.

**Regressions to protect.** Security/system events without actor, deleted users/resources, historical logs, configuration exceptions, department joins, export totals/columns, retry authority, retention ownership and mixed-tenant records.

## S07 — JWT scopes, audience and revocation

**Root cause/evidence.** `auth.py::create_access_token` can include `scopes`; `routers/auth.py::generate_scoped_token` accepts caller-selected labels. `dependencies.py::_decode_access_token` verifies signature/algorithm and optional token type without a required issuer/resource audience or operation-scope requirement. `get_current_user` reloads the database and checks token tenant; roles/status dependencies provide valuable live checks, but no OAuth client/grant registry is consulted. `logout` logs an event and does not invalidate tokens. `refresh_token` loads a user and issues another pair without refresh-family rotation/reuse tracking and without an explicit active-state check at issuance. Active resource dependencies still reject deactivated users on protected calls.

The decoder also does not require `exp`: independent tests sign a synthetic access token without that claim and obtain 200 from task summary on both aliases. Normal token issuance supplies expiry, but this is different from mandatory expiry validation. The deactivation regression now explicitly verifies denial while DEACTIVATED followed by acceptance of the **same** token after reactivation; persistent revocation is not implemented. Do not claim issuer/audience absence means every token with a wrong explicit `aud` is accepted: library validation may reject such a claim. The verified gap is lack of a required configured resource/issuer profile.

**Affected paths/services.** `/auth/generate-token`, `/auth/logout`, `/auth/refresh`, common REST dependencies/aliases and any future MCP adapter. `schemas.py::TokenMintRequest` permits long-lived minted credentials. `routers/oauth2_server.py` is a separate legacy password-grant route with hard-coded signing configuration, mismatched `password_hash` attribute versus `User.hashed_password`, no tenant claim or PKCE/consent/discovery flow; it is not a remote MCP authorization server. No secret value is reproduced here.

**Expected policy.** Dedicated MCP resource credentials with issuer/audience/client/consent/scope enforcement; separately issued constrained REST delegation; live role/status checks; short expiry plus durable revocation at every operation. Existing browser login remains unchanged in this phase.

**Existing tests.** `test_generate_token.py::test_generate_token_allows_access` checks minting/use of scope labels, not least privilege. `test_navigation_readiness.py::test_common_role_dependency_ignores_forged_or_stale_token_roles` covers database role authority. New regression checks pass live status denial/reactivation, Manager demotion with unchanged signed claims, tenant-claim mismatch, missing/expired bearer and alias parity. The missing-expiry diagnostics report FAIL. No grant/refresh revocation test can pass against nonexistent grant infrastructure.

**Smallest proposed fix.** Implement a separate delegated credential class and enforcement boundary as designed in [architecture sections 4–5](PHASE_1_ARCHITECTURE.md), plus a compliant AS. Share identity resolution and resource policy without treating legacy scope labels as enforcement. Never share existing JWT signing material with MCP or expose integration API keys. A generic JWT lifetime reduction alone does not solve this finding.

**Regressions to protect.** Existing login/refresh clients, presence tokens, missing legacy token-type compatibility, logout expectations, role changes mid-request, tenant movement, simultaneous refresh/reuse, key rotation, alias scope bypass and failed revocation-store access. Changes to existing login require separate authorization.

## S09 — Access-sensitive ticket cache

**Root cause/evidence.** `tickets/router.py::list_tickets_handler` authenticates/current-role-checks dependencies, then uses `cache.build_cache_key` with tenant/user/path/query. A hit is returned before `tickets/service.list_tickets::_apply_role_scope` runs. Role, department, participant/follower state and authorization revision are absent. A previously authorized list may remain available after a role/department/membership change. Current authentication alone does not reauthorize its objects. `routers/tasks.py::_task_cache_allowed` already disables task body caching for ordinary users/Managers and list keys include role/department parameters; this is a useful contrast, not proof ticket cache is fixed.

**Affected paths/services.** `GET /tickets` and `/api/tickets`, list filters/totals and later MCP ticket list tools. Mutation invalidation is best-effort Redis prefix deletion and cannot be the sole revocation boundary.

**Expected policy.** Every returned item and count reflects current access, including cache hits. Membership/role/navigation revocation cannot wait for a TTL. Scopes/client/grant would add more context to future MCP caches.

**Existing tests.** `test_task_tabs_review.py::test_permission_sensitive_task_caches_do_not_survive_demotion` covers task cache, not tickets. No ticket-list cache-hit membership/demotion negative test was found in the inspected sources. The Phase 1 ticket tests use no Redis and do not exercise this gap.

**Smallest proposed fix.** Disable ticket business-result caching until safe reauthorization exists, or cache non-sensitive IDs then rerun authoritative access queries on every hit. Versioned keys plus invalidation help performance but cannot alone guarantee immediate revocation after missed events. Test all roles, not only ordinary users.

**Regressions to protect.** List performance, filter/count parity, participant/follower removal, Manager department changes, admin demotion, stale missing-invalidation events, Redis outages and alias-specific keys. Future MCP starts with no business-data cache.

## S10 — Task observer and write permissions

**Root cause/evidence.** `routers/tasks.py::_ensure_task_update_access` narrows ticket tasks to creator/assignee; for ordinary tasks it reuses `_ensure_task_access`, including followers and department Managers. `delete_task` uses read access. General parent PATCH has field/workflow checks but not one consistent observer-write rule. `services/audit_logger.py::_activity_context(write=True)` explicitly rejects an ordinary observer, and subtask/activity services reuse it. `routers/comments.py::_ensure_comment_access` allows all same-tenant Managers regardless of task department while ordinary followers are excluded. Staff may set another same-tenant `CommentCreate.user_id` as author.

**Affected paths/services.** General task PATCH/delete/complete, activity/work intervals/subtasks, comment list/create/delete and aliases. A read scope must never be interpreted as permission for these writes.

**Expected policy/decision.** The explicit observer activity-write denial is authoritative and tested. General task field edit/delete policy, department Manager powers, comment read membership and staff delegated authorship need approval before behavior changes. The follower schema comment describes observers as read-only, but current parent routes contradict that intent; documentation alone is not a deployed fix.

**Existing tests.** `test_task_activity.py::test_tenant_rbac_observer_and_manager_visibility`, `test_subtask_workflow.py::test_permissions_follower_tenant_and_stale_bulk_edits`, and `test_task_tabs_review.py::test_foreign_task_comments_and_author_spoofing_are_rejected` cover selected service/ordinary author rules. New observer activity guard and unrelated parent PATCH denial tests pass. They do not certify observer parent PATCH/delete or staff comment authorship.

**Smallest proposed fix after approval.** Introduce explicit operation/field write guards shared across parent paths, with activity policy as a known baseline; authorize comments through the approved task/comment policy and derive authorship from the actor unless an explicit on-behalf capability is approved. Preserve field schemas and workflows; do not broadly remove Manager rights by assumption.

**Regressions to protect.** Ticket creator/assignee restrictions (even Owner/Admin do not automatically override them), completion/approval gates, history-protected delete, follower notifications, staff support workflows, comment authorship/audit and partial field updates.

## S11 — Notification visibility

**Root cause/evidence.** `services/workload_notifications.py::visible_query` requires own inbox, non-dismissed rows, tenant-or-null legacy ownership and current access for `related_task_id`, with additional workload-subject rules. It has no equivalent ticket membership predicate for `entity_type=TICKET` rows lacking a task link. Legacy null-tenant bodies can therefore survive changed ticket membership. This is not a claim that all task alerts are unsafe: `recipients`, `can_view`, delivery rechecks and `notification_schema.py` ownership guards protect newer deduplicated task alerts. The schema guard's strict ownership condition applies to deduplicated rows, not every legacy notice.

**Affected paths/services.** `/notifications`, `/notifications/inbox`, read-all/read/dismiss actions that share `visible_query`, and notification/email/push/realtime/export consumers. A protected read cannot retract a body already sent externally; delivery-time authorization matters too. Transfer approval notice creation uses the legacy notification path and needs S01 recipient repair.

**Expected policy.** User owns the notice **and** retains access to referenced content before AI export or delivery. Account-only balance notifications may remain visible without task data under their existing explicit policy. Legacy attribution must be decided rather than guessed.

**Existing tests.** `test_workload_notifications.py::test_unread_count_scopes_all_pages_and_actions`, `test_delivery_retries_quiet_preferences_and_revoked_access`, `test_db_rejects_cross_tenant_alert`, and `test_workload_notification_review.py::test_live_badge_count_handles_unread_state_and_removed_watcher` cover task alerts/ownership. They do not establish current ticket-body authorization. No new Phase 1 notification regression was executed.

**Smallest proposed fix.** Extend the shared visibility/delivery policy to ticket-linked notices using current tenant and `get_ticket_for_user`-equivalent predicates, including entity links without `related_task_id`. Apply the same authorized set to list/count/actions/exports; redact or withhold unattributable legacy bodies pending approved legacy policy. Preserve task/account-only alert semantics and deduplication receipts.

**Regressions to protect.** Unread counts/pagination, deleted resources, historical null-tenant notices, pending ticket approvers, removed participants, retry queues/quiet hours, safe account adjustments, dismissed tombstones and notification IDs. No cleanup or production data edit was performed.

## Additional boundary: S08 read side effects

Although not among the ten requested primary findings, S08 affects read-only MCP safety. `GET /tasks` can trigger overdue notifications when its flag is disabled; prefer `/tasks/page`. `tickets/router.py::get_ticket_handler` marks notices read, emits SLA notices/Webex and commits; it is not a pure read. The new top-level ticket authorization tests use inert synthetic tickets without pending notices/SLA deadlines; they do not prove read purity. A future read-only ticket tool needs an approved side-effect-free REST contract before exposure. No endpoint was added now.

## Outstanding decisions and release gates

1. Approve the exact group sibling/shared-field policy and ordinary observer/Manager/comment operation matrix before S05/S10 changes.
2. Approve transfer approval/auto-approval authority, Manager-without-department behavior and active-target eligibility for task/ticket relationships.
3. Establish Department/Kanban ownership and treatment of unattributed audit/legacy notification records; no inferred company/agency relationships or silent backfills.
4. Select OAuth issuer/identity-linking ownership, per-client consent, grant storage/revocation, credential keys and backend delegated-scope enforcement. Existing JWT scope labels cannot satisfy this gate.
5. Fix and negatively test S01–S07/S09–S11 for each enabled surface. A narrow read pilot may leave unrelated tools excluded, but every exposed path must be demonstrably safe; sensitive expansions cannot bypass blockers.
6. Validate PostgreSQL, cache revocation, actual proxy paths, approved clients/protocol versions, quotas, audit failure behavior and concurrency in a verified disposable environment. This turn proves none of those runtime environments.

## Independent acceptance review

The following verdicts use the twelve criteria in the independent-review request. A design PASS means a coherent documented contract after corrections; it never means that an unimplemented OAuth server, MCP container or Settings endpoint works. Existing application security is assessed separately.

| # | Acceptance criterion | Verdict | Evidence / limitation |
|---|---|---|---|
| 1 | Architecture matches actual repository | PASS | React/Vite hash SPA, FastAPI/SQLAlchemy, real Settings registry/client, router order, Docker variants/proxy rewrite and import-time DB helpers rechecked in source. |
| 2 | MCP isolated from backend runtime | PASS (design/scope) | Separate package/container/REST-only boundary specified; no MCP runtime, backend import or service added. Actual MCP image/startup isolation tests NOT RUN because no service exists. |
| 3 | OAuth/delegated credential design secure | PASS (design) | Required token profiles, trusted exchange versus token passthrough, separate credentials, client/grant binding, fail-closed route restrictions and revocation contract clarified. Provider/profile/implementation and interoperability NOT RUN. |
| 4 | Tenant/user permissions cannot be bypassed | **FAIL** | Existing S01–S07/S09–S11 remain; S03 logs return private same-tenant data to a non-member. Passing narrow tests cannot establish comprehensive authorization. |
| 5 | Grouped-assignment visibility protected | **FAIL** | Isolated S05 diagnostics return a sibling whose direct read is denied, on canonical and API group routes. Group writes remain source-confirmed/policy-blocked, not runtime-tested. |
| 6 | REST authorization issues accurately represented | PASS | All requested findings source-rechecked; S01 pre-mutation tenant lock retained; S03 serialization failure distinguished from confirmed log disclosure; S07 live status versus revocation clarified. |
| 7 | Proposed scopes not mistaken for implemented scopes | PASS | Eight scope names explicitly future-only; legacy scope labels do not enforce REST operations. |
| 8 | Settings controls have backend enforcement contracts | PASS (design) | Tenant/own-grant capability checks, before/after write-authority comparison, Owner step-up proof, revision/idempotency, independent revocation/emergency controls documented. No endpoints/UI implemented/tested. |
| 9 | Tests use safe isolated fixtures | PASS | Fresh child/empty scratch, sanitized env, SQLAlchemy and direct SQLite memory-only guards, blocked outbound TCP/UDP/DNS/listeners, no main/legacy collection/startup/migrations. Four isolation methods pass. |
| 10 | Production data/schema/login/functionality unchanged | PASS (review scope) | Changes limited to the seven Phase 1 files. Before/after content check of 1,982 tracked/existing-local-DB files and empty tracked diffs verifies no such local edits; no production connection/action occurred. Remote production state was not inspected. |
| 11 | No claims of working unimplemented features | PASS after correction | Scoped package completion separated from broader feasibility Phase 1 exit; design assertions and current/future token behavior labeled; security diagnostic FAILs surfaced by nonzero exit. |
| 12 | Phase 2 dependencies/blockers explicit | PASS | Feasibility roadmap's auth bridge, launch-surface repairs, policy approvals, credential/storage/step-up implementation and isolated OAuth/PostgreSQL/proxy/client tests remain gates. |

Corrections in this review are limited to the five Phase 1 documents and two standalone test files: stricter fixture guards, valid synthetic emails for full TaskRead validation, actual read-candidate/workload checks, explicit open-finding diagnostics, OAuth exchange/token-profile precision, Owner escalation/step-up contracts and honest completion/acceptance language. The feasibility report and all existing application code are unchanged.

**Recommendation: NO-GO for beginning the Phase 2 MCP service under the feasibility roadmap.** Complete separately authorized prerequisite authentication/delegation and launch-surface authorization work, resolve applicable policy decisions, then rerun the security gates. This does not prohibit review/planning of that prerequisite work, and does not authorize implementing it now. The documentation/test package is delivered; Phase 1 is **not production-ready** and the broader security-preparation exit is unsatisfied.
