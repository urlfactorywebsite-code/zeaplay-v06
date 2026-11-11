# Zea.Play V6.1.7

Application/package version: **6.1.7** (displayed as **V6.1.7**). Login, sidebar, product-update defaults, backup exports, API metadata, and source-built image labels use this release. Authored release-note content and database/reward policy versions remain intact.

Local ZeaPlay services use these ports:

| Service | Host port | Container port |
| --- | ---: | ---: |
| Frontend | 7300 | 80 |
| Backend API and task WebSocket | 7211 | 7211 |
| Presence and chat realtime | 7212 | 7212 |
| PostgreSQL | 7432 | 5432 |
| Redis | 7379 | 7379 |

Open **http://localhost:7300**. Start the existing local project with `docker compose -f docker-compose.yml up -d --build`.

Port-change verification and recovery notes: [docs/zeaplay-7000-ports.md](docs/zeaplay-7000-ports.md).

For a VPS source build, use the existing `docker-compose.prod.yml` + `docker-compose.github.yml` override; application images are tagged `v6.1.7`. The base production file retains the actual previously published image pins, including external workers. This version update does not publish replacement registry images.
