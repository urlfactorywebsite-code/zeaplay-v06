# ZeaPlay Presence Server

Socket.IO realtime service for ZeaPlay presence and chat fanout.

## Environment

- `PRESENCE_PORT`: HTTP/Socket.IO port, default `7212`
- `PRESENCE_REDIS_URL`: Redis connection URL, default `redis://localhost:7379`
- `PRESENCE_JWT_SECRET`: JWT access-token secret, must match `VEE_JWT_SECRET_KEY`
- `PRESENCE_JWT_ALGORITHM`: JWT algorithm, default `HS256`
- `PRESENCE_EVENTS_CHANNEL`: Redis pub/sub channel, default `presence:events`

## Socket.IO Events

Clients authenticate with `auth: { token }`, using the credential returned by
authenticated `GET /auth/presence-token`. Normal API access and refresh tokens
are rejected. The JSON envelope still uses `access_token` and bearer transport;
the signed token is a distinct presence profile:

- `token_type: presence`, `iss: zeaplay`, `aud: zeaplay-presence`.
- Required string `sub`, UUID `tenant_id`, known `roles`, and `scopes: [presence]`.
- Required integer `iat`/`exp`, at most one hour apart, with no clock tolerance.
- Configured algorithm/signature verification; no typeless, nonexpiring,
  unexpected-claim or default-tenant fallback.

Sockets disconnect at credential expiry. The frontend reacquires a credential
30 seconds beforehand and on reconnect; it never substitutes its API token.
Keep backend/presence clocks synchronized. Deploy the updated backend issuer,
presence verifier and frontend together; older presence clients need to reload.
Signing keys and configured maximum token lifetimes are unchanged; the new
absolute session expiry also bounds renewal (see Phase 1.3 below).

Phase 1.3 also requires UUID `sid`/`jti` and nonnegative integer `auth_epoch`.
Set `PRESENCE_SESSION_VALIDATION_URL` to the trusted backend's
`/auth/presence/validate` endpoint (or `/api/auth/presence/validate` when the proxy
preserves that prefix). This configuration is mandatory; there is no fallback.
Use TLS between hosts or a private container network, never an untrusted HTTP
hop. The URL cannot contain credentials/query parameters; redirects are denied.

Admission calls the backend with the presence credential in the Authorization
header. PostgreSQL user/session state is authoritative; Node receives no database
credentials. Each connected socket revalidates every 15 seconds with a 3-second
request timeout and closes on denial/outage. The target revocation latency is at
most 18 seconds under a responsive event loop; incoming packets are also denied
if verification is overdue. Expiry still closes idle connections. Runtime pauses
can delay wall-clock disconnects; this is not a hard real-time guarantee.

Deploy the migration and all backend/presence readers together with the updated
frontend. Legacy tokens require fresh login. See
[Phase 1.3 session revocation](../docs/mcp/PHASE_1_3_SESSION_REVOCATION.md) for
isolation evidence, retention, rollout and rollback limitations.

Presence:
- `presence:get` ack: `{ ok: true, users: [] }`
- `presence:ping`
- emits `presence:online`, `presence:offline`, `user_online`, `user_offline`

Chat:
- `chat:join` ack: `{ ok: true, history: [] }`
- `chat:leave`
- `chat:message` ack: `{ ok: true, message }`
- `chat:typing`
- `chat:reaction`
- `chat:space`

Health endpoint: `GET /health`.
