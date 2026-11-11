# Zea.Play Settings regression review

Historical six-tab review. Current API authorization, tenant isolation, migration and production-readiness evidence are documented in [sidebar-production-readiness.md](sidebar-production-readiness.md).

Reviewed locally on 2026-10-29. This report supersedes the initial navigation-only verification. No deployment, running-install rebuild, production infrastructure change, shared database migration, or external message delivery was performed.

## Findings fixed

- Added unsaved-change protection for Profile, passwords, Support, webhooks, API key preparation, integration configuration and in-progress media/configuration actions. Router navigation and browser Back/Forward use the supported navigation blocker; reload/close uses beforeunload. Cancelling retains the form. Hash URLs are preserved using createHashRouter with the existing routes and provider hierarchy.
- Restricted Profile's backup/import/full-reset controls to Owner, matching the established backend guard. Canonical Settings routes and legacy redirects continue through the same role registry and ProtectedRoute guards.
- Removed unused Profile integration constants, missing type aliases, CredentialRow, imports, the unused Header support callback and duplicate mobile Escape handling. Preserved the pre-existing Header logo navigation edit.
- Restored the previously blank SMTP/OAuth API subtabs using the existing service methods: configuration loading, create/edit/delete, SMTP test request, and OAuth rotation. Saved passwords are not prefilled; blank edit passwords preserve the existing value. OAuth credentials require explicit reveal. AI provider configuration reuses the existing /config/api contract.
- Fixed AvatarCropModal's missing onCompleteWithMetadata destructuring. Avatar changes no longer overwrite a dirty Profile form. Added accessible field labels/status messages, keyboard media previews and active-tab scrolling.
- Reused Headless UI dialogs for media preview, avatar cropping and mobile Pages: focus containment/restoration, Escape dismissal, accessible titles and correct layering. Mobile menu controls expose expanded/pressed states and close on desktop resize.
- Kept media previews open after cancelled deletion, caught clipboard failures, disabled overlapping Master Control saves, and cleaned up Support success timers and duplicate-submit/reset races.
- Replaced shared persistent bearer-key history with account-scoped session history. Only matching account subjects migrate from legacy history, logout clears session credentials, and unrelated preferences remain intact. Credential-bearing configuration responses are no longer cached in localStorage. Login/logout invalidate response caches. Ordinary users receive api_key=null from /config/api.

## Provider credential security

The review confirmed that the earlier production build embedded configured Gemini provider credentials in downloadable JavaScript. The fix removes browser key selection/storage and SDK credential construction. Vite excludes legacy GEMINI_API_KEY variables from public env output and no longer injects private process.env values. Retired browser provider credential/usage caches are cleared without resetting theme preferences.

