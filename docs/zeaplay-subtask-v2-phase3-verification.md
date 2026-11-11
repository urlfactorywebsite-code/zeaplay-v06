# ZeaPlay Subtask V2 — Phase 3 rewards implementation

Follow-up: [security, accounting and concurrency audit](zeaplay-subtask-v2-phase3-audit.md) documents additional repaired defects, the forward v4 guard migration, the enforced accounting invariant, and final verification. The results below describe the original implementation run.

Implemented and verified in the existing React/FastAPI/SQLAlchemy checkout on 2 November 2026. Phase 0 discovery and the Phase 2 verification report were read first. This work does not deploy the application, activate a production policy, migrate an installed database, or reconstruct historical balances.

## Implemented policy

Only rows created with the reserved policy marker **`subtask-additional-v1`** participate. The existing tenant `TaskWorkflowSettings` activation selects this marker for future creations. Historical legacy rows, pre-activation managed rows, and other policy versions are excluded; their markers are not changed. Turning activation off affects future creations, not existing policy ownership or earned history.

Eligible rows are undeleted children of one parent, ordered by original UTC `created_at`, then unique `id`. Original creation time, identifier and reward timezone are frozen for these rows. Position one has no additional base, bonus or penalty posting. Each later row uses the **main-task priority and team** with the existing points resolver. Display-priority override has no scoring effect. Only Completed rows receive new entries.

The assignee is inherited from the parent, matching the actual existing schema. Each parent has one canonical assignee. Existing shared assignment creates separate parent rows; the implementation does not multiply one parent's credit by a frontend assignee-array length. Followers and managers do not receive a duplicate assignee reward. Existing badge/achievement rules can still award independent XP and were not replaced by this policy.

### Verified base examples

The source defaults for `Other` and IT Support resolve High to **30**. Several other teams have different High values; production configuration is authoritative. These examples are tested synthetic fixtures using that existing 30-point value:

| Eligible rows | Additional base capacity / available when none are completed | Base after all complete | Net after all complete on time, with existing +15 bonus |
| ---: | ---: | ---: | ---: |
| 1 | 0 | 0 | 0 |
| 2 | 30 | 30 | 45 |
| 3 | 60 | 60 | 90 |
| 5 | 120 | 120 | 180 |
| 100 | 2,970 | 2,970 | 4,455 |

All four priorities are tested. The default `Other` bases are Low 10, Medium 20, High 30, Urgent 45. No seed or configuration reward amounts were changed.

### Bonus and penalty timing

The user confirmed the deadline rule: compare manually confirmed `actual_end_at` with the end of the child's planned end date, in the creator's configured IANA timezone captured at child creation. The deadline is the next local midnight converted to UTC, minus one microsecond. This includes the whole local day rather than assuming every day is 24 hours. A later profile timezone change does not change the captured deadline timezone.

`completion_point_components()` extracts the existing main-task comparison without changing its arithmetic: completion at or before the deadline gets `beforeDueBonus`; later completion gets `overduePenalty`; missing relevant times give base only. Managed completion already requires actual times and planned dates. Tests verify just before, exactly at, and just after the deadline, plus timezone capture. Parent already-earned bonuses/penalties are never copied. Main-task manager penalties, task-completion counters, badges and approvals retain their existing separate behavior.

The existing points configuration is global. To preserve tenant ownership, activation captures a normalized snapshot in the existing tenant settings row. An owner can explicitly refresh that snapshot and reprice this tenant's affected rows. Editing the global table alone does not silently reprice another tenant's previously activated policy. Tenant bonus/penalty enable flags are versioned policy data; omitted PATCH flags retain their prior values.

## Ledger and transaction behavior

The existing `XpLedger` is reused with `record_version=2` and `ref_type=subtask-additional-v1`. BASE, BONUS, PENALTY and REVERSAL are separate signed rows. Every posting stores the policy marker, rule revision, parent priority/team, resolved point values, ordinal, eligible count, recipient, original creation time, captured timezone, UTC deadline, actual end and eligibility flags in `calculation_inputs`.

Reconciliation compares current entitlements with unreversed entries. Matching amounts/recipients remain untouched. Changed entitlements reverse their original entries exactly, then append replacement components where needed. Ordinal changes with identical entitlements do not cause unnecessary wallet churn. Historical calculation inputs describe the original posting and are not rewritten when a later ordinal or policy revision changes.

