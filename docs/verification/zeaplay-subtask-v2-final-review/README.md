# Final review evidence — 3 November 2026

These are source/disposable verification records. **Overall production disposition: NO-GO.** See the [acceptance matrix](../../zeaplay-subtask-v2-final-acceptance.md), [release notes](../../zeaplay-subtask-v2-release-notes.md) and [deployment checklist](../../zeaplay-subtask-v2-deployment-checklist.md).

## Evidence inventory

| Artifact | Meaning |
| --- | --- |
| `results.json` | Fresh executed counts, failures/skips, dependency and quality gates; explicitly scoped earlier evidence and NOT RUN operations |
| `*.xml.gz`, `*.log.gz` | Gzipped UTF-8 JUnit and execution logs; pre-repair failures retained separately from final passing runs |
| `source-sha256.json`, `source-parity.json` | Final 466 code files compared byte-for-byte to the owned fixture, no mismatches; reviewed file hashes. No environment files or runtime data are included. |
| `bounded-final-review.patch`, `delta-summary.json` | Final source delta against the preceding Phase 7 fixture, rather than the whole dirty checkout; includes three focused regression test files |
| `configuration-sha256.json` | Compose/Dockerfile/dependency-manifest hashes; these files were not edited in this review |
| `profiles-and-query-plans.json` | Synthetic SQL plans, query counts, memory/history/workload/fanout and accounting test properties |
| `secret-assessment.json` | Redacted, allowlisted metadata/classifications only. Four tracked environment credential-material findings; no raw Match/Secret, provider calls, key validity or revocation proof. |
| `npm-audit-current.json.gz`, `backend-dependency-audit-current.json.gz` | Fresh frontend lock and 90-package installed backend fixture-closure scans; not deployed image scans |
| `typescript-comparison.json`, `changed-lint-comparison.json` | Unchanged 112 TypeScript errors, focused lint comparison; broad Ruff count is in `results.json` |
| `review_pytest.py` | Runner used in the owned sanitized fixture, hardened afterward to refuse an unowned root; refusal and owned collection were executed |
| `cleanup.json` | Exact owned container cleanup and unchanged installed-container observations |

Runs overlap: the 11-case final API-contract run includes nine integrated cases already present in the 302-case PostgreSQL cohort. Final target/cache tests repeat across database backends. The intentional offline-only skip is separately executed with a stopped real owned Redis server. Do not add these numbers as a count of unique tested behaviors.

The initial `before-cache` Kanban fixture used the wrong column ID. `before-kanban` is the corrected independent disclosure reproduction. The other initial cache failures reproduced real HTTP/cache defects. An intermediate real-offline test expected only ConnectionError; Docker's stopped port returned Redis TimeoutError. The final test correctly accepts RedisError before exercising real HTTP behavior. Those harness corrections are not repaired production defects.

The 302-case cohort precedes the last two OpenAPI-only decorator flags. After those flags, the affected two contract tests and nine real-JWT integrated cases pass against PostgreSQL. All other product code matches the full feature-cohort source. Earlier Phase 7 browser, Linux/Python 3.11 and obsolete legacy-module results remain in [their own directory](../zeaplay-subtask-v2-phase7/); they were not silently relabelled as fresh final-review execution.

## Safe reproduction

Use a new `F:\Codex-Verification\zeaplay-final-review-<unique-id>` directory with `OWNED-VERIFICATION.txt` at its root, a sanitized copy of actual `backend/` and `frontend/`, an empty root `assets/`, and this runner beside `backend/`. Exclude `.env*`, private configuration, databases, backups, uploads/media, bytecode, dependency folders and build outputs. Legacy tests create/delete relative database files, so do not run them from an installed checkout. The runner refuses other directory names and missing ownership markers, replaces application DB/secrets with synthetic test configuration, and blocks outbound sockets except the two local fixture endpoints and standard-library socket-pair plumbing.

