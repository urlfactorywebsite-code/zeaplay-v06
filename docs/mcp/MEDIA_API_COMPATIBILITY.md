# Media identifiers and backward-compatible API evolution

Date: **12 November 2026, Asia/Calcutta**. **ANALYSIS / PROPOSED CONTRACTS ONLY.** No existing field, endpoint, schema, frontend component or signed TTL was changed. [Inventory](MEDIA_VISIBILITY_MATRIX.md), [ownership](MEDIA_OWNERSHIP_ARCHITECTURE.md), [hybrid delivery](MEDIA_HYBRID_DELIVERY_DESIGN.md).

## Identifier vocabulary and finding interpretation

An opaque asset/version/upload ID identifies a registry record; it is not authorization. An object path/key locates provider bytes; it is not a secret credential, and possession does not authorize application issuance. A signed URL is a deliberately transferable **bearer capability** until its applicable expiry; protect the whole URL even though its path is not itself a secret. SigV4 `X-Amz-Credential` contains an access-key **identifier**/scope, not the secret signing key. Provider secret access keys, service-role keys, private keys, application access/refresh tokens and cookies are actual credentials and must never appear in these media responses or logs.

The [Phase2A.1.1 literal no-key finding](PHASE_2A_1_1_MEDIA_SECURITY.md) should not be misread as a demonstrated leaked S3 signing secret. Redundant storage details can be minimized, but direct provider GET/PUT URLs inherently reveal a provider path and credential identifier. A future opaque-ID JSON contract cannot promise path secrecy while also returning those direct URLs. Use an authenticated application relay when even that path disclosure is unacceptable. Do not “fix” a finding by deleting an upload handshake field or changing URL semantics without a client plan.

## Field classification against current consumers

**A** required by current upload/download protocol; **B** required by actual checked-in frontend behavior; **C** internal detail unnecessarily exposed by that behavior; **D** dependency not proven, requiring verification. The primary label below concerns the specific field, not the entire response. D for external consumers remains a release gate even where checked-in use supports C.

