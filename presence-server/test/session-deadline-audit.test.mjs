import assert from 'node:assert/strict';
import test from 'node:test';
import { createPresenceAuthenticator, enforcePresenceSession } from '../src/auth.js';

// No network or real credentials. The clock advances during authority responses
// to expose stale-success latency, rather than assuming instantaneous HTTP.
function fixture(start = 0) {
  const state = { clock: start, timers: [], closed: 0, handlers: {} };
  state.socket = { data: { presenceVerifiedAt: start, presenceCredential: 'synthetic' },
    on: (name, callback) => { state.handlers[name] = callback; }, use() {},
    disconnect: () => { state.closed++; state.handlers.disconnect?.(); } };
  state.options = { now: () => state.clock,
    schedule: (callback, delay) => { const timer = { callback, delay }; state.timers.push(timer); return timer; }, cancel() {} };
  return state;
}

test('a delayed 204 cannot shift the next poll beyond 15 seconds from the validation request', async () => {
  const state = fixture();
  enforcePresenceSession(state.socket, async () => { state.clock += 2999; return true; }, state.options);
  state.clock = 15000;
  await state.timers[0].callback();
  assert.equal(state.socket.data.presenceVerifiedAt, 15000);
  assert.equal(state.timers.at(-1).delay, 12001);
  assert.equal(state.closed, 0);
});

test('initial poll accounts for time already spent on admission validation', () => {
  const state = fixture();
  state.clock = 2999;
  enforcePresenceSession(state.socket, async () => true, state.options);
  assert.equal(state.timers[0].delay, 12001);
});

test('an overdue success cannot revive a suspended connection', async () => {
  const state = fixture();
  enforcePresenceSession(state.socket, async () => { state.clock += 18000; return true; }, state.options);
  state.clock = 15000;
  await state.timers[0].callback();
  assert.equal(state.closed, 1);
  assert.equal(state.socket.data.presenceCredential, undefined);
});

test('admission records request time and refuses a token expiring during authority validation', async () => {
  for (const expires of [102, 200]) {
    let clock = 100000;
    const payload = { sub: 'fixture', tenant_id: '00000000-0000-0000-0000-000000000001',
      sid: '00000000-0000-0000-0000-000000000002', jti: '00000000-0000-0000-0000-000000000003',
      auth_epoch: 0, iat: 99, exp: expires, token_type: 'presence', iss: 'zeaplay', aud: 'zeaplay-presence',
      roles: ['user'], scopes: ['presence'] };
    const authenticate = createPresenceAuthenticator({
      jwt: { verify: () => ({ payload, header: { alg: 'HS256', typ: 'JWT' } }) },
      secret: 'synthetic', algorithm: 'HS256', now: () => clock,
      validateSession: async () => { clock += 2999; return true; },
    });
    const socket = { data: {}, handshake: { auth: { token: 'synthetic' }, query: {}, headers: {} } };
    let error;
    await authenticate(socket, value => { error = value; });
    if (expires === 102) {
      assert.ok(error instanceof Error);
      assert.equal(socket.data.user, undefined);
    } else {
      assert.equal(error, undefined);
      assert.equal(socket.data.presenceVerifiedAt, 100000);
    }
  }
});