AI task generation, reports and the assistant retain their existing actions through authenticated /api/ai/generate and /api/ai/message backend routes. The gateway keeps keys on the server, preserves the existing prompts/system instructions/JSON schemas, retries quota failures with another configured key, and does not return provider errors or echoed credentials. The upstream generation mapping follows the [documented Gemini generateContent contract](https://ai.google.dev/api/generate-content).

Configure backend keys using VEE_GEMINI_API_KEYS (comma separated), or use Owner Settings > API > AI provider to update the existing server API configuration. VEE_GEMINI_DAILY_LIMIT defaults to 60 per key in each process; quota/cooldown counters are process-local and the provider remains the authoritative quota enforcer. VEE_AI_WEBHOOK_URL defaults to the application's existing assistant webhook; custom frontend webhook configuration must move to this server setting. No production configuration was changed and no real provider request was sent.

Keys included in any previously served build must be rotated by their account owner. Rotation and removal of old deployed assets were not performed. Existing frontend local env files were not modified; their legacy Gemini values are excluded from new builds. The rebuilt local production artifacts were scanned against each configured local provider key with zero matches.

## Routes and permissions

This checkout retains /#/ hash URLs. Redirects replace the legacy history entry while preserving query parameters, anchors and navigation state.

| Previous route/entry | Canonical route |
| --- | --- |
| /settings, /profile, Profile | /settings/profile |
| /support, former Support entry | /settings/support |
| /master-control | /settings/master-control |
| /api/overview | /settings/api |
| /logs | /settings/logs |
| /media | /settings/media-library |

| Module | User | Manager | Admin | Owner |
| --- | --- | --- | --- | --- |
| Profile / Support / Media | Yes | Yes | Yes | Yes |
| Logs | No | Yes | Yes | Yes |
| API / Master Control | No | No | No | Yes |
| Profile backup/import/reset and media deletion | No | No | No | Yes |

The existing backend get_current_admin helper includes Manager, Admin and Owner. Those established roles retain configuration endpoint privileges; the Settings API route remains Owner-only. Ordinary User configuration reads never return the provider key. Backend webhook rules remain Admin/Owner and log scoping/retention guards remain unchanged. No administrative role was added or broadened. AI requests use the existing active-user guard, retaining the previous AI feature access.

There is one Settings gear item in the desktop sidebar and mobile Pages menu, with no relocated standalone entries or footer dropdown. The version still opens release notes and the account menu still provides logout. Unrelated navigation retains its relative order.

## Exact verification

Frontend working directory: frontend/.

| Command/check | Result |
| --- | --- |
| npm test | PASS, exit 0: 17 tests |
| Saved Playwright browser suite | PASS: 60 checks; zero uncaught JavaScript errors |
| npm run build | PASS, exit 0 |
| npx tsc --noEmit --pretty false | FAIL, exit 2: 118 existing diagnostics, reduced from 134 before review; none in the reviewed Settings/AI implementation |
| npm run lint | FAIL, exit 1: Missing script: lint; no linter is configured |
| npx tsc --noEmit --pretty false --noUnusedLocals --noUnusedParameters | Global command retains pre-existing failures; no unused-symbol diagnostics in reviewed files |
| git diff --check | PASS, exit 0 |
| node checks/check-provider-credentials.mjs | PASS, exit 0: zero provider credential matches in production artifacts |

Backend authorization/proxy tests were run from repository root with an isolated in-memory database and bytecode writing disabled:

```powershell
$env:VEE_DATABASE_URL='sqlite:///:memory:'
$env:VEE_ENVIRONMENT='test'
$env:PYTHONDONTWRITEBYTECODE='1'
.\backend\venv\Scripts\python.exe -m pytest backend/tests/test_settings_security.py -q
```

Result: PASS, exit 0: 21 tests. Existing SQLAlchemy/Pydantic deprecation warnings remain. Tests use the real authorization dependencies with fixture identities/database responses and intercepted outbound HTTP; they do not certify a production JWT/session or live database persistence.

Run the browser suite by starting npm run dev -- --host 127.0.0.1 --port 6319 --strictPort from frontend/, then passing frontend/checks/settings-navigation.browser.js to Playwright browser_run_code_unsafe as filename. The suite intercepts API, storage, support and AI requests. It exercises routing/history/refresh, role visibility and forbidden canonical/legacy URLs, dirty-form cancellation and beforeunload, forms and payloads, avatar crop/finalize, integration CRUD/rotation/test actions, session credential isolation, desktop/collapsed/390px/768px navigation, keyboard/focus and error/empty states. No production mutation or external delivery is attempted.

## Files

Created during implementation/review: ProfileSettings.tsx, PreserveLocationRedirect.tsx, settingsNavigation.ts, useUnsavedChanges.tsx, IntegrationSettingsPanel.tsx, ProviderSettingsPanel.tsx, credentialHistory.ts, settings-navigation.test.ts, credential-history.test.ts, settings-navigation.browser.js, settings-navigation-results.json, check-provider-credentials.mjs, backend/app/routers/ai.py, backend/tests/test_settings_security.py and this report.

Modified: frontend App, Settings, Sidebar, Layout, Header (only orphan support callback), ProtectedRoute, SupportFormModal, AvatarCropModal, ApiOverview, Logs, MasterControl, MediaLibrary, MediaCard, MediaDetailsDrawer, Chatbot, Reports, GenerateTaskWithAIModal, mockApi, aiClient, geminiClient, Vite config and frontend README; backend configuration, API configuration reads and router registration. Retired frontend/utils/geminiKeyStore.ts after all callers moved to the server gateway. No dependencies or database schemas changed.

## Outstanding / unverified

- Global TypeScript and lint gates are not green. Remaining diagnostics are outside the reviewed code (primarily visual effects, seed data and existing task modules); lint has no project script.
- Live SMTP delivery, OAuth authorization flows, real storage operations, real AI provider calls and production authentication/persistence were not exercised. Browser request compatibility and isolated backend guards are verified.
- Owner data export/import/full reset were inspected for preservation and role gating; destructive restore/reset execution was intentionally not performed.
- Provider keys require server configuration before the new AI gateway is used. Previously served provider keys require owner-managed rotation. Neither production configuration nor deployment was performed.
- Existing Lottie eval and large-bundle build warnings remain.