| Current field / response | Primary class | Current evidence and dependency | Future action, not performed |
|---|---|---|---|
| `MediaItemRead.storage_path` | **C** | [schemas.py](../../backend/app/schemas.py); legacy mockApi methods pass responses through; no checked-in runtime component reads storage_path. Backend management uses DB record, not a client round trip. External callers/backups may depend on it (**D**) | Omit in opt-in v2; preserve legacy response shape until D09 approval; retain server mapping and restore metadata |
| `MediaItemRead.public_url` | **D for legacy consumers** | A current legacy delivery field, but no checked-in terminal component caller of the legacy list/get/upload wrappers was found. Current library page uses MediaFile read_url instead. Saved links and external clients remain unknown dependencies; general URL rendering does not prove this exact field is consumed | Preserve the field now; replace with a typed delivery descriptor only for opted-in clients after caller verification. Never return a supposedly public URL that requires an unavailable auth bridge |
| `MediaPresignResponse.bucket` | **C** | [media router](../../backend/app/routers/media.py) returns it; [mockApi](../../frontend/services/mockApi.ts)::presignMediaUpload maps it; [MediaLibrary](../../frontend/pages/MediaLibrary.tsx) uploads using uploadUrl/content type only, not bucket | No separate bucket field in v2; direct URL still contains a provider path. Preserve current field now |
| `MediaPresignResponse.object_key`→objectKey | **C** | Same mapping; confirmation sends file_id, not object_key. No checked-in terminal consumer found. External dependency **D** | Server upload-intent resolution; remove only in new contract |
| Media `file_id`→fileId | **A + B** | Current presign→confirm(fileId) and delete flow | Keep old ID stable; new registry mapping can expose separate asset/version/upload IDs without changing v1 |
| Media `upload_url` | **A + B** | Actual axios.put(uploadUrl,file,Content-Type) with upload progress; current upload requires this capability | Keep methods/headers stable for the old flow; v2 typed upload descriptor |
| Media `expires_in` | **A protocol metadata; no terminal B use found** | Required current response schema; mockApi maps expiresIn, but MediaLibrary does not use it to schedule expiry. Existing value300 is a compatibility commitment | Retain now; future UI should track expiration/reacquire capabilities. Do not alter300 seconds |
| Media `read_url`→readUrl | **A + B** | MediaCard image, DetailsDrawer image/video/anchor, MediaLibrary copy URL | Mode selection must drive UI; ModeA requires auth bridge/streaming, ModeB may still return URL. Reacquire expired delivery instead of caching it indefinitely |
| Ticket presign `fileKey` and confirm request `fileKey` | **A + B** | [TicketAttachmentsPanel](../../frontend/components/Tickets/TicketAttachmentsPanel.tsx)/[Summary](../../frontend/components/Tickets/TicketAttachmentsSummary.tsx) echo presign.fileKey to confirm. Prefix/leaf plus parent permission checked server-side | Preserve v1 handshake. Opt-in v2 uses upload_id; do not replace fileKey with an opaque ID in the same v1 field |
| Ticket list/confirm `file_key`→fileKey | **C for checked-in display/delete; external D** | mockApi mapTicketAttachment stores it; panels display filename/size/date and delete attachment.id. No byte download route exists in this router | v2 returns asset/attachment ID and protected delivery action; old field retained until consumers verified |
| `AvatarFinalizeResponse.profile_image_key`→profileImageKey | **C for checked-in runtime; external D** | Finalize service returns `user.avatar_asset.file_path`; wrapper/types map it; no checked-in UI call of finalizeAvatarUpload found | v2 finalize returns asset/version and protected portrait URL; no raw private path. Do not remove existing field now |
| `UserRead.profile_image_key` | **D / compatibility tombstone, not normal wire exposure** | Schema still declares it, but `UserRead.serialize_profile` explicitly pops it. mapUser defaults missing field to null; userAvatar selection uses URLs | Preserve serializer behavior. Do not claim every user response exposes it or manufacture a null field just to match a type |
| `profile_image_url`, `avatar_url`, `AvatarAssetRead.url` | **B** | [Avatar.tsx](../../frontend/components/Avatar.tsx), [userAvatar.ts](../../frontend/utils/userAvatar.ts): authenticated fetch for protected image routes, bounded blob cache; external/image fallbacks | Keep bounded authenticated image path and identity invalidation; URL/version change must prevent stale picture reuse |
| Chat `storage_key`→storageKey | **A/B today** | mapChatMessagePayload echoes uploaded metadata; normalizeMessage and MessageItem/MemberPanel use it as identity/key. Client sends storage_key/url when attaching to message | v2 binds upload intent/asset to permitted conversation/message; migrate keys to stable attachment IDs. Do not discard storage_key before the old message creation flow changes |
| Chat `url`, task/template attachments and featured image, reward/badge URLs | **B** | Anchors/images and copied reference lists. They do not carry independent object ownership | Migrate to typed asset references per resource/version; preserve unresolved legacy strings with explicit status and approved link plan |
| Badge `image_asset_path`, reward `image_ref` | **D**, with internal C where only URL rendering proven | Mapping/management contracts and provider-specific delete/restore references exist; exhaustive external/client workflow verification not run | Retain now; inventory exact references and restore formats before v2 omission |
| Provider access-key ID in signed URL | **A for provider protocol** | SigV4 SDK-generated credential scope | Do not mislabel it as secret; avoid recording complete URL. Never expose corresponding secret/signing key |

Checked-in source anchors: [schemas.py](../../backend/app/schemas.py) `MediaItemRead`, `MediaPresignResponse`, `MediaFileListItem`, `AvatarFinalizeResponse`, `UserRead.serialize_profile`; [ticket request/response classes](../../backend/app/tickets/attachments_router.py); [frontend types](../../frontend/types.ts); mockApi `presignMediaUpload`, `confirmMediaUpload`, `listMediaFiles`, `finalizeAvatarUpload`, legacy media/ticket/chat methods; [chat normalizer](../../frontend/features/chat/utils/normalizeMessage.ts), [MessageItem](../../frontend/features/chat/components/MessageItem.tsx), [MemberPanel](../../frontend/features/chat/components/MemberPanel.tsx). Search results are source evidence, not live telemetry or proof of no external consumer.

