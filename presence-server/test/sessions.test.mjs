import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createHmac } from 'node:crypto';
import net from 'node:net';
import { createPresenceAuthenticator, enforcePresenceExpiry, createSessionValidator, enforcePresenceSession } from '../src/auth.js';

// Fresh synthetic Python-issued fixtures only; no installed services.
if (!process.env.ZEA_PHASE13_ISOLATED || !process.env.ZEA_PHASE13_INTEROP) {
  throw new Error('Use run_mcp_phase1_3.py');
}
const localRequire = createRequire(import.meta.url);
let jwt;
try { jwt = localRequire('jsonwebtoken'); }
catch { jwt = createRequire(new URL('../../frontend/package.json', import.meta.url))('jsonwebtoken'); }
const fixture = JSON.parse(readFileSync(process.env.ZEA_PHASE13_INTEROP, 'utf8'));
const original = jwt.decode(fixture.presence);
const authenticate = createPresenceAuthenticator({ jwt, secret: fixture.secret, algorithm: "HS256", validateSession: async () => true });

function rawToken(payload, header = { alg: 'HS256', typ: 'JWT' }, secret = fixture.secret) {
  const body = [header, payload].map(value => Buffer.from(JSON.stringify(value)).toString('base64url')).join('.');
  const algorithm = header.alg === 'HS512' ? 'sha512' : 'sha256';
  return body + '.' + createHmac(algorithm, secret).update(body).digest('base64url');
}
async function invoke(token, placement = 'auth') {
  const socket = { data: {}, handshake: { auth: {}, query: {}, headers: {} } };
  if (placement === 'header') socket.handshake.headers.authorization = 'Bearer ' + token;
  else socket.handshake[placement].token = token;
  let calls = 0;
  let failure;
  await authenticate(socket, error => { calls++; failure = error; });
  assert.equal(calls, 1);
  return { socket, accepted: !failure };
}
const omit = (...names) => Object.fromEntries(Object.entries(original).filter(([key]) => !names.includes(key)));

test('Python-issued presence token authenticates with exact user and tenant', async () => {
  for (const placement of ['auth', 'query', 'header']) {
    const { socket, accepted } = await invoke(fixture.presence, placement);
    assert.equal(accepted, true);
    assert.deepEqual(socket.data.user, { id: original.sub, tenantId: original.tenant_id,
      roles: original.roles, scopes: ['presence'] });
    assert.equal(socket.data.presenceExpiresAt, original.exp);
  }
});

test('Python-issued API and refresh tokens cannot authenticate presence', async () => {
  assert.equal((await invoke(fixture.access)).accepted, false);
  assert.equal((await invoke(fixture.refresh)).accepted, false);
  // Even with the access signing key and a scope label, this remains an API token.
  assert.equal((await invoke(rawToken({ ...original, token_type: 'access' }))).accepted, false);
});

const badProfiles = [
  ['missing session', omit('sid')],
  ['missing jti', omit('jti')],
  ['missing epoch', omit('auth_epoch')],
  ['boolean epoch', {...original, auth_epoch:true}],
  ['negative epoch', {...original, auth_epoch:-1}],
  ['bad session', {...original, sid:'legacy'}],
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
  test('rejects ' + name, async () => {
    const { socket, accepted } = await invoke(rawToken(payload));
    assert.equal(accepted, false);
    assert.equal(socket.data.user, undefined);
  });
}

test('rejects wrong signature, algorithm, header extensions and malformed tokens', async () => {
  const tokens = [rawToken(original, undefined, 'synthetic-wrong-key'),
    rawToken(original, { alg: 'HS512', typ: 'JWT' }),
    rawToken(original, { alg: 'none', typ: 'JWT' }),
    rawToken(original, { alg: 'HS256', typ: 'JWT', crit: ['custom'] }),
    rawToken(original, { alg: 'HS256', typ: 'JWT', jku: 'https://invalid.example.test' }),
    rawToken(original, { alg: 'HS256', typ: 'other' }), '', 'malformed'];
  for (const token of tokens) assert.equal((await invoke(token)).accepted, false);
});

test('network/listener controls prevent touching any installed service', async () => {
  assert.throws(() => net.connect(7211, '127.0.0.1'), /forbids network/);
  assert.throws(() => net.createServer().listen(0, '127.0.0.1'), /forbids network/);
  assert.throws(() => fetch('http://127.0.0.1:7211'), /forbids network/);
});

