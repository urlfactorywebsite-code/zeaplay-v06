# Future Settings → MCP Management design

Date: **11 November 2026, Asia/Calcutta**. **Design only:** no UI, navigation registry, endpoint or schema is implemented. The existing Settings experience, login and API configuration remain unchanged. See [architecture/authentication](PHASE_1_ARCHITECTURE.md), [permissions](MCP_PERMISSION_MODEL.md) and [open security findings](PHASE_1_SECURITY_REVIEW.md).

## 1. Existing Settings architecture

| Source | Current integration point |
|---|---|
| `frontend/App.tsx` | React Router hash SPA; nested `/settings` routes; index redirects to `/settings/profile`; lazy existing page components and `ProtectedRoute`. Legacy redirects preserve query/hash/state. |
| `frontend/utils/settingsNavigation.ts` | Route identities/typed `SettingsTabKey` for profile, support, master-control, api, logs, media-library and sidebar-management; legacy URL map. |
| `frontend/pages/Settings.tsx` | Tabs come from server navigation via `useNavigation`; responsive overflow, keyboard/manual activation, icons, Outlet and shared `UnsavedChangesProvider`. |
| `frontend/hooks/useNavigation.tsx`, `components/ProtectedRoute.tsx` | Server registry drives visible/available pages, role ceilings and client route access. UI hiding supplements server checks. |
| `backend/app/navigation_registry.py::PAGES`, `api_pages` | Server page identities/roles and mapped endpoint policy. API administration Owner/Admin; Sidebar Management Owner/Admin; Master Control Owner-only; Logs staff. |
| `backend/app/navigation_guard.py::enforce_navigation_policy`, `services/navigation.py` | Application-wide active bearer authentication and server page policy on mapped REST operations/aliases. |
| `frontend/services/mockApi.ts`, `frontend/App.tsx::AppProviders` | Existing Axios bearer/refresh client and TanStack Query infrastructure. Reuse patterns and cache invalidation; do not create a second client/login stack. |
| `backend/app/routers/config.py`, `dependencies.py`, `permissions.py` | Configuration access uses `get_current_api_admin` and tenant filters. This is a reusable capability pattern, but existing secret-returning configuration responses are not a suitable MCP management DTO. |

Future route: `/settings/mcp-management`, server page ID `settings.mcp-management`, parent `settings`, location `settings-tab`. Add route identity, icon, lazy component and server registration together in a later implementation. Preserve existing tabs/deep links/legacy redirects and mobile/collapsed navigation. Do not route MCP protocol traffic through React's hash router or SPA fallback.

The proposed tab may be available to all current roles for **personal** consent/connections. Administrative sections require narrower server capabilities. Extend `api_pages` for management routes/aliases so navigation denial is consistent, but retain explicit operation dependencies. Hiding a tab/section never authorizes an HTTP request.

## 2. Six sections and role controls

These are proposed MCP role defaults, pending approval. Tenant role is read from the current database; a token/UI-supplied role cannot grant access.

| Section | User / Manager | Admin | Owner |
|---|---|---|---|
| Overview | Own connection state, available tools/scopes, tenant enabled/read-only state, safe service status | Tenant counts, readiness/blocker summary, policy revision and tenant health | Same; approve/recover emergency lock |
| MCP Tools | Read currently effective tools/descriptions for self | Edit tenant subset of released server catalog, within tenant scope ceiling | Same; approve enabling write capabilities |
| AI Connections | Own consent/grants, scope reduction/withdrawal and own connection revocation | Tenant client approvals, connection inventory, revoke tenant connections with reason | Same; approve confidential client credential rotation |
| Permissions | Own effective scopes and consent history | Edit allowed read scopes/tool policy; cannot grant another user's consent | Same; approve read-only removal/write-scope ceiling |
| Security | Personal sessions/connections; revoke own connection | Tenant emergency disable, reviewed security settings within ceilings | Same plus explicit unlock/re-enable after emergency |
| Activity Logs | Own connection/tool metadata only | Attributable tenant MCP activity, subject to field redaction | Same; retention/export policy if separately approved |

Manager's department/direct-report resource powers do not imply MCP administration. Tenant Owner is not platform/Super Agency administrator. No Agency/Company selector or hierarchy editor is shown because those ownership relationships do not exist. A future platform-wide emergency switch belongs to authenticated deployment operations, with no automatic tenant data read privilege.

