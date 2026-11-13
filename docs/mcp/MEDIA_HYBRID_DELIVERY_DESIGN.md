# Hybrid private media delivery design

Date: **12 November 2026, Asia/Calcutta**. **DESIGN ONLY — no routes, authentication mechanisms, storage policies or TTL changes implemented.** [Ownership](MEDIA_OWNERSHIP_ARCHITECTURE.md), [API compatibility](MEDIA_API_COMPATIBILITY.md), [test plan](MEDIA_STORAGE_TEST_PLAN.md).

## Existing versus proposed behavior

Current [media router/service](../../backend/app/routers/media.py) / [MinIO signer](../../backend/app/services/minio_media_service.py) authorizes list/upload operations and returns300-second GET/PUT URLs. Legacy `/uploads` bytes are public despite authenticated metadata. [Avatars](../../backend/app/routers/avatars.py) fetch bounded image bytes after current-user/tenant checks; they are not a general range-streaming endpoint. [media_http.py](../../backend/app/media_http.py) sandbox/nosniff protects local uploaded documents but does not add confidentiality. Actual object policies/signature rejection/CDN behavior remain unverified.

Proposed mode selection is server policy derived from asset/version/classification and an approved category/binding policy. A client may express a preference but cannot upgrade visibility, select arbitrary provider/key/host or obtain signed delivery for a ModeA-only asset.

| Class / requirement | Proposed delivery | Authorization and limitations |
|---|---|---|
| Approved public artwork/rendition | Public isolated origin | Explicit publication, no confidential original or application credentials; revoking public status requires replica/cache closure |
| Confidential document/task/ticket/chat file; strict current revocation | **A** authenticated content stream | Current active session/membership, tenant and canonical selected-resource permission on every new request |
| Tenant portraits requiring current access | **A** bounded image fetch or authenticated content path | Preserve current same-tenant portrait audience and narrower edit/selection rights |
| Private large media where transferable access is explicitly acceptable | **B** signed GET, TTL300 | Fresh issuance admission; verified private provider policy; bearer URL reusable/transferable until expiry; no immediate app-permission revocation guarantee |
| UNKNOWN or unresolved owner | No new public publication or privileged delivery grant | Review state; current legacy exposure handled by separately approved compatibility/closure workflow |

## Mode A — authenticated download/streaming

Proposed external route: `GET/HEAD /api/v2/media/assets/{asset_id}/versions/{version_id}/content?binding_id={opaque_id}`; backend path `/v2/media/...`, registered once behind Nginx prefix stripping. It is not currently implemented. Existing routes/aliases remain untouched.

```mermaid
sequenceDiagram
  participant C as Authenticated client
  participant API as Content endpoint
  participant P as Current policy / session authority
  participant R as Asset + binding registry
  participant S as Private storage
  C->>API: GET/HEAD opaque asset/version + optional Range
  API->>P: Validate live session, membership, tenant
  API->>R: Load tenant-scoped asset and requested binding/version
  API->>P: Canonical resource + asset policy; deny stale/deleted/unresolved
  API->>S: Open allowlisted server-resolved object/range
  API-->>C: Safe headers; bounded streamed bytes
  loop Until complete or cancelled
    API->>P: Revocation/epoch revalidation for long stream
    S-->>API: Bounded chunks with backpressure
    API-->>C: Authorized bytes
  end
```

Requirements for a future implementation:

1. Authenticate before revealing size, MIME, existence, ETag or issuing provider calls. Use the existing durable session authority; no model/client-controlled tenant, role or user ID. Check live tenant ownership, current membership incarnation, resource binding, canonical domain read permission and asset policy. Unknown/foreign/missing resources have nondisclosing error shapes; current same-tenant forbidden distinctions can remain only where existing contract intentionally exposes them.
2. Resolve provider configuration, bucket/key/version or local path **only** from trusted registry state. No path, URL, host, redirect target or Range-generated key supplied by a caller. Local resolution must prevent traversal/symlink races: contained non-symlink/open-by-handle strategy with least filesystem permissions, not only lexical prefix checking. Provider adapters never follow unexpected redirects or forward application Authorization/cookies to storage. External links are not fetched by this endpoint.
3. Open upstream streams lazily after admission, bind to an immutable sealed version, close storage bodies on normal/error/client-disconnect paths, and propagate backpressure. Avoid reading whole large objects into Python/JS memory. Bound connection pool, per-tenant/user concurrency, stream duration, bytes in flight, range request count/rate and aggregate throughput. Proposed limits require D08/load-test approval; no untested number is called production-ready. Slow/disconnected clients must not leave storage sockets or worker slots occupied indefinitely.
4. Support HEAD without bytes and a documented single byte range where media playback/resume requires it; successful range206 has correct Content-Range/Length and immutable version identity. Unsatisfiable range416 reports size only after authorization. Malformed range is a safe client error; valid unsupported multi-range can be ignored with200 full response, subject to the same byte quotas. Cap pathological headers/range count. If-Range/ETag behavior must not combine bytes from different versions. Never let range/error/conditional paths skip admission or safety headers. [HTTP semantics](https://www.rfc-editor.org/rfc/rfc9110.html#name-range-requests).
5. Set `Cache-Control: private, no-store, max-age=0`, `X-Content-Type-Options:nosniff`, safe content type and explicit `Content-Disposition`. Normalize display filename, remove controls/separators, use safe fallback plus correctly encoded filename*, and never interpolate object keys into headers. Private responses bypass shared CDN/proxy caching; `Vary` alone is not sufficient. Public caching is a separate approved policy. [Caching semantics](https://www.rfc-editor.org/rfc/rfc9111.html#name-no-store).
6. Default untrusted active SVG/HTML/XML and unsupported formats to attachment or approved sanitized/raster derivative on an isolated media origin. Preserve the existing document sandbox; do not add allow-scripts/allow-same-origin. Do not trust filename, declared Content-Type or extension as a content validator. PDFs/native viewer/plugins and audio/video paths need explicit browser tests; download success does not prove universal preview compatibility. [CSP sandbox](https://www.w3.org/TR/CSP3/#directive-sandbox).
7. Write bounded audit events: request correlation, actor/session reference (not bearer), tenant, asset/version/binding IDs, allow/deny reason, mode, policy epoch, range/byte count, duration and completion/cancellation/storage error. No raw keys, signed URLs, cookies, file content or credentials in routine request logs. Limit/dedupe abusive denied events without losing security counts.

### Revocation semantics — precise boundary

Every **new** ModeA GET/HEAD/range/conditional request rechecks committed current authority and denies after revocation/role/tenant/binding/deletion changes. Do not use long permission TTL caches or a long-lived database snapshot that hides those changes. A response already delivered to a recipient cannot be recalled.

For long in-flight streams, recommend authority-change invalidation plus periodic independent revalidation and cancellation, with a separately approved measurable maximum stop latency and buffer budget (D08). No “immediate byte revocation” or numerical SLO is approved/implemented here. Even cancellation cannot retract already sent or client-buffered bytes. If strict consumers cannot tolerate this boundary, product must define a different workflow; do not silently substitute a transferable signed URL.

### Native browser authentication gap

Current [mockApi.ts](../../frontend/services/mockApi.ts) attaches bearer credentials through Axios; native `<img>`, `<video>`, `<a>` navigation/download and browser Range requests do not inherit that header. Current [Avatar.tsx](../../frontend/components/Avatar.tsx) uses authenticated fetch+Blob for small portraits. Current MediaLibrary uses raw signed readUrl directly. A new protected URL alone would break those native consumers.

| Future option | Use / tradeoff | Approval gate |
|---|---|---|
| Authenticated fetch+bounded Blob | Suitable for existing bounded portraits/small files; clear object URLs and pending responses on identity change | No claim it scales to multi-gigabyte media or supports native arbitrary Range; strict memory cap |
| Authenticated streaming client / explicit save API | API clients can send bearer; browser streaming-to-disk support varies and must be tested | Frontend/browser-support design; no full-file buffering fallback for large files |
| **Proposed same-origin HttpOnly media-session bridge** | Recommended candidate for native large-file/video ModeA; minted only after valid current bearer; server record binds sid/epoch/user/tenant/membership, narrow media path, nonpersistent Secure/HttpOnly/SameSite policy, lifetime no greater than the parent authority; every content request revalidates session and object | **D08 security/product approval required. This is not implemented and is not an approval to change current authentication.** Review account/tab switching, CSRF/Origin/Fetch Metadata, cookie path/domain, absolute expiry and logout/deactivation before rollout |
| One-use URL/download ticket without independent client authentication | Convenient native flow, but transferable until consumed; current backup ticket is an example of capability delivery | Does **not** satisfy strict ModeA identity by itself. If accepted, classify as a bounded capability with explicit policy; do not disguise it as continuously authenticated delivery |

For a future bridge, cookie/session state must not grant general REST access or extend a revoked login. Deny legacy cookie grants after tenant/account/membership epoch change; new login cannot reactivate old per-asset grants. Recheck selected resource on every Range request. Avoid tokens in query strings, persistent service-worker storage or local saved media. Public/untrusted media must not get the application's authenticated document origin. Until the bridge/streaming option is approved and verified, claim only API-client/bounded portrait ModeA capability, not completed native large-media support.

## Mode B — deliberately bounded signed delivery

Proposed issuance route: `POST /api/v2/media/assets/{asset_id}/versions/{version_id}/delivery` with requested binding. Authenticate and authorize exactly as ModeA before signing. The server selects provider, immutable version/key, method and safe response parameters. Use **TTL300**, never client-supplied TTL; no shortening/extension in this phase. Only approved category policy may choose B.

Prerequisites: verified private bucket policy and unsigned GET/LIST denial; least-privilege server signer identity; HTTPS; CORS scoped to intended methods/origins without mistaking CORS for authorization; no intermediary public alias; signatures verified on the actual compatible provider; safe response cache control and disposition/type tested. A HEAD/list permission granted to the application does not imply anonymous reads are denied. Current `ensure_bucket_exists` is not policy verification.

Signed response contract: `private, no-store, max-age=0` cache override, fixed GET/key/version and safe filename/disposition/type where provider supports tested overrides. For active formats use attachment and isolated media origin or ModeA; native S3 does not provide an arbitrary CSP override merely because metadata contains a CSP-like key. Never proxy untrusted signed media back onto the app origin without the HTTP defenses. No redirect to arbitrary client URL.

The result is a bearer URL: it exposes a provider object path and access-key **identifier**, not the secret signing key. It may be copied/replayed until expiry; user logout/permission removal stops **new issuance**, not necessarily old storage-authorized requests. Credential/policy/object changes may invalidate it sooner, but this requires provider proof, not a guarantee. A request begun before expiry may finish afterward; downloaded bytes cannot be recalled. [Official S3 capability/lifetime contract](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html).

Literal “no storage path visible anywhere” is incompatible with direct provider URLs. Remove redundant raw fields in an opt-in future contract, but choose ModeA/relay if hiding even URL-embedded paths is required. Do not call object keys secret credentials or claim opaque IDs alone prevent unauthorized reads.

## Upload/confirmation and integrity

Both modes need a proposed upload-intent ledger and quarantine lifecycle. Trusted request context fixes original tenant, uploader membership, selected resource and purpose; server fixes staging key. Signed PUT remains300 seconds when allowed. Compare actual size/type/content validation/checksum to declared bounds, not just request metadata. Current MediaFile confirmation explicitly rechecks avatar size; it does not provide a general immutable sealed-object workflow. Ticket confirmation checks its maximum but accepts a supplied key under a parent prefix without an upload-intent ledger.

Before making bytes readable, seal a validated version into a different server-owned canonical object/version inaccessible to the still-live PUT capability. A reusable old PUT may recreate/overwrite its staging key until expiry; it must not alter published bytes. Atomic/idempotent confirmation records the sealed identity, handles duplicate/racing calls and rechecks permission changes between presign and confirm. Do not serve staging objects or delete shared references speculatively. Staging cleanup happens only for proven owned, expired unreferenced intents after a reviewed retention process. This phase performs no copies, deletion, storage checks or upload changes.

## Operational acceptance and rollback

Later verify cancellation/resource release, range resume/version consistency, same-tenant object denial, tenant transfer/old-cookie rejection, no private shared-cache hits, safe active documents, no provider URL or credential logging, and actual storage tamper/expiry/delete behavior. Fail closed on unverified policy/provider identity; do not fall back from A to B or a legacy public URL on errors.

Roll out future routes opt-in under approved feature/version negotiation. Keep legacy contracts while measuring client migration; a rollback may return to a known secure adapter, not automatically reopen public paths or resurrect stale capabilities. Mode selection and immutable owner enforcement must never be controlled by a UI toggle alone. No service or policy was changed by this design.