Completion, its audit event, ledger entries and wallet deltas share a transaction/savepoint. An injected wallet failure leaves the child status/version, ledger and balance unchanged even if a caller catches the error and later commits. Reopening, soft deletion/restoration, reassignment, priority/team changes, relevant child date/actual-time changes, snapshot refresh and eligibility changes all invoke the same reconciliation path. Protected rows cannot be hard-deleted through task replacement or parent deletion.

PostgreSQL writes acquire a tenant advisory transaction lock before the policy and parent-group row locks. This is intentionally conservative: the existing frozen audit guards take user `FOR SHARE` locks, so independent parents sharing a recipient otherwise risk deadlocking during wallet lock upgrades. Parent locks still protect ordinal/reconciliation scope. SQLite uses a single-writer transaction. The tenant lock serializes task mutations within a tenant; very large policy refreshes should run in a suitable operational window. All deployed writers must follow this protocol.

Unique tenant/idempotency keys, unique reversal references, and a new partial unique component/event index provide database duplicate protection. Repeated reconcile calls do not repost. Stale edit requests return 409. Concurrency tests cover separate completions, simultaneous creation/completion, different parents sharing a wallet, and an independent wallet delta.

`users.points` remains the existing wallet. A shared SQL-arithmetic helper replaces additive read-modify-write updates in the existing task, badge, achievement, claim/refund and ticket award paths. Values and eligibility rules remain their existing values. Claim deduction also atomically checks that sufficient points remain. Admin absolute balance edits remain explicit legacy overrides. New-policy reversals are signed adjustments and can leave a negative balance if credits were already spent; they are not clamped or erased.

### Executed ledger example

The retained [synthetic PostgreSQL ledger capture](verification/zeaplay-subtask-v2-phase3/ledger-examples.json) contains actual generated IDs, idempotency keys, event references, timestamps and inputs from the implementation. Its initial wallet was 100, completion raised it to 145, and reopening returned it to 100:

| Lifecycle | Component | Delta | Reference |
| --- | --- | ---: | --- |
| Complete second eligible High row on time | BASE | +30 | Reconciliation event |
| Same completion | BONUS | +15 | Same event, separate component |
| Reopen | REVERSAL | -30 | Original BASE entry |
| Same reopen | REVERSAL | -15 | Original BONUS entry |

The first row generated no additional ledger entries. A late High row posts BASE +30 and PENALTY -15. Reassignment reverses the previous recipient's active components and posts eligible components to the new recipient; it does not transfer or rewrite historical entries.

## API and UI integration

- Existing `PATCH /tasks/{task}/subtasks/{child}` accepts `deleted:true/false` with `expected_version`. It is soft deletion, preserves actual times, and supports restoration. Direct edits on a deleted row require restoration first.
- Existing task PATCH, group propagation and task-transfer paths reconcile affected new-policy rows. Existing task access, active-actor checks, ticket restrictions and tenant ownership are reused. Foreign tenant checks precede reward locks and postings. Former-assignee authorization for an already authorized reassignment is retained within that transaction.
- Existing full task responses have additive `subtask_rewards`: `eligible_count`, `base_capacity`, `available_base`, ledger-net `earned`, `earned_by_recipient`, `available_recipient_id`, and `policy_version`. Task-list ledger/settings reads are batched.
- New settings operations live in the existing config router: `GET /config/subtask-rewards` and `PATCH /config/subtask-rewards`. They require the tenant owner; policy version edits use compare-and-set semantics. The normal application `/api` aliases also apply.
- The existing subtask section displays earned XP, uncompleted base availability and total base capacity separately, with Delete/Restore controls. Progress excludes deleted children. Audit history includes the immutable reconciliation event and changed components.
- Dashboard and Reports reuse their current StatCard patterns for separate earned and available totals. Dashboard's XP Banked now reads the stored wallet rather than counting projected task availability as banked XP. The existing task points utility includes only ledger-net additional credits for the requested recipient. Task change events refresh task/user caches and the two views.
- Report totals follow the selected task set; they are labeled ledger net for selected tasks, not an assertion that all entries were earned during a selected calendar interval. Available totals exclude hypothetical bonuses and penalties.

Activation request, only after schema and all compatible writers are deployed:

```http
PATCH /api/config/subtask-rewards
Content-Type: application/json

{"enabled":true,"expected_version":0}
```