Recommended defaults: tenant disabled, read-only true, no tools/scopes allowed, no automatically consented clients. A later approved pilot may allow only the five task/workload read tools. Admins can remove authority immediately. Write enablement/read-only removal needs Owner approval plus separately satisfied security gates; it is not available while writes are unreleased. User consent may always choose less. Changes take effect across MCP replicas and backend delegated checks, not merely in the browser.

Backend enforcement must compare the persisted before/after authority for **every** mutation. Adding any write tool, mutation scope, client write-scope ceiling, or changing read-only from true to false requires current Owner role and a verified step-up receipt, even if the tenant/client is presently disabled. Apply this to policy PATCH, client POST/PATCH and any later bulk/alias route; do not rely on a special UI button. Admin cannot stage a dormant write allowance and let a separate enable action activate it. Reject the whole unauthorized patch atomically; do not partially save allowed fields. Reduction/revocation stays available to Admin/Owner within tenant scope.

## 3. Section behavior

### Overview

Show configured MCP resource URL (read-only, server controlled), tenant enabled/read-only state, user capability summary, effective tool count, active connections, service health and last observation time. Distinguish `healthy`, `degraded`, `unavailable`, `unknown` and `not_configured`. Never display green based solely on an old successful ping. A service liveness response does not establish OAuth, policy, revocation, backend or audit readiness.

Health is derived from operator-configured probes and redacted observations, not a browser-entered URL. Public detail includes status/time; admin detail may include safe reason codes such as `POLICY_UNAVAILABLE`, not internal hosts, stack traces or credentials. Disabling a tenant does not imply stopping the shared MCP process.

### MCP Tools

List static catalog tool ID, description, read/write side-effect class, required scopes, release status, tenant allowlist state, effective availability and blocking reason. Only released catalog IDs can be selected. No arbitrary tool names/endpoints/schema editor. Locked entries explain why unavailable (`SECURITY_GATE`, `SCOPE_DENIED`, `READ_ONLY`, `NOT_RELEASED`). Show estimated data categories/limits and source coverage where relevant; avoid exposing implementation-only source paths in the product UI.

Save the whole reviewed allowlist with a revision token and audit reason. Show effective changes before save, including affected existing grants. Adding a tool does not expand old consent. Disabling a tool immediately prevents subsequent calls and buffered result emission; already committed writes are recorded, not undone.

### AI Connections

Distinguish a registered OAuth **client** from a user's tenant-bound **connection/grant**. Inventory shows safe client identity, verified registration status, user, tenant, scopes/tools, connected/last-used/expires times and revoked state. A label or logo is not client trust. Display own versus tenant views by capability; never let Admin impersonate/consent for a user.

Also distinguish an AS client registration from a **tenant's approval of that client**. Management `{client_id}` identifies a tenant-scoped management/approval record, mapped server-side to the verified AS client ID. A shared/operator-managed client may serve multiple tenants: a tenant Admin/Owner may revoke its own approval and tenant grants, but may not delete the shared AS registration, alter its redirects/credentials or revoke other tenants. AS registration mutation is allowed only for a registration explicitly owned by the current tenant; shared registration changes belong to the operator. Client type/name alone never establish ownership. Responses declare registration ownership and permitted mutation fields; the backend enforces both independently of UI state.

Connect starts a trusted AS authorization/consent flow with PKCE S256 and exact registered redirect URI. Consent identifies the client, tenant, requested tools/data/actions, redirect destination and duration. There is no copy-paste REST JWT/API key workflow. Browser session tokens never appear in a connection response or redirect. Standard OAuth redirects/codes are handled by the AS/client; management endpoints return metadata only.

Default registration is admin-controlled and allowlisted. Registration records include public/confidential client type, exact approved redirect URIs, scope ceiling and tenant approval; dynamic registration and arbitrary metadata URL fetching are disabled initially. Public native clients use PKCE without a fabricated client secret. Confidential credentials, when needed, are delivered through the chosen AS/vault secure mechanism, never through ordinary list responses or application logs.

Revocation requires a concrete connection/client target and reason; withdrawing one's own consent is always possible while personal management is available. Revoke stops refresh/delegation, invalidates current access at shared authorization gates and closes sessions/resumption. Re-enabling a tenant/client never revives a revoked grant. Confirmed completed writes remain visible with outcome metadata.

### Permissions

