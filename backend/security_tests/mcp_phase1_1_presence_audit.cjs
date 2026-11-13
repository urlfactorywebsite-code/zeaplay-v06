/* Execute exact presence authentication functions, never import/start server.js.
 * Uses the locally installed jsonwebtoken version satisfying presence package.json.
 * No Redis, database, sockets, environment secrets, or production configuration.
 */
'use strict';
require('./phase1_1_network_guard.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const { randomBytes, createHash } = require('node:crypto');
const repository = path.resolve(__dirname, '../..');
const frontendRequire = createRequire(path.join(repository, 'frontend/package.json'));
const jwt = frontendRequire('jsonwebtoken');
const version = frontendRequire('jsonwebtoken/package.json').version;
assert.equal(version, '9.0.2', 'Re-review probe compatibility before changing dependency version');
const source = fs.readFileSync(path.join(repository, 'presence-server/src/server.js'), 'utf8');
const start = source.indexOf('function extractToken(socket)');
const end = source.indexOf('async function publishPresenceEvent(', start);
assert.ok(start >= 0 && end > start, 'Authentication function boundaries must be reviewed');
const exactFunctions = source.slice(start, end);
assert.match(exactFunctions, /function authenticateSocket\(socket, next\)/);
assert.match(source, /io\.use\(authenticateSocket\)/);
const config = { jwtSecret: randomBytes(48).toString('hex'), jwtAlgorithm: 'HS256' };
const context = { jwt, config };
vm.runInNewContext(exactFunctions + '\nthis.auditAuthenticate = authenticateSocket;', context,
                   { timeout: 1000, filename: 'presence-auth-exact-source.js' });
assert.throws(() => require('node:net').connect(7211, '127.0.0.1'), /forbids network/);
assert.throws(() => fetch('http://127.0.0.1:7211'), /forbids network/);
const base = { sub: 'synthetic-audit-user', tenant_id: 'synthetic-audit-tenant',
               token_type: 'access', exp: Math.floor(Date.now() / 1000) + 300 };
const cases = [
  ['valid', base, true],
  ['missing-expiry', { ...base, exp: undefined }, true],
  ['missing-type', { ...base, token_type: undefined }, true],
  ['null-type', { ...base, token_type: null }, true],
  ['empty-type', { ...base, token_type: '' }, true],
  ['fractional-expiry', { ...base, exp: Date.now() / 1000 + 300.5 }, true],
  ['refresh-type', { ...base, token_type: 'refresh' }, false],
  ['expired', { ...base, exp: 1 }, false],
  ['expiry-now', { ...base, exp: Math.floor(Date.now() / 1000) }, false],
];
for (const [name, input, expectedAccepted] of cases) {
  const payload = Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
  const token = jwt.sign(payload, config.jwtSecret, { algorithm: config.jwtAlgorithm, noTimestamp: true });
  const socket = { handshake: { auth: { token }, headers: {} }, data: {} };
  let called = false;
  let accepted;
  context.auditAuthenticate(socket, error => { called = true; accepted = !error; });
  assert.equal(called, true);
  assert.equal(accepted, expectedAccepted, name);
  console.log(JSON.stringify({ probe: name, accepted }));
}
console.log(JSON.stringify({ source_sha256: createHash('sha256').update(exactFunctions).digest('hex'),
  dependency: 'jsonwebtoken@' + version, probes: cases.length, isolation_controls: 2,
  scope: 'Exact authentication functions only; complete presence service and Redis NOT RUN' }));
console.log('AUDIT_GATE ' + JSON.stringify({ criterion: 8, result: 'FAIL',
  evidence: 'Presence authenticateSocket accepts a signed JWT with no expiration.' }));
console.log('AUDIT_GATE ' + JSON.stringify({ criterion: 9, result: 'FAIL',
  evidence: 'Presence permits missing/null/empty type and fractional expiry; FastAPI rejects these profiles.' }));
process.exitCode = 2;