Create only explicitly owned local PostgreSQL 15 and Redis 7 containers with unique names/labels and fixture ports. PostgreSQL must use synthetic user `phase1`, database `zea_subtask_phase1`, localhost port 15467; Redis uses localhost port 16379, DB 15. Never substitute installed service URLs. The database fixtures allocate unique schemas and clean them up. Keep all output outside private data directories.

From that owned copy:

```powershell
$env:ZEA_TASK_AUDIT_TEST_URL='postgresql+psycopg://phase1@127.0.0.1:15467/zea_subtask_phase1'
python -B review_pytest.py backend/tests/test_phase7_system.py backend/tests/test_task_audit_foundation.py backend/tests/test_subtask_workflow.py backend/tests/test_subtask_reward_calculation.py backend/tests/test_subtask_rewards.py backend/tests/test_subtask_reward_audit.py backend/tests/test_task_activity.py backend/tests/test_task_activity_audit.py backend/tests/test_task_information.py backend/tests/test_task_information_review.py backend/tests/test_task_tabs_review.py backend/tests/test_workload_notifications.py backend/tests/test_workload_notification_review.py backend/tests/test_phase7_performance.py backend/tests/test_subtask_schema_rehearsal.py --junitxml=pg-final-regression.xml
python -B review_pytest.py backend/tests/test_final_readiness.py backend/tests/test_final_migration_gate.py backend/tests/test_phase7_migrations.py --junitxml=final-targets.xml
python -B review_pytest.py backend/tests/test_final_api_contracts.py backend/tests/test_phase7_system.py --junitxml=api-contract-final.xml
Remove-Item Env:ZEA_TASK_AUDIT_TEST_URL
$env:ZEA_PHASE7_REDIS_URL='redis://127.0.0.1:16379/15'
python -B review_pytest.py backend/tests/test_final_readiness.py backend/tests/test_phase7_realtime.py --junitxml=sqlite-cache-realtime-final.xml
python -B review_pytest.py backend/tests/test_settings_security.py backend/tests/test_navigation_policy.py backend/tests/test_navigation_readiness.py backend/tests/test_navigation_socket_auth.py backend/tests/test_navigation_sockets.py backend/tests/test_employee_avatar_profile.py backend/tests/test_backup_manager.py backend/tests/test_api_settings_migration.py backend/tests/test_time_bonus.py backend/tests/test_task_audit_migration.py --junitxml=sqlite-existing-regression.xml
```

For the separate real-server outage case, verify the Redis container's exact ID, `zea.phase=final-review` label and unique name before stopping it. Do not run recovery tests concurrently. Set `ZEA_FINAL_OFFLINE_REDIS_URL=redis://127.0.0.1:16379/15`, execute only `test_final_readiness.py::test_stopped_real_redis_preserves_http_mutation_and_read`, and restart the exact owned Redis in `finally`. Remove the environment flag afterward. This is fixture-only orchestration, not an installed Redis outage instruction.

From the sanitized frontend with the matching reviewed dependency fixture:

```powershell
npm test
npm run build
npx --no-install tsc --noEmit
npm audit --json
```

Ruff was run explicitly over `backend` and the changed small files; broad diagnostics are not suppressed. Backend auditing uses the preceding report's `dependency_scope.py` to pin the installed requirements closure, then isolated pip-audit 2.10.0 with `--no-deps --disable-pip -r <fixture-versions-file> -f json`. The initial global interpreter lacked pip-audit; the successful recorded scan used a separate tool venv, without changing app dependencies. Git scanning used Gitleaks 8.24.2 with `--redact`, all ten reachable commits and network-disabled read-only mounts. Raw scanner reports remain outside public evidence; only allowlisted metadata was archived.

No source/disposable check executes the rollout runbook. Production backup/restore, private environment handling, images/providers, installed E2E, sustained load, pilot and actual recovery remain separate release gates.