Show permission intersection clearly: tenant ceiling → user consent → client/grant → tool → current resource access. Display the eight proposed scopes from [permission model](MCP_PERMISSION_MODEL.md), with warnings that no scope bypasses task/ticket membership. No free-text scope editor, wildcard or direct role reassignment in this UI.

Read-only mode withholds all mutation/side-effect tools regardless of their HTTP method. `GET /tickets/{id}` currently has side effects and cannot be approved as a pure read tool. Adding/removing role or department rights happens through existing user management; MCP refreshes live state. Scope additions require new user consent. A reduced scope set is not treated as a new broader grant.

### Security

Expose approved policy values and ceilings for token lifetime, idle/absolute consent expiration, client approval, quotas and audit retention; initially read-only until provider/policy decisions are approved. Never provide existing signing secrets or provider keys. Separate ordinary `enabled=false` from `emergency_disabled=true` so a routine policy save cannot unlock an emergency stop.

Emergency disable is a short flow: show affected tenant/connections, accept required reason, submit one atomic server action, display durable disabled state/revision. Admin/Owner may invoke it. Only Owner with fresh authentication and explicit recovery action may unlock under the proposed policy. Deployment operator global disable overrides tenant unlock. Confirmations in this design describe future product interactions; Phase 1 does not perform these actions.

Fresh authentication has no verified implementation in the existing web JWT contract. Sensitive future actions require `X-MCP-Step-Up: <opaque-receipt>` from the future trusted reauthentication bridge. A receipt expires within a proposed 120 seconds, is single-use, and binds authenticated user, current tenant, action, target, canonical payload digest and expected policy/client revision. Backend validates/consumes it in the action transaction and stores only a protected reference/hash. Existing bearer `iat`, a refreshed access token, `approved:true` or a caller-supplied authentication timestamp cannot substitute. Missing proof returns 403 `STEP_UP_REQUIRED`; invalid/replayed/mismatched proof returns 403 with a safe reason. Provider challenge/receipt issuance and callback validation require approval and implementation; until available, these sensitive actions must remain denied, not silently downgrade to ordinary Owner authentication.

Audit every policy, client, consent and revocation change. If the durable authorization store is unavailable, actions fail closed and the UI shows unavailable state rather than claiming success. If backend commit succeeds but response is lost, fetch canonical status by request ID/revision before retrying.

### Activity Logs

Separate MCP access records from existing broad `/logs/audit`. Show time, actor/client/tool, outcome/reason, duration, correlation ID, result count/truncation and authorized resource references. Users see own grant activity; Admin/Owner see only attributable same-tenant events. Never include raw prompt/task/ticket body, token, password, provider secret or unrestricted request headers.

Bound and paginate reads/filter ranges. Escape rendered untrusted text and protect any future CSV export from formula injection. Export is excluded initially; retention changes and detailed IP/user-agent collection need approved privacy policy. Preserve security tombstones after revocation so records cannot imply a connection is active again. See S06 for why existing audit queries cannot be reused unchanged.

## 4. Proposed backend REST contracts

**None of these endpoints exist yet.** Proposed canonical base: `/mcp-management`, with matching `/api/mcp-management` aliases only if later implemented consistently with existing patterns. This namespace is separate from protocol `/mcp` and internal delegation `/internal/mcp/delegations`. Tenant identity is always resolved from the existing authenticated user. Reject `tenant_id`, `actor_id`, `role` and credentials in user-controlled management request bodies.

Common behavior:

- Existing web bearer authentication + ACTIVE database user + section capability + server navigation policy. Mutation role checks run on backend regardless of page visibility. No acceptance of MCP/delegated business tokens as management credentials by default.
- Strict request schemas, bounded strings/arrays and unknown-field rejection. Stable UUIDs for new client/grant IDs; catalog tool IDs are enumerated. IDs in paths are tenant/owner scoped before disclosure.
- `ETag`/`If-Match` revision for policy/client mutation; missing revision `428`, stale `412`. `request_id:UUID` for idempotent revocation/emergency actions. Idempotency binds actor, tenant, action, target and payload; conflicting reuse returns `409`.
- Success carries `request_id`, safe DTO and revision where applicable; errors carry `{error:{code,message,request_id}}`. No raw upstream payload. `401` authentication; `403` capability; `404` foreign/unknown object; `422` invalid shape/value; `409` release/consent/state conflict; `429` quota; `503` unavailable authority. Browser error normalization belongs in the existing client.
- Management responses are `Cache-Control:no-store`; TanStack keys include current user/tenant and are cleared on account changes/revocation. UI optimistic updates must not claim security action completed before server confirmation.
- Personal consent withdrawal/revocation and tenant emergency disable must work when tenant MCP is disabled/read-only, without an MCP protocol token or healthy MCP process. Do not condition these management actions on the business-tool `enabled` gate. Existing user/navigation/capability checks still apply; provide the AS's standard own-grant revocation path if personal navigation is disabled. An authority-store outage must visibly fail the operation while the execution gate remains denied.

