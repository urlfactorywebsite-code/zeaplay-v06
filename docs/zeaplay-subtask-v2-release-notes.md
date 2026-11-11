# ZeaPlay V2 Phases 0–7 release candidate

Prepared 3 November 2026. **NOT APPROVED FOR PRODUCTION. No deployment occurred.** The [final acceptance matrix](zeaplay-subtask-v2-final-acceptance.md) and [deployment checklist](zeaplay-subtask-v2-deployment-checklist.md) control release readiness. Earlier phase reports describe their own runs, not the deployed application.

## Delivered behavior

- Extend the existing FastAPI/SQLAlchemy/Alembic and React/Vite application. No replacement task, wallet, notification system or standalone application was introduced.
- Newly created subtasks require planned dates and use To Do, In Progress, Paused, Testing and Completed. Historical checklist rows retain their legacy contract. Manual actual timestamps require explicit confirmation and are not populated by workflow or activity timers. Existing approval and object-access rules remain in use.
- Subtask display priority inherits the current parent priority unless overridden. Additional rewards always use the main task's configured team/priority value. Future reward enrollment is controlled independently by the tenant's existing Owner-only reward-policy setting.
- For eligible undeleted new-policy children ordered by original creation time and ID, the first has zero additional reward; subsequent completed children earn the existing main-task base value and applicable existing bonus or penalty. Reconciliation uses immutable signed components and compensations, transaction locks and database uniqueness. Historical credits are not recomputed.
- Personal activity supports five distinct active parent tasks per user, persistent server-recorded elapsed time, paused slots and separate confirmed productive intervals. Overlap allocation prevents counting the same user's productive time twice. No global daily-hours policy was added.
- The existing task information actions open one modal with Overview, Status Timeline, Subtasks, Points and Activity. Authorized histories are paginated; unknown historical facts remain unknown. The frontend uses authoritative point summaries.
- Existing durable notifications, preferences, unread badge, native task WebSocket, Redis fanout and browser delivery are extended for task/reward/workload changes. Recipients are resolved through tenant-scoped live relationships and deduplicated. External push/webhook delivery is at least once, not an exactly-once guarantee.

## Security and reliability repairs

Phase 7 restricts public registration to a new empty workspace, preserves authenticated enrollment, reserves SQLite writes before nested audit savepoints, and reconnects the existing bounded Redis listener with a data-free authorized resync.

This final review additionally fixes:

| Confirmed problem | Repair |
| --- | --- |
| A cache transport failure could surface as HTTP failure after a committed task change | `backend/app/cache.py` treats Redis read/write/invalidation failures as cache misses or best-effort invalidation. Socket operations have bounded timeouts and no automatic command retry. Warnings are rate-limited and omit keys, URLs and exception bodies. |
| A removed watcher could replay cached page, Kanban or calendar aggregate data after missed invalidation | `backend/app/routers/tasks.py` reads membership-dependent User/Manager results from current scoped SQL. Owner/Admin tenant-wide caching remains keyed by tenant/user/access parameters. This intentionally increases member read traffic; measured query cost is recorded in the acceptance report. |
| A readiness script could accept a different trigger on a table, a replica-only guard or a same-named wrong index | `backend/sql/zeaplay_v2_phase7_readiness.sql` checks 52 frozen trigger contracts, ordinary-write enablement, handler/schema identity and six required index contracts including validity, ordered columns, uniqueness, access method and partial predicate. The script remains read only. |
| OpenAPI published a shadowed ticket DTO for canonical task updates/completion | Two legacy decorators in `backend/app/tickets/workflow_router.py` now use `include_in_schema=False`. Runtime registration/handlers and ticket endpoints remain present; task documentation now reports the actual `TaskRead` response. Two before/after contract tests and the affected integrated HTTP suite pass. |

The final-review source delta consists of `backend/app/cache.py`, the cache conditions/helper in `backend/app/routers/tasks.py`, the two schema-visibility flags in `backend/app/tickets/workflow_router.py`, the SQL readiness gate, `backend/tests/test_final_readiness.py`, `backend/tests/test_final_migration_gate.py`, `backend/tests/test_final_api_contracts.py`, the three final handoff documents, superseding report links and the final evidence directory. The rest of the large dirty checkout predates this review. Do not use the full working-tree diff as the release manifest; the evidence includes a file-level comparison against the preceding verified fixture and hashes of reviewed source.

## Compatibility and migration

HTTP response schemas and reward values are unchanged by this final review. Public registration into an existing workspace intentionally returns 403; use authenticated user management. A stale subtask version is rejected rather than silently replacing newer data. Membership-dependent reads are no longer served from task body caches.

No new migration, schema backfill, historical audit synthesis or historical point recalculation was added in this review. Apply the existing linear chain through `k1a3c5e7f9b1` as documented in the [rollout runbook](zeaplay-subtask-v2-phase7-rollout.md). Legacy nullable values remain readable. The reward enrollment switch is not a kill switch for reconciliation of already enrolled records; disabling it affects future enrollment only.

## Release blockers

Credential material remains in tracked `backend/.env` and `frontend/.env`, including current HEAD and older commits. The redacted scan summary contains locations and classifications only. Validity/revocation was not tested. Rotate or revoke affected credentials using the installation's approved process, provide protected runtime configuration, remove private environment files from the reviewed release/index, and coordinate any history remediation. Rotation must account for storage access and existing Web Push subscriptions. This review did not change private configuration, rotate keys, rewrite Git history or alter the index.

TypeScript, repository lint, dependency-security and obsolete legacy regression failures remain release gates. Full application accessibility, target image builds, target-schema restore/recovery, sustained production-scale contention, external providers and installed end-to-end regressions are not certified. A successful Vite bundle or isolated accounting test does not close these gates.

## Recovery

Prefer a compatible forward repair. Preserve all new audit, ledger, interval, correction and notification records, the migration head, balances and media. Stop affected writers before switching artifacts. An older database dump or pre-V2 image cannot safely replace a system that has accepted new writes. Never use destructive Alembic downgrades, table truncation, global balance reconstruction or deletion of immutable history as rollback. Backup, restore, writer inventory, health observations and recovery commands are in the existing runbook and final checklist.
