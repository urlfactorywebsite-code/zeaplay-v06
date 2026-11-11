# ZeaPlay 7000-series port migration

Completed for the local `zeaplay_v1` installation on 3 November 2026.

| Service | Previous host port | Current host port | Current container listener |
| --- | ---: | ---: | ---: |
| Frontend | 6300 | **7300** | 80 |
| Backend API and task WebSocket | 6211 | **7211** | 7211 |
| Presence/chat Socket.IO | 6212 | **7212** | 7212 |
| PostgreSQL | 6432 | **7432** | 5432 |
| Redis | 6379 | **7379** | 7379 |

Open **http://localhost:7300**. The browser sees a new origin, so sign in again there. Browser-local preferences and notification permissions belong to their origin; existing server data, accounts and notification preferences were preserved. Grant browser notification permission only through the existing user action if needed.

## Scope and changed files

The scan covered application/backend/frontend/presence source, Docker/Compose, private local endpoint configuration, templates, operational commands, browser-served assets and stored URL references. Old frontend port 6200 in production defaults was also aligned to 7300, and obsolete backend port 8000 URL fallbacks/documentation were aligned to 7211.

| Area | Files |
| --- | --- |
| Container topology | `docker-compose.yml`, `docker-compose.prod.yml`, `docker-compose.github.yml`, `backend/Dockerfile`, `presence-server/Dockerfile` |
| Backend/CORS | `backend/app/config.py`, `backend/app/main.py` |
| Frontend proxies/defaults | `frontend/vite.config.ts`, `frontend/nginx.conf`, `frontend/public/runtime-config.js`, `frontend/presenceClient.js`, `frontend/hooks/usePresence.ts`, `frontend/hooks/useTicketChat.ts` |
| Realtime/Redis | `presence-server/src/server.js`, Redis commands/health checks and Redis URLs in Compose/templates |
| Local/private configuration | Only port-bearing CORS/proxy/presence values in `backend/.env` and `frontend/.env.local`; credential and database settings were verified unchanged |
| Production example | `.env.production.example`; domain-based public URLs retained |
| Operations/documentation | `scripts/deploy-vps-github.sh`, `benchmarks/ab_commands.txt`, `benchmarks/k6_tasks_list.js`, project/backend/frontend/presence READMEs, `WEBSOCKET_FIXES.md`, current health command in the Phase 7 rollout runbook |

Historical reports, archived test logs, checksums and disposable test-server port allocations retain their recorded values. Numbers representing points, colors and clock-test inputs were not treated as network ports. New notes on historical reports point to this current mapping.

PostgreSQL keeps its standard internal listener on 5432 and Nginx keeps 80. Redis's actual listener, client URLs and health checks now use 7379. The upstream Redis image can still advertise 6379 as image `EXPOSE` metadata; that is not a listener or published host binding. Production templates continue to keep PostgreSQL/Redis unpublished where they were previously internal-only.

## Data and configuration safeguards

The destination ports were checked available before activation. The local project's labels and workspace were verified. Application writers were paused for the cutover; a protected custom-format PostgreSQL backup and validated Redis RDB snapshot were saved outside the repository. Configuration snapshots were retained privately for recovery.

PostgreSQL's existing named volume and Redis's existing anonymous data volume were reused. Fingerprints of all **85 database tables** matched exactly after storage recreation and before application writers resumed. No migration, reward recalculation, record deletion, volume deletion, database-major-version switch, credential rotation or external database change was performed.

Only this project's local containers were rebuilt/recreated. Paradise's application/database container IDs, images and start times remained unchanged. No remote VPS deployment script was executed.

## Executed verification

| Check | Result |
| --- | --- |
| Development Compose | PASS: all five expected published mappings |
| Production and production-plus-source Compose | PASS: configuration validation with synthetic example environment; no remote deployment |
| Backend, frontend and presence image builds | PASS; final backend/frontend build includes the last fallback changes |
| Existing frontend unit suite | **81 PASS**, zero failures/skips |
| Changed backend Python / presence JavaScript syntax | PASS |
| VPS deployment script syntax | PASS with `bash -n`; script not executed |
| Frontend, API, presence and proxied API health | HTTP **200** on the new ports |
| Authenticated direct/proxied API reads | PASS for auth, activity, inbox and task page |
| CORS preflight from `http://localhost:7300` | PASS for activity and push subscription |
| Native backend task WebSocket and frontend WebSocket proxy | Authenticated `activity.watching` acknowledgements PASS |
| Socket.IO presence | Authenticated connection and Redis-backed presence acknowledgement PASS |
| Redis | Host 7379 PONG; backend Redis client ping PASS and configured port 7379 |
| PostgreSQL | Published 7432 protocol handshake PASS; internal database fingerprints preserved |
| Served frontend assets/runtime config/service worker | Five local assets checked; no old project-port URLs, new API/presence URLs found |
| Stored configuration URLs | Two configuration URL fields checked; no old project-port records |
| Stored local URLs across the database | **438 text/JSON fields** checked read-only; no old local project-port URLs |
| Old host ports | 6300, 6211, 6212, 6432 and 6379 closed |
| Other projects | Container IDs/images/start times unchanged |

This is port-migration verification, not a replacement for the broader V2 production-readiness/security assessment. Full TypeScript, the entire backend suite, actual OS/provider push delivery and remote prebuilt worker/image compatibility were not newly certified by this change. The already-open production release gates remain separate.

Sanitized results and the changed-file manifest are in `docs/verification/zeaplay-7000-ports/`. Tokens, credentials, private configuration snapshots and backups are excluded.

## Operation and recovery

The existing local topology is still started with:

```powershell
docker compose -f docker-compose.yml up -d --build
```

Source-build deployment configuration uses the updated ports, Redis health check and backend listener. Remote reverse proxies/firewall rules outside this repository must be reviewed against the new upstream ports before any subsequently authorized remote rollout. Public domain names and external service endpoints were retained.

The protected task directory is referenced by `$env:TEMP\zea-ports-7000-current.txt`. It contains the before-configuration snapshots, database dump/checksum, Redis snapshot and private operator logs. Retain those files privately; do not commit or publish them.

For a port rollback, restore only the affected port configuration from those snapshots, rebuild the application images and recreate this project's containers using the **same data volumes**. Never use `down -v`, renew anonymous volumes, downgrade PostgreSQL, reset balances or overwrite post-cutover data with the old dump. Restore a backup into a separate database first if disaster recovery is required. No rollback was needed or executed.
