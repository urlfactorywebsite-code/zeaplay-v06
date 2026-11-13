import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createHmac } from 'node:crypto';
import net from 'node:net';
import { createPresenceAuthenticator, enforcePresenceExpiry } from '../src/auth.js';

// Run through run_mcp_phase1_2.py: fixture is ephemeral, never production config.
if (process.env.ZEA_PHASE1_ISOLATED !== 'memory-only' || !process.env.ZEA_PHASE12_INTEROP_FILE) {
  throw new Error('Use the isolated Phase 1.2 launcher');
}
const localRequire = createRequire(import.meta.url);
let jwt;
try { jwt = localRequire('jsonwebtoken'); }
catch { jwt = createRequire(new URL('../../frontend/package.json', import.meta.url))('jsonwebtoken'); }
const fixture = JSON.parse(readFileSync(process.env.ZEA_PHASE12_INTEROP_FILE, 'utf8'));
const original = jwt.decode(fixture.presence);
const authenticate = createPresenceAuthenticator({ jwt, secret: fixture.secret, algorithm: fixture.algorithm });

function rawToken(payload, header = { alg: 'HS256', typ: 'JWT' }, secret = fixture.secret) {
  const body = [header, payload].map(value => Buffer.from(JSON.stringify(value)).toString('base64url')).join('.');
  const algorithm = header.alg === 'HS512' ? 'sha512' : 'sha256';
  return body + '.' + createHmac(algorithm, secret).update(body).digest('base64url');
}
function invoke(token, placement = 'auth') {
  const socket = { data: {}, handshake: { auth: {}, query: {}, headers: {} } };
  if (placement === 'header') socket.handshake.headers.authorization = 'Bearer ' + token;
  else socket.handshake[placement].token = token;
  let calls = 0;
  let failure;
  authenticate(socket, error => { calls++; failure = error; });
  assert.equal(calls, 1);
  return { socket, accepted: !failure };
}
const omit = (...names) => Object.fromEntries(Object.entries(original).filter(([key]) => !names.includes(key)));

test('Python-issued presence token authenticates with exact user and tenant', () => {
  for (const placement of ['auth', 'query', 'header']) {
    const { socket, accepted } = invoke(fixture.presence, placement);
    assert.equal(accepted, true);
    assert.deepEqual(socket.data.user, { id: original.sub, tenantId: original.tenant_id,
      roles: original.roles, scopes: ['presence'] });
    assert.equal(socket.data.presenceExpiresAt, original.exp);
  }
});

test('Python-issued API and refresh tokens cannot authenticate presence', () => {
  assert.equal(invoke(fixture.access).accepted, false);
  assert.equal(invoke(fixture.refresh).accepted, false);
  // Even with the access signing key and a scope label, this remains an API token.
  assert.equal(invoke(rawToken({ ...original, token_type: 'access' })).accepted, false);
});

const badProfiles = [
  ['missing expiry', omit('exp')],
  ['expired expiry', { ...original, exp: 1 }],
  ['expiry boundary', { ...original, exp: Math.floor(Date.now() / 1000) }],
  ['string expiry', { ...original, exp: String(original.exp) }],
  ['boolean expiry', { ...original, exp: true }],
  ['null expiry', { ...original, exp: null }],
  ['fractional expiry', { ...original, exp: original.exp + 0.5 }],
  ['unsafe integer expiry', { ...original, exp: Number.MAX_SAFE_INTEGER + 1 }],
  ['missing type', omit('token_type')],
  ['null type', { ...original, token_type: null }],
  ['empty type', { ...original, token_type: '' }],
  ['refresh type', { ...original, token_type: 'refresh' }],
  ['wrong type casing', { ...original, token_type: 'PRESENCE' }],
  ['missing audience', omit('aud')],
  ['wrong audience', { ...original, aud: 'normal-api' }],
  ['array audience', { ...original, aud: ['zeaplay-presence', 'normal-api'] }],
  ['missing issuer', omit('iss')],
  ['wrong issuer', { ...original, iss: 'untrusted-issuer' }],
  ['missing issued-at', omit('iat')],
  ['future issued-at', { ...original, iat: original.exp }],
  ['string issued-at', { ...original, iat: String(original.iat) }],
  ['overlong lifetime', { ...original, exp: original.iat + 3601 }],
  ['missing subject', omit('sub')],
  ['empty subject', { ...original, sub: '' }],
  ['object subject', { ...original, sub: {} }],
  ['spaced subject', { ...original, sub: ' user ' }],
  ['conflicting identity alias', { ...original, user_id: 'another-user' }],
  ['missing tenant', omit('tenant_id')],
  ['default tenant fallback', { ...original, tenant_id: 'default' }],
  ['object tenant', { ...original, tenant_id: {} }],
  ['missing scopes', omit('scopes')],
  ['wrong scope', { ...original, scopes: ['tasks:read'] }],
  ['extra scope', { ...original, scopes: ['presence', 'tasks:read'] }],
  ['missing roles', omit('roles')],
  ['string roles', { ...original, roles: 'owner' }],
  ['unknown role', { ...original, roles: ['superadmin'] }],
  ['unexpected claim', { ...original, delegated_admin: true }],
  ['non-object payload', 'not-an-object'],
];
for (const [name, payload] of badProfiles) {
  test('rejects ' + name, () => {
    const { socket, accepted } = invoke(rawToken(payload));
    assert.equal(accepted, false);
    assert.equal(socket.data.user, undefined);
  });
}

