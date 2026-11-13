import assert from 'node:assert/strict';
import test, { after, beforeEach } from 'node:test';
import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import api, { http } from '../services/mockApi';
import { storeTokens, getAccessToken, getRefreshToken } from '../services/tokenStorage';

// Component integration: real API methods, Axios interceptors and token storage;
// synthetic transport only. The command also installs the network-denial guard.
const savedDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
const values = new Map<string, string>();
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => { values.set(key, value); },
  removeItem: (key: string) => { values.delete(key); },
  key: (index: number) => [...values.keys()][index] ?? null,
  get length() { return values.size; },
} });
const originalHttp = http.defaults.adapter, originalAxios = axios.defaults.adapter;
after(() => {
  http.defaults.adapter = originalHttp; axios.defaults.adapter = originalAxios;
  if (savedDescriptor) Object.defineProperty(globalThis, 'localStorage', savedDescriptor);
  else Reflect.deleteProperty(globalThis, 'localStorage');
});
beforeEach(() => values.clear());
function pair(number: number, sid = 'same-session') {
  const token = (kind: string) => `header.${Buffer.from(JSON.stringify({
    sub: 'user', tenant_id: 'tenant', sid, auth_epoch: 0, jti: `${kind}-${number}`,
  })).toString('base64url')}.signature`;
  return { access_token: token('access'), refresh_token: token('refresh') };
}
const save = (tokens: ReturnType<typeof pair>) => storeTokens(tokens.access_token, tokens.refresh_token);
function response(config: InternalAxiosRequestConfig, data: unknown, status = 200) {
  return { config, data, status, statusText: String(status), headers: {} };
}
function unauthorized(config: InternalAxiosRequestConfig): never {
  throw new AxiosError('Synthetic unauthorized', 'ERR_BAD_REQUEST', config, undefined, response(config, {}, 401));
}
function transport(handler: (config: InternalAxiosRequestConfig) => Promise<ReturnType<typeof response>>) {
  http.defaults.adapter = handler; axios.defaults.adapter = handler;
}

test('existing login envelope stores both credentials through the real API method', async () => {
  const tokens = pair(1);
  transport(async config => {
    assert.equal(config.url, '/auth/login');
    assert.deepEqual(JSON.parse(config.data), { email: 'fixture@example.test', password: 'synthetic-password' });
    return response(config, { token: tokens, user: {
      id: 'user', name: 'Fixture', email: 'fixture@example.test', role: 'user', status: 'ACTIVE', tenant_id: 'tenant',
    } });
  });
  assert.equal((await api.login('fixture@example.test', 'synthetic-password')).id, 'user');
  assert.equal(getAccessToken(), tokens.access_token);
  assert.equal(getRefreshToken(), tokens.refresh_token);
});

test('concurrent Axios 401s send one refresh and retry with the stored successor', async () => {
  const initial = pair(1), successor = pair(2);
  save(initial);
  let posts = 0, retries = 0;
  transport(async config => {
    if (config.url?.endsWith('/auth/refresh')) {
      posts++;
      assert.equal(JSON.parse(config.data).refresh_token, initial.refresh_token);
      return response(config, successor);
    }
    if (config.headers.Authorization === `Bearer ${initial.access_token}`) unauthorized(config);
    assert.equal(config.headers.Authorization, `Bearer ${successor.access_token}`);
    retries++;
    return response(config, { ok: true });
  });
  const result = await Promise.all([http.get('/fixture'), http.get('/fixture')]);
  assert.ok(result.every(item => item.data.ok));
  assert.equal(posts, 1); assert.equal(retries, 2);
  assert.equal(getRefreshToken(), successor.refresh_token);
});

test('logout sends its captured session even if a new login changes storage before dispatch', async () => {
  const initial = pair(1), newer = pair(9, 'new-session');
  save(initial);
  let complete!: () => void;
  const dispatched = new Promise<void>(resolve => { complete = resolve; });
  transport(async config => {
    assert.equal(config.url, '/auth/logout');
    assert.equal(config.headers.Authorization, `Bearer ${initial.access_token}`);
    complete();
    return response(config, null, 204);
  });
  api.logout();
  assert.equal(getAccessToken(), null); assert.equal(getRefreshToken(), null);
  save(newer);
  await dispatched;
  assert.equal(getAccessToken(), newer.access_token);
});

