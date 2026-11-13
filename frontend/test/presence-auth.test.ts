import test from 'node:test';
import assert from 'node:assert/strict';
import type { Socket } from 'socket.io-client';
import { createPresenceConnection, presenceIdentity } from '../services/presenceConnection';

class SocketFixture {
    connected = false;
    disconnected = 0;
    handlers = new Map<string, Array<(...args: unknown[]) => void>>();
    on(name: string, handler: (...args: unknown[]) => void) {
        this.handlers.set(name, [...(this.handlers.get(name) ?? []), handler]);
        return this;
    }
    fire(name: string, ...args: unknown[]) {
        if (name === 'connect') this.connected = true;
        if (name === 'disconnect') this.connected = false;
        for (const handler of this.handlers.get(name) ?? []) handler(...args);
    }
    removeAllListeners() { this.handlers.clear(); return this; }
    disconnect() { this.disconnected++; this.connected = false; return this; }
}

function harness() {
    let clock = 1_800_000_000_000;
    let nextTimer = 0;
    let current = true;
    let requests = 0;
    const timers = new Map<number, { at: number; callback: () => void }>();
    const sockets: SocketFixture[] = [];
    const sentTokens: string[] = [];
    const states: string[] = [];
    const credential = () => ({ access_token: `presence-only-${requests}`, subject: 'member',
                               expires_at: new Date(clock + 3600000).toISOString() });
    const provider = { get: async () => credential() };
    const connection = createPresenceConnection({
        subject: 'member', isCurrent: () => current,
        getCredential: async () => { requests++; return provider.get(); },
        openSocket: token => {
            sentTokens.push(token);
            const socket = new SocketFixture();
            sockets.push(socket);
            return socket as unknown as Socket;
        },
        onSocket() {},
        onState: state => states.push(state), now: () => clock,
        schedule: (callback, delay) => {
            timers.set(++nextTimer, { at: clock + delay, callback });
            return nextTimer as unknown as ReturnType<typeof setTimeout>;
        },
        cancel: timer => { timers.delete(timer as unknown as number); },
    });
    return { connection, sockets, sentTokens, states, timers, provider, credential,
        requests: () => requests, invalidate: () => { current = false; },
        advance: async (milliseconds: number) => {
            clock += milliseconds;
            for (const [id, timer] of [...timers]) {
                if (timer.at <= clock) { timers.delete(id); timer.callback(); }
            }
            await new Promise<void>(resolve => setImmediate(resolve));
        } };
}

test('connects using only the dedicated credential and retains connected state', async () => {
    const h = harness();
    await h.connection.start();
    assert.deepEqual(h.sentTokens, ['presence-only-1']);
    h.sockets[0].fire('connect');
    assert.deepEqual(h.states, ['connecting', 'connected']);
    h.connection.stop();
    assert.equal(h.sockets[0].disconnected, 1);
    assert.equal(h.timers.size, 0);
});

test('renews before expiry and removes the old socket listeners', async () => {
    const h = harness();
    await h.connection.start();
    h.sockets[0].fire('connect');
    await h.advance(3570000);
    assert.equal(h.requests(), 2);
    assert.deepEqual(h.sentTokens, ['presence-only-1', 'presence-only-2']);
    assert.equal(h.sockets[0].disconnected, 1);
    assert.equal(h.sockets[0].handlers.size, 0);
    h.sockets[1].fire('connect');
    assert.equal(h.states.at(-1), 'connected');
    h.connection.stop();
});

test('logout while credential request is pending never creates a socket', async () => {
    const h = harness();
    let resolve!: (value: ReturnType<typeof h.credential>) => void;
    h.provider.get = () => new Promise(done => { resolve = done; });
    const pending = h.connection.start();
    h.connection.stop();
    resolve(h.credential());
    await pending;
    assert.equal(h.sockets.length, 0);
    assert.equal(h.timers.size, 0);
});

test('account or tenant change during acquisition discards the response', async () => {
    const h = harness();
    let resolve!: (value: ReturnType<typeof h.credential>) => void;
    h.provider.get = () => new Promise(done => { resolve = done; });
    const pending = h.connection.start();
    h.invalidate();
    resolve(h.credential());
    await pending;
    assert.equal(h.sockets.length, 0);
    h.connection.stop();
});

test('failed credential acquisition retries after cooldown without API-token fallback', async () => {
    const h = harness();
    h.provider.get = async () => { throw new Error('Denied'); };
    await h.connection.start();
    h.connection.reconnect();
    assert.equal(h.requests(), 1);
    assert.deepEqual(h.sentTokens, []);
    assert.equal(h.states.at(-1), 'offline');
    h.provider.get = async () => h.credential();
    await h.advance(5000);
    assert.equal(h.requests(), 2);
    assert.equal(h.sockets.length, 1);
    h.connection.stop();
});

test('wrong subject or expired credential cannot open a connection', async () => {
    for (const change of [{ subject: 'other' }, { expires_at: new Date(0).toISOString() },
                          { expires_at: 'invalid' }, { access_token: '' }]) {
        const h = harness();
        h.provider.get = async () => ({ ...h.credential(), ...change });
        await h.connection.start();
        assert.equal(h.sockets.length, 0);
        assert.equal(h.states.at(-1), 'offline');
        h.connection.stop();
    }
});

test('disconnect and connection errors reacquire credentials instead of replaying expired ones', async () => {
    for (const event of ['disconnect', 'connect_error']) {
        const h = harness();
        await h.connection.start();
        h.sockets[0].fire(event);
        assert.equal(h.states.at(-1), 'offline');
        await h.advance(5000);
        assert.equal(h.requests(), 2);
        assert.equal(h.sockets[0].disconnected, 1);
        h.connection.stop();
    }
});

test('stopping prevents scheduled renewal and stale socket state callbacks', async () => {
    const h = harness();
    await h.connection.start();
    h.connection.stop();
    const states = [...h.states];
    h.sockets[0].fire('connect');
    await h.advance(3600000);
    assert.equal(h.requests(), 1);
    assert.deepEqual(h.states, states);
    assert.equal(h.timers.size, 0);
});

test('identity survives ordinary API refresh but detects logout, user and tenant changes', () => {
    const token = (sub: string, tenant_id: string, exp: number, sid = 'session-a', auth_epoch = 0) =>
        `header.${btoa(JSON.stringify({ sub, tenant_id, exp, sid, auth_epoch }))}.signature`;
    const initial = presenceIdentity(token('member', 'tenant-a', 1));
    assert.equal(initial, presenceIdentity(token('member', 'tenant-a', 2)));
    assert.notEqual(initial, presenceIdentity(token('member', 'tenant-b', 2)));
    assert.notEqual(initial, presenceIdentity(token('another', 'tenant-a', 2)));
    assert.notEqual(initial, presenceIdentity(token('member', 'tenant-a', 2, 'session-b')));
    assert.notEqual(initial, presenceIdentity(token('member', 'tenant-a', 2, 'session-a', 1)));
    assert.equal(presenceIdentity(null), null);
    assert.equal(presenceIdentity('malformed'), null);
});