test('valid session admits packets then denies at expiry even if its timer is delayed', async () => {
  const { socket } = await invoke(fixture.presence);
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

test('expiry timer closes idle sockets and expired session setup refuses admission', async () => {
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

test('server registers the tested authenticator and expiry guard', async () => {
  const source = readFileSync(new URL('../src/server.js', import.meta.url), 'utf8');
  assert.match(source, /createPresenceAuthenticator\(\{\s*validateSession,\s*jwt, secret: config.jwtSecret, algorithm: config.jwtAlgorithm/);
  assert.match(source, /io\.use\(authenticateSocket\)/);
  assert.match(source, /io\.on\('connection', async \(socket\) => \{\s*if \(!enforcePresenceExpiry\(socket\)\) return;/);
});


test('missing authority config fails closed', () => {
  assert.throws(() => createPresenceAuthenticator({jwt, secret: fixture.secret, algorithm:'HS256'}));
  assert.throws(() => createSessionValidator({url:''}));
  assert.throws(() => createSessionValidator({url:'https://backend.test/redirect?token=bad'}));
});

test('remote denial/outage prevents attaching socket identity', async () => {
  for (const validateSession of [async () => false, async () => {throw new Error('offline');}]) {
    const middleware = createPresenceAuthenticator({jwt, secret:fixture.secret, algorithm:'HS256', validateSession});
    const socket = {data:{},handshake:{auth:{token:fixture.presence},query:{},headers:{}}};
    let error;
    await middleware(socket, value => {error=value;});
    assert.ok(error instanceof Error);
    assert.equal(socket.data.user, undefined);
  }
});

test('authority client checks exact status and denies redirects/network failure', async () => {
  let calls=0;
  const check=createSessionValidator({url:'https://backend.test/auth/presence/validate',fetcher:async (url, options) => {
    calls++;
    assert.equal(url,'https://backend.test/auth/presence/validate');
    assert.equal(options.method,'POST');
    assert.equal(options.redirect,'error');
    assert.equal(options.headers.Authorization,'Bearer synthetic-credential');
    assert.ok(options.signal instanceof AbortSignal);
    return {status:204};
  }});
  assert.equal(await check('synthetic-credential'),true);
  assert.equal(calls,1);
  for (const status of [200,301,401,403,500,503]) {
    assert.equal(await createSessionValidator({url:'http://backend:7211/auth/presence/validate',fetcher:async()=>({status})})('x'),false);
  }
  assert.equal(await createSessionValidator({url:'http://backend:7211/auth/presence/validate',fetcher:async()=>{throw new Error('timeout');}})('x'),false);
});

test('revocation poll closes established connection and cancels secrets/timer', async () => {
  let clock=1000, disconnected=0, callback, packet, cleanup, delay;
  const canceled=[];
  const socket={data:{presenceCredential:fixture.presence,presenceVerifiedAt:clock},
    on:(event,handler)=>{if(event==='disconnect') cleanup=handler;},use:handler=>{packet=handler;},
    disconnect:()=>{disconnected++;cleanup();}};
  let allowed=true;
  enforcePresenceSession(socket,async token=>{assert.equal(token,fixture.presence);return allowed;},
    {now:()=>clock,schedule:(work,ms)=>{callback=work;delay=ms;return 42;},cancel:value=>canceled.push(value)});
  assert.equal(delay,15000);
  clock+=15000;await callback();assert.equal(disconnected,0);
  allowed=false;clock+=15000;await callback();
  assert.equal(disconnected,1);assert.equal(socket.data.presenceCredential,undefined);assert.deepEqual(canceled,[42]);
  assert.equal(typeof packet,'function');
});

test('late revalidation cannot admit packets beyond the 18 second deadline', () => {
  let disconnected=0, packet, error;
  const socket={data:{presenceVerifiedAt:0},on(){},use:handler=>{packet=handler;},disconnect:()=>{disconnected++;}};
  enforcePresenceSession(socket,async()=>true,{now:()=>18000,schedule:()=>42,cancel(){}});
  packet([],value=>{error=value;});assert.ok(error instanceof Error);assert.equal(disconnected,1);
});