## Current response examples — synthetic, not captured customer traffic

Media presign currently returns the following shape. The deliberately invalid example signature is not a working credential; the URL still illustrates unavoidable provider-path disclosure.

```json
{
  "upload_url":"https://storage.example.invalid/private-demo/media/demo/object.png?X-Amz-Credential=DEMOACCESS&X-Amz-Expires=300&X-Amz-Signature=NOT_A_VALID_SIGNATURE",
  "bucket":"private-demo",
  "object_key":"media/demo/object.png",
  "file_id":"11111111-1111-4111-8111-111111111111",
  "expires_in":300
}
```

Selected current legacy MediaItem fields (other metadata fields remain as documented in the inventory):

```json
{
  "id":"22222222-2222-4222-8222-222222222222",
  "owner_id":"33333333-3333-4333-8333-333333333333",
  "filename":"example.txt",
  "storage_provider":"local",
  "storage_path":"uploads/demo-user/2026/11/example.txt",
  "public_url":"/uploads/demo-user/2026/11/example.txt"
}
```

Current ticket presign and confirmation are distinct from media file_id confirmation:

```json
{
  "uploadUrl":"https://storage.example.invalid/ticket-demo/tenant/demo/tickets/demo/opaque-example.txt?X-Amz-Expires=300&X-Amz-Signature=NOT_A_VALID_SIGNATURE",
  "fileKey":"tenant/demo/tickets/demo/opaque-example.txt",
  "headers":{"Content-Type":"text/plain"}
}
```

```json
{"fileKey":"tenant/demo/tickets/demo/opaque-example.txt"}
```

Current avatar finalize may return `profile_image_key:"private-avatars/demo-tenant/demo-user/opaque.webp"` with an opaque protected `/avatars/{id}/image` URL; normal UserRead serialization omits that key. This difference must survive compatibility tests.

## Proposed opt-in opaque-ID contract — not existing endpoints

Prefer a new external `/api/v2/media` surface, backend `/v2/media` registered once. Avoid introducing another `/api/api` alias accidentally. Do not change old routes, response fields or path meaning. An optional future v2 frontend adapter is explicit; old clients continue v1 until an approved cutover.

`POST /api/v2/media/uploads` request: logical purpose/authorized parent, display metadata and size/hash constraints. Server derives tenant/user/membership/provider/key/initial private policy. Any publication request is a separate reviewed action, not a body-controlled owner/visibility override.

```json
{
  "purpose":"task_attachment",
  "resource":{"type":"task","id":"task-demo"},
  "file_name":"example.pdf",
  "content_type":"application/pdf",
  "size_bytes":2048
}
```

Response for an approved direct-upload capability:

```json
{
  "upload_id":"44444444-4444-4444-8444-444444444444",
  "asset_id":"55555555-5555-4555-8555-555555555555",
  "version_id":"66666666-6666-4666-8666-666666666666",
  "status":"PENDING",
  "upload":{
    "method":"PUT",
    "url":"https://storage.example.invalid/staging-demo/opaque-object?X-Amz-Expires=300&X-Amz-Signature=NOT_A_VALID_SIGNATURE",
    "headers":{"Content-Type":"application/pdf"},
    "expires_in":300
  },
  "confirm_url":"/api/v2/media/uploads/44444444-4444-4444-8444-444444444444/confirm"
}
```

Server upload-intent record binds this ID to the exact staging object and current authority. Confirming that **upload ID** rechecks session/tenant/parent/purpose, validates actual metadata/content under the later approved upload rules and seals a canonical immutable version. Retry is idempotent; another user cannot claim a known upload ID or arbitrary key. For strict identifier confidentiality, `upload` instead advertises a bearer-authenticated application upload endpoint; it must not pretend a provider URL conceals its object path.

Proposed metadata and ModeA delivery descriptors:

