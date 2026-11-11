# Employee profiles and avatars — implementation record

Latest review: [avatar/profile refinement report](avatar-profile-refinement-report.md). Its security findings and verification results supersede the initial implementation snapshot below.

Implemented locally on 2026-10-29. No shared database migration, running-install update, deployment, commit, or publication was performed. Existing unrelated working-tree changes were retained.

## Features and component structure

- Settings → General / Profile supports original JPEG, PNG and WebP uploads, circular crop previews, zoom/reposition, progress, retry, replacement and removal. Removing a photo restores deterministic initials while retaining the selected frame.
- Classic Slate, Aurora Neon, Solar Flare and Emerald Crest now persist on the existing user record independently of the picture. Existing role ring, achievement glow and minimal frames remain supported.
- `Avatar` centralizes authenticated image loading, thumbnail selection, accessible identity labels, loading placeholders, broken-image fallback, initials and frame styling. Profile update events refresh the current identity and an open directory/detail view without logging out.
- Shared avatars are used in both header layouts, Settings, the user directory and employee card, creation/edit previews, organization views, task assignees and comments, mention/client-related selectors, ticket approval/activity views, Gantt/levels and chat conversations/messages/members.
- `EmployeeIdentityCard` shows the existing employee ID, actual designation, role, department, account status and email, plus the new bio and existing skills. Missing values have explicit empty states. Role and designation remain separate.
- User Details retains its existing modal workflow, adds the identity card, skills chips and assigned projects, and folds existing contact/work/shift/notes into Additional Details. Directory sorting, filters, pagination, points and presence indicators remain in place.
- `SkillsEditor` adds/removes chips, searches the tenant's existing skills, prevents duplicates, and keeps structured skills separate from gamification. Limits: 30 skills, 60 characters each. The bio allows 500 characters and preserves line breaks through safe React text rendering.
- Existing optional employment/contact fields are reused. No emergency contact, certification, experience, or other intrusive personal fields were added. No new sensitive contact information is exposed to ordinary viewers.

```text
AuthProvider + profile update events
  Header → Avatar
  ProfileSettings → SkillsEditor + AvatarCropModal + Avatar
  Users → Avatar + EmployeeIdentityCard + Additional Details
  Tasks / ticket activity / selectors / chat → Avatar

Existing users and avatar_assets
  users.profile_bio + existing title / skills / contact / employment fields
  avatar_assets → existing MinIO client or LocalAdapter → normalized variants
```

## Backend and API

- Extended the existing `PATCH /users/me` and `PATCH /users/{id}` schemas and permission checks. Self-service accepts bio, skills and permitted contact information. Regular users cannot submit role changes or protected employment fields. Existing administrative user-management policy is preserved; avatar changes additionally require self, Admin or Owner authorization.
- Extended the existing `POST /users/me/avatar` to accept either the established JSON data URL or multipart `file` and `crop`. Administrative `POST /users/{id}/avatar` remains available. There is one canonical assignment/storage path.
- Existing `PATCH` avatar assignment with `avatar_asset_id: null` removes the picture. No duplicate removal endpoint was added.
- Added authenticated `GET /avatars/policy`, `GET /avatars/{id}/image` (optional `thumbnail=true`), and a compatibility read route for existing MinIO user images. Authorization is checked before returning image bytes. New image responses use private caching and `nosniff`.
- User reads and writes, avatar selection/library access, reporting-manager references and user-change notification recipients are scoped to the actor's tenant. Cross-tenant IDs return 404. Managers cannot bypass avatar restrictions through a profile patch.
- Profile edits accept `expected_updated_at` and return 409 for stale edits. User-row locking serializes avatar replacements. Audit events record the actor, target and changed reference without image bytes.
- The bio is included in the existing backup export/import contract. Existing authentication mechanisms and role definitions were retained.

## Migration and storage

`backend/alembic/versions/c3e5f7a9b1d2_employee_profile_avatar.py`, after `b2c4d6e8f0a2`, adds only nullable fields:

| Existing table | Additions |
| --- | --- |
| `users` | `profile_bio VARCHAR(500)` |
| `avatar_assets` | indexed `tenant_id`, `storage_provider`, `thumbnail_path` |

The existing user-to-avatar foreign key is reused. Tenant ownership is backfilled from existing creators. The migration is additive and tested for repeat application on a disposable database. It deliberately refuses a destructive downgrade.

The server checks the declared MIME against the decoded JPEG/PNG/WebP format, verifies and fully decodes the image, enforces byte/pixel/dimension limits, corrects EXIF orientation, validates crop bounds, discards metadata, and encodes fresh 512px display and 128px thumbnail WebP files. SVG/GIF/AVIF uploads, malformed/truncated images, mismatched MIME and oversize images are rejected. Original filenames are never used as storage paths.

Limits use `VEE_AVATAR_MAX_FILE_SIZE_MB` (default 5) and `VEE_AVATAR_MAX_PIXELS` (default 25,000,000). The UI reads the server policy.

Configured MinIO credentials reuse the existing client/bucket. Otherwise the existing local adapter stores files below `VEE_MEDIA_ROOT/private-avatars/<tenant>/<user>/<random-version>`. This directory is outside the public `/uploads` mount. Only references are stored in the database. New versions use new paths to invalidate stale photo caches. Unreferenced old variants are removed after commit; a rollback removes new variants and keeps the previous picture. Shared/default assets are retained while referenced. Cleanup failures are logged.