| Method / path | Authority | Request → response |
|---|---|---|
| `GET /mcp-management/overview` | All roles, current user | No body → `Overview{capabilities,enabled,read_only,emergency_disabled,effective_tool_count,own_connections,health,policy_revision}`; tenant totals only for administrators |
| `GET /mcp-management/tools` | All roles | No body → `{items:ToolDescriptor[],policy_revision}` filtered to user-visible catalog metadata |
| `GET /mcp-management/policy` | Admin/Owner | No body → `TenantPolicy` and `ETag` |
| `PATCH /mcp-management/policy` | Admin/Owner; any mutation-authority expansion Owner-only + step-up | `PolicyPatch{enabled?,read_only?,allowed_tool_ids?,allowed_scopes?,reason}` + If-Match → canonical policy/revision; compare before/after effective authority; cannot override emergency state or unreleased tools |
| `GET /mcp-management/clients` | Admin/Owner | `page>=1,page_size<=100` → `Page<ClientSummary>`; tenant-approved clients only |
| `POST /mcp-management/clients` | Admin/Owner for read-only public client; confidential provisioning or any write ceiling Owner + step-up | `{name,type,redirect_uris,scope_ceiling,reason}` → `201 ClientSummary`; backend validates AS registration and tenant approval before enabling; no returned secret in normal DTO |
| `PATCH /mcp-management/clients/{client_id}` | Admin/Owner within ceiling; any added write authority or confidential credential/redirect change Owner + step-up | Strict allowlisted changes + reason + If-Match → updated metadata/revision; redirect/scope changes trigger appropriate re-registration/consent |
| `POST /mcp-management/clients/{client_id}/revoke` | Admin/Owner, current tenant approval only | `{request_id,reason}` → `{revoked_at,affected_connections,state}` after durable tenant approval/grant revocation; never disables a shared AS registration or other tenants; retry returns same state |
| `GET /mcp-management/me/connections` | All roles, own only | Bounded pagination → `Page<ConnectionSummary>` |
| `GET /mcp-management/connections` | Admin/Owner | Bounded pagination/status/client filters → tenant `Page<ConnectionSummary>` |
| `POST /mcp-management/connections/{connection_id}/revoke` | Own user or tenant Admin/Owner | `{request_id,reason}` → `{connection_id,revoked_at,state}`; ownership/tenant checked first |
| `GET /mcp-management/me/consents` | All roles, own only | Bounded pagination → metadata/history of own tenant/client scope decisions |
| `POST /mcp-management/me/consents/{consent_id}/withdraw` | Own user only | `{request_id,reason}` → withdrawal/revocation state; Admin revocation uses connection/client authority, never fabricates user consent |
| `GET /mcp-management/security` | Admin/Owner | No body → safe approved ceilings/current values/key-version identifiers only; no secret material |
| `POST /mcp-management/emergency-disable` | Admin/Owner | `{request_id,reason}` → `{emergency_disabled:true,revision,disabled_at}`; atomic shared deny gate plus grant/session invalidation |
| `POST /mcp-management/emergency-recovery` | Owner + step-up receipt bound to recovery and revision | `{request_id,reason,expected_revision}` → recovered state; default tenant remains disabled until explicit approved enablement |
| `POST /mcp-management/step-up-challenges` | Owner, existing authenticated web identity | `{action,target_id,expected_revision,proposed_change}` validated against the sensitive-action schema → `{challenge_id,verification_url,expires_at}`; backend computes payload digest; fixed trusted provider, no arbitrary callback/verification URL input |
| `GET /mcp-management/step-up-challenges/{challenge_id}` | Same user/tenant who created it, current Owner | No body → `{status,expires_at,receipt?}`; receipt delivered only after authenticated provider completion, never from a caller's success assertion; one authorized retrieval, no-store and redacted |
| `GET /mcp-management/health` | All roles, redacted by capability | No arbitrary target URL → `HealthSnapshot{status,observed_at,stale,checks}`; safe check codes only |
| `GET /mcp-management/activity` | Own scope for User/Manager, tenant for Admin/Owner | Bounded page/filter/time range → `Page<ActivitySummary>`; server prohibits a wider scope than caller capability |