Read the settings first and use the returned version for later changes. `bonus_enabled` and `penalty_enabled` are optional controls; `refresh_rules:true` explicitly adopts current configured values and reprices this tenant's policy rows. Disabling activation does not turn existing rows into legacy records. No activation was sent to an installed or production application during this work.

## Schema, compatibility and rollback

New additive migration **`g7c9e1f3a5d7`**, dependent on Phase 2 **`f6b8d0e2a4c6`**, adds:

- `subtasks.deleted_at` (UTC nullable), `subtasks.reward_timezone` (nullable for legacy).
- `xp_ledger.calculation_inputs` (nullable for historical rows).
- `task_workflow_settings.reward_policy_data` (nullable for other/historical policies).
- Ordinal lookup and partial unique component/event indexes; guards freezing policy creation order, requiring versioned soft deletion, validating new-policy ledger/settings shapes, and preventing physical deletion of these policy rows.

No rows are activated, backfilled with invented dates, retagged, or paid by this migration. Existing immutable guards remain installed. Preflight refuses incompatible columns, indexes and malformed reserved-policy data. PostgreSQL uses transactional DDL with five-second lock and 120-second statement timeouts. Normal index creation may block writers; this is not lock-free migration at arbitrary production scale.

Rehearsal creates the full model-derived Phase 2 schema with the Phase 3 columns removed, inserts synthetic historical data, upgrades twice and verifies every original selected column remains identical. Separate tests repeat adoption, refuse malformed policy state and refuse destructive downgrade. These are sanitized synthetic schemas, not an actual production dump.

Backup allowlists include the reviewed new fields and retain exact legacy/Phase 1/Phase 2 archive profiles. A missing header cannot match an absent compatibility profile. Fresh restore preserves calculation inputs, policy snapshot, timestamps and reversal relationships **without posting imported ledger rows to the destination wallet again**. Opaque audit payloads remain excluded under existing backup policy; full database backup is needed for complete opaque metadata fidelity.

Before deployment, inspect the installed Alembic revision/schema and verify a full backup. Resolve the pre-existing `tasks.tenant_id` historical-index migration mismatch before choosing an installed upgrade path. Run migrations before a newer application bootstraps its metadata: frozen older revisions intentionally reject a future settings-table shape. Do not stamp or blindly upgrade an unknown installation.

Rollback retains all additive schema and immutable history; downgrade refuses data destruction. Once activated, older writers cannot maintain new entitlements and must not mutate these tasks. Use compatible writers, read-only operation, or roll forward. Disabling future activation alone is not a complete rollback for existing policy rows. Do not restore an old balance snapshot over later reward history.

## Files changed

All paths are relative to this checkout. Existing unrelated dirty work was preserved.

| Area | Files |
| --- | --- |
| Models and contracts | `backend/app/models.py`, `backend/app/tickets/models.py`, `backend/app/schemas.py` |
| New shared engines | `backend/app/services/subtask_rewards.py`, `backend/app/services/subtask_reward_schema.py`, `backend/app/services/wallet.py` |
| Migration | `backend/alembic/versions/g7c9e1f3a5d7_subtask_rewards.py` |
| Existing workflow and point integration | `backend/app/services/subtasks.py`, `backend/app/services/gamification.py`, `backend/app/services/points_table.py`, `backend/app/routers/tasks.py`, `backend/app/routers/config.py` |
| Shared wallet callers | `backend/app/services/badge_engine.py`, `backend/app/services/rewards.py`, `backend/app/tickets/workflow_service.py` — additive wallet operations only; rule definitions preserved |
| Backup compatibility | `backend/app/backups/registry.py`, `backend/app/backups/service.py` |
| Frontend contracts/summaries | `frontend/types.ts`, `frontend/services/mockApi.ts`, `frontend/utils/subtaskWorkflow.ts`, `frontend/utils/taskPoints.ts`, `frontend/utils/subtaskRewardSummary.ts` |
| Existing UI | `frontend/components/SubtaskEditor.tsx`, `frontend/components/TaskDetailModal.tsx`, `frontend/pages/Dashboard.tsx`, `frontend/pages/Reports.tsx` |
| Tests | `backend/tests/test_subtask_rewards.py`, `backend/tests/test_task_audit_foundation.py`, `backend/tests/test_backup_manager.py`, `frontend/test/subtask-reward-summary.test.ts` |

## Validation results