The source Compose configurations now persist `/app/media` through `backend_media`. Before any future installation update, back up the database and existing local media, apply the migration through the installation's migration process, and verify the actual MinIO policy denies public reads of `private-avatars/*`. Historical public legacy objects/URLs require an operator review; changing API reads does not revoke an existing public object URL. No bucket policy was changed here.

## Files created

- `backend/app/profile_validation.py`
- `backend/alembic/versions/c3e5f7a9b1d2_employee_profile_avatar.py`
- `backend/tests/test_employee_avatar_profile.py`
- `frontend/components/Avatar.tsx`, `EmployeeIdentityCard.tsx`, `SkillsEditor.tsx`
- `frontend/hooks/useAvatarPolicy.ts`
- `frontend/test/user-avatar.test.ts`
- `frontend/checks/avatar-profile.browser.js`, `avatar-profile.fixture.tsx`, `avatar-profile.fixture.html`
- This implementation record and browser screenshots under `frontend/checks/avatar-profile-*.png`.

`frontend/pages/ProfileSettings.tsx` already existed as an untracked in-progress file and was extended in place.

## Files modified for this feature

- Backend: `app/avatar_utils.py`, `config.py`, `models.py`, `schemas.py`; `routers/users.py`, `avatars.py`, `auth.py`, `data_admin.py`; `services/minio_media_service.py`; `chat/serializers.py`, `chat/services.py`.
- Frontend core: `hooks/useAuth.tsx`, `constants/avatarFrames.ts`, `types.ts`, `services/mockApi.ts`, `utils/userAvatar.ts`, `utils/appEvents.ts`, `utils/image.ts`.
- Frontend profile/identity: `pages/ProfileSettings.tsx`, `Users.tsx`, `GanttView.tsx`, `LevelsManager.tsx`; `components/Header.tsx`, `AvatarCropModal.tsx`, `AvatarPicker.tsx`, `CreateUserModal.tsx`, `EditUserModal.tsx`, `OrganizationTreeSection.tsx`, `SameTaskLogModal.tsx`, `CreateTaskModal.tsx`, `CreateTicketModal.tsx`, `TaskDetailModal.tsx`.
- Shared consumers: `components/ui/MultiSelect.tsx`, `MentionPicker.tsx`; `components/Tickets/TicketApprovalPanel.tsx`, `TicketStatusTimeline.tsx`, `TicketActivityTimeline.tsx`; chat `ChatModal.tsx`, `ChatSidebar.tsx`, `ConversationListItem.tsx`, `EmptyChatState.tsx`, `MemberPanel.tsx`, `MessageItem.tsx`.
- Verification and persistence: `frontend/checks/settings-navigation.browser.js`, `docker-compose.yml`, `docker-compose.github.yml`.

## Verification

Browser tests use intercepted fixture APIs, and database tests use disposable SQLite databases. The MinIO adapter check uses a simulated object store; it does not prove external storage policy or availability.

| Check | Result |
| --- | --- |
| Avatar/profile, Settings security, navigation policy/readiness/socket backend checks | **PASS ? 123 tests** |
| Final focused avatar/profile backend rerun | **PASS ? 21 tests** |
| Frontend unit/component rendering tests (`npm test`) | **PASS ? 25 tests** |
| Avatar/profile browser component checks | **PASS ? 13 checks**, no uncaught errors |
| Wider Settings browser regression | **71 PASS, 6 FAIL**; failures are in Sidebar Management drag/reorder and subsequent editor scenarios |
| Production frontend build | **PASS**, with existing large-chunk warnings |
| Focused Ruff syntax/import/undefined-name checks (`E9,F,I`) | **PASS** |
| Full Ruff rule check | **FAIL** under the current rules, including FastAPI dependency defaults, naive UTC timestamps and legacy typing conventions |
| Frontend typecheck | **FAIL ? 118 existing errors**, same diagnostics as the pre-frontend-change snapshot; no new diagnostics |
| Entire backend test directory on SQLite | **FAIL during collection**: three older test modules require PostgreSQL-specific `to_tsvector` schema functionality |
| Frontend ESLint | **NOT RUN** ? no configured lint script/package in this checkout |
| Source Compose validation and Alembic graph | **PASS**; the new migration is the single head |
| `git diff --check` | **PASS** |
| Live database migration, live MinIO policy and deployment | **NOT RUN** |

The first broad Settings pass exposed the avatar multipart header and header-button accessible-name integration issues; both were corrected and their avatar/header scenarios subsequently passed. The broad browser harness now waits for dirty-draft registration and restores dialog handling after failures so one failed case does not block later cases. The remaining Sidebar Management failures were retained as failures; this feature does not modify that module.

## Remaining operational limits

- Live PostgreSQL migration and live MinIO authorization were not run. Apply and verify them before installation acceptance.
- Old public image URLs cannot be revoked by this source change alone. Verify storage access policy and retain a media backup before retiring historical objects.
- File cleanup is transaction-aware; a storage outage during post-commit cleanup logs an orphan for operator follow-up. No background reconciliation service was introduced.
- No emergency-contact storage or proficiency taxonomy was added; existing optional business fields and the existing skill list remain authoritative.