Standards-based authorize/token/discovery/revocation endpoints belong to the selected AS/MCP resource metadata, not these admin CRUD routes. Consent creation occurs only through the authenticated AS flow; there is no general `POST consent=approved` API accepting an LLM/browser assertion. A future client credential rotation requires an AS-supported secure delivery flow, explicit capability and fresh authentication; no reusable secret-read endpoint is proposed.

The proposed step-up bridge is also unimplemented. Its private provider completion validates issuer, audience, subject binding, nonce/state, challenge lifetime and the approved authentication assurance before marking a challenge verified; an ordinary web bearer cannot mark it verified. The one-action receipt is authorization proof, not a reusable access/refresh token, and is excluded from normal DTOs/logs. Identity provider/proof issuance must be selected and negatively tested before these contracts can be enabled. No existing login flow is changed or activated in Phase 1.

### DTOs and invariants

```text
TenantPolicy = {enabled:boolean, read_only:boolean, emergency_disabled:boolean,
  allowed_tool_ids:CatalogToolId[], allowed_scopes:ProposedScope[], revision:int,
  updated_at:RFC3339, updated_by:UserId}
ToolDescriptor = {id, name, description, required_scopes[], side_effect:"read"|"write",
  release_status:"blocked"|"pilot"|"released", tenant_allowed:boolean,
  effective_available:boolean, blocked_reason?:SafeCode}
ClientSummary = {id, name, type:"public"|"confidential", redirect_uris:string[],
  registration_ownership:"tenant"|"operator_shared", modifiable_fields:string[],
  scope_ceiling:ProposedScope[], status, created_at, updated_at, revision}
ConnectionSummary = {id, client_id, client_name, user_id, scopes[], tool_ids[],
  status, created_at, last_used_at?:RFC3339, expires_at, revoked_at?:RFC3339}
ActivitySummary = {id, occurred_at, user_id, client_id, grant_id, tool_id,
  outcome, reason_code?, duration_ms, request_id, result_count?, truncated?}
Page<T> = {items:T[], page:int, page_size:int, total:int, has_more:boolean}
```

Unknown/never-used timestamps are null, not invented. Client redirect URIs may be shown only to authorized client administrators/consenting user. DTOs never return signing keys, API keys, passwords, client secret, raw access/refresh tokens, encrypted credential blobs or database connection information. Tenant identity may be displayed from trusted response context; it cannot be chosen to widen a request.

## 5. Frontend state and accessibility

Reuse current Settings shell and existing theme tokens/components. Add internal section links with stable query/deep-link state; use accessible tab/heading relationships, keyboard navigation, mobile overflow, focus/error summaries, loading/empty/unavailable states and unsaved-change protection. Ordinary users should see personal controls without blank administrative tables. Do not fetch admin endpoints and then hide their responses in React.

Revalidate overview/policy/tools/connections after a successful change; clear sensitive caches when logging out/switching users. Disable stale forms on revision conflict and require reload/review; do not overwrite other administrators' policy. Display server-computed effective state/reasons and last-updated information. Confirm revoke/emergency actions with a named client/connection/tenant and expected impact; no accidental bulk-revoke default.

## 6. Deferred decisions and acceptance

Approve role ceilings, Owner write enable/recovery and step-up provider/receipt flow, AS provider/client registration/identity linking, consent duration/retention, privacy/redaction, emergency fail-closed behavior and durable audit storage before implementation. Missing agency hierarchy is explicitly unsupported. No UI/backend DTO should suggest otherwise. These contracts are a design-level PASS after review, not proof that any backend control exists. Phase 2 service start remains NO-GO until prerequisite security work and its tests are complete.

Later acceptance must cover all six sections for all roles, direct deep links, signed-out/inactive/demoted requests, foreign IDs, navigation-policy denial, optimistic concurrency/idempotency, stale health, no secret rendering, consent denial/revocation, dropped invalidation, keyboard/mobile behavior, unchanged legacy Settings paths and real API proxy aliases. These future UI tests are **NOT RUN**; this phase builds no UI.