Tests ran in a credential-free disposable copy, with outbound sockets blocked except the owned PostgreSQL loopback fixture. Python 3.14.3 was used locally; the application Docker runtime and a live authenticated end-to-end deployment were not exercised. API tests execute real task/config routes with synthetic identities; existing delivery/cache/badge integrations are mocked where documented by the fixture.

| Check | Result |
| --- | --- |
| Combined SQLite task/audit/migration/workflow/time-rule/backup regressions | **PASS: 175**, ten PostgreSQL-only skips. |
| Combined PostgreSQL 15 task/audit/migration/workflow/reward suites | **PASS: 79**, no failures/skips. |
| Final Phase 3 policy module after PATCH omission and shared-wallet lock hardening | **PASS: 25 PostgreSQL; 22 SQLite with three PostgreSQL-only skips.** These overlap the combined suites; do not sum counts. |
| Final deadline-range follow-up | **PASS: four PostgreSQL and four SQLite checks.** Includes the three ordinary deadline boundaries and a new unrepresentable-year validation test, with no partial writes. This final error-handling change was verified separately after the module run above. |
| Actual PostgreSQL ledger capture | **PASS: 1** synthetic example test, separate from the counts above. |
| Frontend complete Node tests | **PASS: 49**. |
| Frontend production build | **PASS**, existing bundle-size warnings. |
| Scoped new-engine/migration/test Ruff | **PASS**. Whole-repository lint was not certified. |
| Component browser check | **PASS**: earned/available separation; keyboard deletion and restore; requests omit actual times; one request per action; 390px/1280px no overflow; zero page JavaScript exceptions. Responses were intercepted locally, not live authenticated API responses. Screenshot inspected. Unrelated external calendar/logo assets were intentionally blocked. |
| TypeScript | **FAIL — existing baseline: 112 diagnostics**, unchanged normalized filename/error/message set from Phase 2. The temporary UI fixture was excluded from the source check; new production/test source introduces no new diagnostics. |
| Full backend suite / installed application / production | **NOT RUN**. The Phase 0 full-suite SQLite `to_tsvector` collection/setup failures and installed migration uncertainty remain documented baseline limits. |

The final policy module covers counts 1/2/3/5/100, all priorities, out-of-order completion, first-row zero entries, repeated requests, concurrent creation/completion and different-parent shared wallets, exact bonus/penalty boundaries, timezone snapshot, reopen/delete/restore/reassignment, config refresh/eligibility changes, preservation of omitted flags, audit/ledger/wallet rollback, immutable creation order, database uniqueness, legacy protection, real main-task awards and claim/refund behavior, tenant/RBAC failures, and migration compatibility. Existing non-point legacy counters and all old reward/achievement concurrency paths were not independently recertified as a new system.

Evidence files are retained in `docs/verification/zeaplay-subtask-v2-phase3/`. No production credentials, password hashes, or private environment files were included. Disposable services are removed after verification.

### Repeat isolated checks

Retained source copy: `C:\Users\Lenovo\AppData\Local\Temp\zeaplay-phase3-58ef7db019f146e7a9ab88e76cef8ecb`. Its runner uses test settings and network isolation. Never point these fixtures at an installed/shared database. PostgreSQL requires a separately owned disposable PostgreSQL 15 database at the explicitly permitted port.

```powershell
$reviewRoot = 'C:\Users\Lenovo\AppData\Local\Temp\zeaplay-phase3-58ef7db019f146e7a9ab88e76cef8ecb'
Set-Location $reviewRoot
python -B review_pytest.py backend/tests/test_subtask_rewards.py backend/tests/test_subtask_workflow.py backend/tests/test_subtask_schema_rehearsal.py backend/tests/test_task_audit_foundation.py backend/tests/test_task_audit_migration.py backend/tests/test_task_tabs_review.py backend/tests/test_time_bonus.py backend/tests/test_backup_manager.py

# Only an owned synthetic PostgreSQL database:
$env:ZEA_TASK_AUDIT_TEST_URL = 'postgresql+psycopg://phase1@127.0.0.1:54317/zea_subtask_phase1'
python -B review_pytest.py backend/tests/test_subtask_rewards.py
Remove-Item Env:ZEA_TASK_AUDIT_TEST_URL

Set-Location "$reviewRoot\frontend"
npm test
npm run build
npx --no-install tsc --noEmit
```
