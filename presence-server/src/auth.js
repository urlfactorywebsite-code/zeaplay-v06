// Presence has its own signed profile. API/refresh tokens are never substitutes.
export const PRESENCE_TOKEN_TYPE = 'presence';
export const PRESENCE_AUDIENCE = 'zeaplay-presence';
export const PRESENCE_ISSUER = 'zeaplay';
const CLAIMS = new Set(['sub', 'tenant_id', 'roles', 'scopes', 'token_type', 'iss', 'aud', 'iat', 'exp', 'sid', 'jti', 'auth_epoch']);
const ROLES = new Set(['user', 'manager', 'admin', 'owner']);
const TENANT_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function extractToken(socket) {
  const handshake = socket.handshake;
  const authToken = handshake.auth?.token;
  if (typeof authToken === 'string' && authToken.trim()) return authToken.trim();
  const queryToken = handshake.query?.token;
  if (typeof queryToken === 'string' && queryToken.trim()) return queryToken.trim();
  const header = handshake.headers?.authorization;
  if (typeof header === 'string') {
    const parts = header.trim().split(/\s+/);
    if (parts.length === 2 && parts[0].toLowerCase() === 'bearer') return parts[1];
  }
  return '';
}

export function createPresenceAuthenticator({ jwt, secret, algorithm, validateSession, now = Date.now }) {
  if (!secret || !algorithm || algorithm === 'none') throw new Error('Presence signing configuration required');
  if (typeof validateSession !== 'function') throw new Error('Presence session authority required');
  return async function authenticateSocket(socket, next) {
    try {
      const token = extractToken(socket);
      if (!token) throw new Error('Missing token');
      const seconds = Math.floor(now() / 1000);
      const decoded = jwt.verify(token, secret, {
        algorithms: [algorithm], issuer: PRESENCE_ISSUER, audience: PRESENCE_AUDIENCE,
        complete: true, clockTimestamp: seconds,
      });
      const payload = decoded.payload;
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)
          || Object.keys(payload).some(key => !CLAIMS.has(key))
          || Object.keys(decoded.header).some(key => !['alg', 'typ'].includes(key))
          || decoded.header.typ !== 'JWT'
          || payload.token_type !== PRESENCE_TOKEN_TYPE
          || payload.aud !== PRESENCE_AUDIENCE || payload.iss !== PRESENCE_ISSUER
          || !Number.isSafeInteger(payload.exp) || payload.exp <= seconds
          || !Number.isSafeInteger(payload.iat) || payload.iat < 0 || payload.iat > seconds
          || payload.exp <= payload.iat || payload.exp - payload.iat > 3600
          || typeof payload.sub !== 'string' || !payload.sub || payload.sub !== payload.sub.trim()
          || payload.sub.length > 36
          || typeof payload.tenant_id !== 'string' || !TENANT_UUID.test(payload.tenant_id)
          || typeof payload.sid !== 'string' || !TENANT_UUID.test(payload.sid)
          || typeof payload.jti !== 'string' || !TENANT_UUID.test(payload.jti)
          || !Number.isSafeInteger(payload.auth_epoch) || payload.auth_epoch < 0
          || !Array.isArray(payload.roles) || !payload.roles.length
          || payload.roles.some(role => !ROLES.has(role))
          || !Array.isArray(payload.scopes) || payload.scopes.length !== 1 || payload.scopes[0] !== 'presence') {
        throw new Error('Invalid presence profile');
      }
      const verificationStartedAt = now();
      if (await validateSession(token) !== true
          || now() - verificationStartedAt >= 18000
          || now() >= payload.exp * 1000) throw new Error('Invalid session');
      socket.data.user = { id: payload.sub, tenantId: payload.tenant_id.toLowerCase(),
                           roles: payload.roles, scopes: payload.scopes };
      socket.data.presenceExpiresAt = payload.exp;
      socket.data.presenceCredential = token;
      // A delayed 204 represents a decision made during the request, not at
      // response arrival. Do not extend its revocation window by HTTP latency.
      socket.data.presenceVerifiedAt = verificationStartedAt;
    } catch {
      next(new Error('Invalid presence authentication token'));
      return;
    }
    next();
  };
}

// Backend validates this presence-only JWT against PostgreSQL. This service
// receives no database credentials. Configure a trusted internal/TLS endpoint.
export function createSessionValidator({ url, fetcher = fetch }) {
  const endpoint = new URL(url);
  if (!['http:', 'https:'].includes(endpoint.protocol) || endpoint.username || endpoint.password
      || endpoint.search || endpoint.hash
      || !['/auth/presence/validate', '/api/auth/presence/validate'].includes(endpoint.pathname)) {
    throw new Error('Trusted presence session validation URL required');
  }
  return async token => {
    try {
      const response = await fetcher(endpoint.href, { method: 'POST', redirect: 'error',
        headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(3000) });
      // No response body or identity supplied by the caller is trusted.
      return response.status === 204;
    } catch { return false; }
  };
}

export function enforcePresenceSession(socket, validateSession,
  { now = Date.now, schedule = setTimeout, cancel = clearTimeout } = {}) {
  let stopped = false;
  let timer;
  socket.on('disconnect', () => {
    stopped = true;
    cancel(timer);
    delete socket.data.presenceCredential;
  });
  const check = async () => {
    const verificationStartedAt = now();
    let valid = false;
    try { valid = await validateSession(socket.data.presenceCredential); } catch { /* fail closed */ }
    if (stopped) return;
    if (valid !== true || now() - verificationStartedAt >= 18000) { socket.disconnect(true); return; }
    socket.data.presenceVerifiedAt = verificationStartedAt;
    timer = schedule(check, Math.max(0, verificationStartedAt + 15000 - now()));
    timer.unref?.();
  };
  timer = schedule(check, Math.max(0, socket.data.presenceVerifiedAt + 15000 - now()));
  timer.unref?.();
  socket.use((_packet, next) => {
    if (now() - socket.data.presenceVerifiedAt >= 18000) {
      next(new Error('Presence session verification overdue'));
      socket.disconnect(true);
    } else next();
  });
}

export function enforcePresenceExpiry(socket, { now = Date.now, schedule = setTimeout, cancel = clearTimeout } = {}) {
  const remaining = socket.data.presenceExpiresAt * 1000 - now();
  if (!Number.isFinite(remaining) || remaining <= 0) {
    socket.disconnect(true);
    return false;
  }
  const timer = schedule(() => socket.disconnect(true), remaining);
  timer.unref?.();
  socket.on('disconnect', () => cancel(timer));
  // A delayed timer/event loop must not admit packets after the signed expiry.
  socket.use((_packet, next) => {
    if (now() >= socket.data.presenceExpiresAt * 1000) {
      next(new Error('Presence credential expired'));
      socket.disconnect(true);
      return;
    }
    next();
  });
  return true;
}