```json
{
  "asset_id":"55555555-5555-4555-8555-555555555555",
  "version_id":"66666666-6666-4666-8666-666666666666",
  "file_name":"example.pdf",
  "content_type":"application/pdf",
  "size_bytes":2048,
  "visibility":"PRIVATE",
  "delivery":{
    "mode":"AUTHENTICATED",
    "method":"GET",
    "url":"/api/v2/media/assets/55555555-5555-4555-8555-555555555555/versions/66666666-6666-4666-8666-666666666666/content?binding_id=binding-demo",
    "authentication_required":true
  }
}
```

For an explicitly approved ModeB request, future `POST .../delivery` returns `{mode:"SIGNED",url,expires_in:300,expires_at,version_id}`. That URL remains transferable and embeds provider details. No raw bucket/key field is necessary alongside it; it is not a path-secrecy guarantee. Native ModeA URLs require the approved browser bridge described in the hybrid design; putting them in existing img/video/anchor elements without that bridge will fail authentication.

## Versioning, client migration and old upload-confirm compatibility

| Stage | Proposed later action | Compatibility/security gate |
|---|---|---|
| 0 — this phase | Document contracts/unknown dependencies; no edits | All existing fields/TTL/routes unchanged |
| 1 — approved additive registry | Internal mapping and versioned writes with legacy serializers unchanged | Do not simply add fields to strict legacy responses; validate old schema and backup formats. Reconcile ownership first |
| 2 — opt-in v2 | New version path and explicit client capability selection; dual contract tests | New upload_id confirmation alongside old file_id/fileKey protocols; never reinterpret an existing field. Provider methods/headers/signature parameters fixed server-side |
| 3 — migrate frontend by feature | MediaLibrary typed descriptors and expiry refresh; native ModeA bridge; ticket upload_id flow; chat attachment IDs; task/template reference adapter; portraits still bounded and identity-scoped | Test actual browser img/video/Range/download/copy interactions. Check response.ok before confirm; bound retries and avoid logging signed URLs. Small Blob use is not a large streaming solution |
| 4 — observe and notify | Approved aggregate endpoint/contract-version telemetry, external client inventory, release notice and migration window | Do not log paths, signatures, content, tokens or arbitrary request bodies. No date/window is invented here; D09 approval required |
| 5 — controlled cutover | Category/tenant-by-tenant activation with expected policy/mapping epochs | Legacy private requests cannot fall back to public URLs/current-uploader tenant. Old copied public links may intentionally stop after explicit approval; that is a privacy cutover, not silent backward compatibility |
| 6 — deprecate/remove old fields | Only after caller/restore dependencies and approved sunset are satisfied | Keep mappings/provenance and test old support window. Unknown clients block removal; v2 opt-in alone does not prove they migrated |

Some backwards compatibility has a hard limit: a previously anonymous copied URL cannot both remain anonymously usable and become private. Preserve old interfaces during analysis and planned adaptation, then obtain explicit approval for link invalidation and owner notices. A strict-private v2 asset must not generate a legacy public fallback just to make an old UI appear functional. If a legacy client cannot authenticate native delivery, use a reviewed compatibility bridge or explicit upgrade-required behavior after approval; do not leak bytes.

Current wrappers also expose two source gaps: `uploadMedia(...,provider)` sends a provider form value the backend upload handler does not accept/use; `getMediaProviders()` requests a provider-list path without a matching literal route. No caller found does not justify changing either in this phase. Record and test them before promising a legacy frontend migration works.

## Contract tests and rollback requirements

Later synthetic contract tests must keep exact current response field names/types/aliases; prove normal UserRead key omission and finalize's legacy field; preserve media file_id vs ticket fileKey echo; reject model-controlled identity/provider/TTL; prove current frontend no longer reads raw v2 key fields; verify v1 strict clients and versioned backup imports; test old link notices and denied unsafe fallback. Mock tests establish schema/client behavior only, not S3 enforcement.

Rollback v2 UI/version selection only to a known secure adapter. Retain original tenant ownership, mapping/epoch checks and closed public paths for already activated private assets; old uploader-derived logic is not an acceptable security rollback. Keep300-second signed TTL unchanged. No API/schema/client change or rollback is executed now.
