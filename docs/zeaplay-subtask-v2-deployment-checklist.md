# ZeaPlay V2 deployment-ready checklist

Prepared 3 November 2026. **HOLD: this checklist is prepared, not completed. Production deployment requires explicit authorization after the failing and unverified gates close.** See the [acceptance matrix](zeaplay-subtask-v2-final-acceptance.md), [release notes](zeaplay-subtask-v2-release-notes.md) and [repository-specific executable runbook](zeaplay-subtask-v2-phase7-rollout.md).

## Release and security gates

- [x] Inspect actual repository architecture and Phase 0–7 dependency order; preserve the existing application and shared engines.
- [x] Reproduce and repair final cache/authorization and readiness-gate defects; run targeted HTTP/database regression tests.
- [x] Execute fresh frontend tests/build, TypeScript, Ruff, dependency scans and a redacted local Git-history secret scan; retain real failures.
- [ ] Rotate/revoke credential material found in tracked environment files. Verify restrictions/revocation with the relevant providers; preserve storage access and plan Web Push key/subscription transition.
- [ ] Provision protected runtime secrets, remove private environment files from the reviewed release/index, and coordinate history remediation without unilaterally rewriting shared Git history. Re-scan the final index, commit, artifact layers and any public export. Do not publish scanner matches or private configuration.
- [ ] Resolve dependency advisories against the actual backend/frontend/presence image dependency sets; rerun affected compatibility, authentication, accounting and browser tests. The fixture/lock scans are not image scans.
- [ ] Resolve the TypeScript and lint gates and establish a green supported legacy regression baseline. Repair obsolete fixtures separately from business logic; document any accepted exception explicitly.
- [ ] Complete full application keyboard/mobile/accessibility and installed regression checks for login, task CRUD, tickets, Kanban, Calendar/Gantt, reporting, existing rewards/achievements and notifications. Five modal-tab axe checks do not establish whole-application accessibility.
- [ ] Review a bounded artifact/commit manifest for all required Phase 1–7 files. Preserve unrelated dirty work. Record immutable image digests, dependency inventory, verification revision and artifact hashes.

## Target prerequisites and recovery rehearsal

- [ ] Establish the actual target Compose topology/project, PostgreSQL major version, volumes, database revision, private environment source and current running image digests. Do not switch PostgreSQL versions or Compose layouts as part of this change.
- [ ] Inventory all API/maintenance/worker/external task and reward writers. The production Compose references externally supplied Celery/reporting modules absent from this checkout; independently validate their images and schema compatibility.
- [ ] Build and scan the actual release images with their declared runtime versions. Local Node tests/build used Node 24; the frontend Dockerfile declares Node 18. A preceding Linux/Python 3.11 fixture run is not a production image build.
- [ ] Take protected database and media backups, verify archive integrity, and restore into separately named disposable databases/volumes. An archive listing alone is insufficient. Keep backups out of Git and public evidence.
- [ ] Rehearse the exact migration path on the sanitized restored target schema. Compare original-column fingerprints, task/reward counts, foreign keys, wallet openings and signed adjustments. Reconcile drift explicitly; do not blindly stamp an unversioned database.
- [ ] Measure lock acquisition and index creation on target-sized data. The existing chain is transactional/additive but not fully online; use a controlled write-maintenance window. Confirm lock/statement timeout behavior and abort safely on contention.
- [ ] Rehearse a compatible forward repair and artifact rollback while preserving new writes and the migration head. Establish the installation's approved recovery time/data-loss objectives and evidence; this review invents neither.

## Authorized rollout order

1. Close the above gates, identify the operator and obtain explicit production authorization. Keep reward enrollment disabled for non-pilot tenants until reviewed.
2. Confirm backups, image digests and the compatible recovery artifact. Drain/freeze every affected task/reward writer. The public-registration security fix must survive any fallback.
3. Apply the existing Alembic chain from the verified pre-V2 revision in order: `e5a7c9d1f3b5`, `f6b8d0e2a4c6`, `g7c9e1f3a5d7`, `h8d0f2a4c6e8`, `i9e1a3c5d7f9`, `j0f2b4d6e8a0`, `k1a3c5e7f9b1`. No final-review migration is added.
4. Run `backend/sql/zeaplay_v2_phase7_readiness.sql` using `psql -v ON_ERROR_STOP=1`. Stop on wrong revision, ownership/shape violations, guard/index drift or timeout. The read-only gate does not repair schema and is not a cryptographic attestation of trigger function bodies.
5. Roll out the compatible backend and validated workers before the frontend. Recheck SQL gates, authenticated reads/mutations and WebSocket recovery. Do not mix pre-V2 writers with managed records.
6. Activate the reviewed frontend, exercise a dedicated pilot task through planning/manual actuals/workflow, five slots, information tabs, rewards/reversals and notifications. Check both HTTP aliases where used. Preserve unrelated header navigation.
7. Use the existing Owner-only `GET/PATCH /api/config/subtask-rewards` with `expected_version` to enroll future children for the approved pilot tenant. All new subtasks already require managed planning independently of reward enrollment. Disabling the switch does not freeze reconciliation for enrolled rows.
8. Resume validated writers and expand only after monitored pilot acceptance. Document image digests, operator, migration output, health evidence, balances and approval. Never publish access tokens or private SQL data.

Use the existing runbook's exact backup/build/migration/health commands for an installation already using production plus GitHub Compose. They are conditional operator instructions, not commands executed by this review. Do not paste them into a differently configured installation.

## Health and rollback criteria

Monitor API latency/errors, DB lock waits/deadlocks, slot occupancy, signed ledger totals versus scoped earned balances and wallet movement, audit completeness, manual-time preservation, listener recovery, pending notification age and selected/processed/retried/suppressed/due counters. Compare against the target's measured baseline rather than inventing a global service threshold. `/health` alone proves neither database nor worker readiness.

Freeze affected writes immediately for cross-tenant visibility, unauthorized recipient delivery, duplicate credit, ledger/balance mismatch, lost audit events, more than five active parent contexts, overwritten manual actuals, migration failure or changed legacy rewards. Pause expansion for sustained lock, latency, memory or backlog regressions.

Keep the schema, ledger, audit events, manual work/corrections, durable notification receipts and post-release writes. Prefer roll forward. Switch only to a demonstrated schema-compatible artifact; a pre-V2 artifact is unsafe after enrollment. Never drop V2 columns/tables/guards, truncate history, reset wallets, recalculate historical rewards or overwrite accepted new writes with an old dump. Re-run the read-only gate and authenticated scope/accounting checks before restoring writes. Document any separate disaster-recovery reconciliation.

## Not executed here

Production backup/restore, provider revocation, release commit/push, production image build/cutover, shared-database migration, installed-service restart, tenant activation, production pilot and production rollback were **NOT RUN**. Owned local PostgreSQL/Redis fixtures are distinct from installed services; final evidence records their cleanup.