test('ambiguous refresh transport failure clears the old session without a second POST', async () => {
  const initial = pair(1);
  save(initial);
  let posts = 0;
  transport(async config => {
    if (config.url?.endsWith('/auth/refresh')) { posts++; throw new AxiosError('Synthetic lost response'); }
    unauthorized(config);
  });
  await assert.rejects(http.get('/fixture'));
  assert.equal(getAccessToken(), null);
  save(initial); // Model restored stale storage; the attempt marker survives.
  await assert.rejects(http.get('/fixture'));
  assert.equal(posts, 1);
});

test('late Axios denial cannot rotate or erase another login', async () => {
  const initial = pair(1), newer = pair(9, 'new-session');
  save(initial);
  let calls = 0;
  transport(async config => { calls++; save(newer); unauthorized(config); });
  await assert.rejects(http.get('/fixture'));
  assert.equal(calls, 1);
  assert.equal(getAccessToken(), newer.access_token);
});

test('auth bootstrap retries a timed-out retried GET after another request rotated credentials', async () => {
  const initial = pair(1), successor = pair(2);
  save(initial);
  let posts = 0, reads = 0;
  transport(async config => {
    if (config.url?.endsWith('/auth/refresh')) { posts++; return response(config, successor); }
    reads++;
    if (config.headers.Authorization === `Bearer ${initial.access_token}`) unauthorized(config);
    if (reads === 2) throw new AxiosError('Synthetic slow retried GET', 'ECONNABORTED', config);
    return response(config, {id:'user',name:'Fixture',email:'fixture@example.test',role:'user',status:'ACTIVE',tenant_id:'tenant'});
  });
  assert.equal((await api.getCurrentUser())?.id, 'user');
  assert.equal(posts, 1); assert.equal(reads, 3);
  assert.equal(getAccessToken(), successor.access_token);
  assert.equal(getRefreshToken(), successor.refresh_token);
});

test('late auth bootstrap denial cannot erase another login', async () => {
  const initial = pair(1), newer = pair(9, 'new-session');
  save(initial);
  transport(async config => { save(newer); unauthorized(config); });
  assert.equal(await api.getCurrentUser(), null);
  assert.equal(getAccessToken(), newer.access_token);
  assert.equal(getRefreshToken(), newer.refresh_token);
});

test('late successful auth bootstrap cannot publish a previous identity', async () => {
  save(pair(1));
  transport(async config => {
    save(pair(9, 'new-session'));
    return response(config, {id:'old-user',name:'Old fixture',email:'old@example.test',role:'owner',status:'ACTIVE',tenant_id:'old-tenant'});
  });
  assert.equal(await api.getCurrentUser(), null);
  assert.equal(getAccessToken(), pair(9, 'new-session').access_token);
});

test('bootstrap network failure does not destroy unchanged credentials', async () => {
  const initial = pair(1); save(initial);
  transport(async config => { throw new AxiosError('Synthetic network failure', 'ERR_NETWORK', config); });
  await assert.rejects(api.getCurrentUser());
  assert.equal(getAccessToken(), initial.access_token);
  assert.equal(getRefreshToken(), initial.refresh_token);
});

test('missing Web Locks fails closed without posting a competing refresh', async () => {
  const descriptor = Object.getOwnPropertyDescriptor(navigator, 'locks');
  Object.defineProperty(navigator, 'locks', {configurable:true, value:undefined});
  try {
    save(pair(1)); let posts = 0;
    transport(async config => {
      if (config.url?.endsWith('/auth/refresh')) posts++;
      unauthorized(config);
    });
    await assert.rejects(http.get('/fixture'));
    assert.equal(posts, 0); assert.equal(getAccessToken(), null);
  } finally {
    if (descriptor) Object.defineProperty(navigator, 'locks', descriptor);
    else Reflect.deleteProperty(navigator, 'locks');
  }
});

test('an uncertain storage receipt cannot become a bootstrap 401 that clears shared credentials',async()=>{
  const initial=pair(1);save(initial);values.set('vee_refresh_attempt','refresh-1');
  let posts=0;
  transport(async config=>{if(config.url?.endsWith('/auth/refresh'))posts++;unauthorized(config);});
  await assert.rejects(api.getCurrentUser(),{name:'RefreshStorageUnavailableError'});
  assert.equal(posts,0);assert(getAccessToken()===initial.access_token);assert(getRefreshToken()===initial.refresh_token);
});