test('rejects wrong signature, algorithm, header extensions and malformed tokens', () => {
  const tokens = [rawToken(original, undefined, 'synthetic-wrong-key'),
    rawToken(original, { alg: 'HS512', typ: 'JWT' }),
    rawToken(original, { alg: 'none', typ: 'JWT' }),
    rawToken(original, { alg: 'HS256', typ: 'JWT', crit: ['custom'] }),
    rawToken(original, { alg: 'HS256', typ: 'JWT', jku: 'https://invalid.example.test' }),
    rawToken(original, { alg: 'HS256', typ: 'other' }), '', 'malformed'];
  for (const token of tokens) assert.equal(invoke(token).accepted, false);
});

test('network/listener controls prevent touching any installed service', () => {
  assert.throws(() => net.connect(7211, '127.0.0.1'), /forbids network/);
  assert.throws(() => net.createServer().listen(0, '127.0.0.1'), /forbids network/);
  assert.throws(() => fetch('http://127.0.0.1:7211'), /forbids network/);
});

test('valid session admits packets then denies at expiry even if its timer is delayed', () => {
  const { socket } = invoke(fixture.presence);
  let clock = original.iat * 1000;
  let timer;
  let packet;
  let disconnected = 0;
  const handlers = {};
  socket.disconnect = () => { disconnected++; };
  socket.on = (name, handler) => { handlers[name] = handler; };
  socket.use = handler => { packet = handler; };
  const canceled = [];
  assert.equal(enforcePresenceExpiry(socket, { now: () => clock,
    schedule: (callback, delay) => { timer = { callback, delay }; return timer; },
    cancel: value => canceled.push(value) }), true);
  assert.equal(timer.delay, 3600000);
  let error;
  packet(['presence:ping'], value => { error = value; });
  assert.equal(error, undefined);
  clock = original.exp * 1000;
  packet(['presence:get'], value => { error = value; });
  assert.ok(error instanceof Error);
  assert.equal(disconnected, 1);
  handlers.disconnect();
  assert.deepEqual(canceled, [timer]);
});

test('expiry timer closes idle sockets and expired session setup refuses admission', () => {
  let disconnected = 0;
  let expire;
  const socket = { data: { presenceExpiresAt: 200 }, disconnect: () => { disconnected++; },
    on() {}, use() {} };
  assert.equal(enforcePresenceExpiry(socket, { now: () => 199000,
    schedule: callback => { expire = callback; return { unref() {} }; }, cancel() {} }), true);
  expire();
  assert.equal(disconnected, 1);
  assert.equal(enforcePresenceExpiry(socket, { now: () => 200000 }), false);
  assert.equal(disconnected, 2);
});

test('server registers the tested authenticator and expiry guard', () => {
  const source = readFileSync(new URL('../src/server.js', import.meta.url), 'utf8');
  assert.match(source, /createPresenceAuthenticator\(\{\s*jwt, secret: config.jwtSecret, algorithm: config.jwtAlgorithm/);
  assert.match(source, /io\.use\(authenticateSocket\)/);
  assert.match(source, /io\.on\('connection', async \(socket\) => \{\s*if \(!enforcePresenceExpiry\(socket\)\) return;/);
});
