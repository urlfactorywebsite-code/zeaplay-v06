import test from 'node:test';
import assert from 'node:assert/strict';
import { createSessionRefresh, sessionIdentity, type SessionTokens } from '../services/sessionRefresh';

function token(jti: string, sid = 'session-one') {
  return `header.${Buffer.from(JSON.stringify({sub:'member', tenant_id:'tenant', sid, auth_epoch:0, jti})).toString('base64url')}.signature`;
}
const pair = (id: number, sid?: string): SessionTokens => ({access_token:token(`access-${id}`,sid),refresh_token:token(`refresh-${id}`,sid)});
function setup() {
  let saved: SessionTokens | null = pair(1), attempt: string | null = null, calls = 0, expired = 0;
  let queue = Promise.resolve();
  const endpoint = {run: async () => pair(2)};
  const options = {
    getAccess: () => saved?.access_token ?? null, getRefresh: () => saved?.refresh_token ?? null,
    store: (value: SessionTokens) => {saved=value;}, expire: () => {expired++;saved=null;},
    attempted: () => attempt, markAttempt: (value:string) => {attempt=value;},
    request: async () => {calls++;return endpoint.run();},
    lock: <T>(work:()=>Promise<T>):Promise<T> => {
      const next=queue.then(work);queue=next.then(()=>undefined,()=>undefined);return next;
    },
  };
  return {options, endpoint, state:()=>({saved,attempt,calls,expired}), set:(value:SessionTokens|null)=>{saved=value;}};
}

test('successful rotation persists both tokens',async()=>{
  const h=setup();assert.equal(await createSessionRefresh(h.options)(pair(1).access_token),pair(2).access_token);
  assert.deepEqual(h.state().saved,pair(2));assert.equal(h.state().calls,1);
});
test('same-tab requests share one refresh',async()=>{
  const h=setup(), refresh=createSessionRefresh(h.options);
  const result=await Promise.all([refresh(pair(1).access_token),refresh(pair(1).access_token)]);
  assert.deepEqual(result,[pair(2).access_token,pair(2).access_token]);assert.equal(h.state().calls,1);
});
test('separate tab coordinators use the lock and stored successor',async()=>{
  const h=setup(), tab1=createSessionRefresh(h.options),tab2=createSessionRefresh(h.options);
  assert.deepEqual(await Promise.all([tab1(pair(1).access_token),tab2(pair(1).access_token)]),[pair(2).access_token,pair(2).access_token]);
  assert.equal(h.state().calls,1);
});
test('network ambiguity is never retried with the same credential',async()=>{
  const h=setup();h.endpoint.run=async()=>{throw new Error('response lost');};
  const refresh=createSessionRefresh(h.options);
  assert.equal(await refresh(pair(1).access_token),null);assert.equal(h.state().calls,1);assert.equal(h.state().expired,1);
  // Model a crash/reload restoring old token storage while the durable attempt marker survives.
  h.set(pair(1));assert.equal(await createSessionRefresh(h.options)(pair(1).access_token),null);
  assert.equal(h.state().calls,1);
});
test('logout during refresh cannot restore credentials',async()=>{
  const h=setup();h.endpoint.run=async()=>{h.set(null);return pair(2);};
  assert.equal(await createSessionRefresh(h.options)(pair(1).access_token),null);assert.equal(h.state().saved,null);
});
test('new login during refresh is preserved on success or failure',async()=>{
  for (const failure of [false,true]) {
    const h=setup();h.endpoint.run=async()=>{h.set(pair(9,'other-session'));if(failure)throw new Error('failed');return pair(2);};
    assert.equal(await createSessionRefresh(h.options)(pair(1).access_token),null);
    assert.deepEqual(h.state().saved,pair(9,'other-session'));assert.equal(h.state().expired,0);
  }
});
test('stale request cannot rotate another session',async()=>{
  const h=setup();h.set(pair(9,'other-session'));
  assert.equal(await createSessionRefresh(h.options)(pair(1).access_token),null);assert.equal(h.state().calls,0);
});
test('new account requests do not share the previous account pending refresh',async()=>{
  const h=setup();let release!: (value:SessionTokens)=>void;
  h.endpoint.run=()=>new Promise(resolve=>{release=resolve;});
  const refresh=createSessionRefresh(h.options);
  const old=refresh(pair(1).access_token);
  await Promise.resolve();await Promise.resolve();
  h.set(pair(9,'other-session'));
  const next=refresh(pair(9,'other-session').access_token);
  h.endpoint.run=async()=>pair(10,'other-session');
  release(pair(2));
  assert.equal(await old,null);assert.equal(await next,pair(10,'other-session').access_token);
  assert.deepEqual(h.state().saved,pair(10,'other-session'));assert.equal(h.state().expired,0);
});
test('legacy tokens require sign-in and do not attempt rotation',async()=>{
  const h=setup();assert.equal(await createSessionRefresh(h.options)('legacy'),null);assert.equal(h.state().calls,0);
  assert.equal(sessionIdentity('legacy'),null);
});
test('storage failure prevents sending a state-changing refresh',async()=>{
  const h=setup();h.options.markAttempt=()=>{throw new Error('storage blocked');};
  assert.equal(await createSessionRefresh(h.options)(pair(1).access_token),null);assert.equal(h.state().calls,0);
});
test('wrong-session or reused response is rejected',async()=>{
  for (const result of [pair(1),pair(2,'foreign')]) {
    const h=setup();h.endpoint.run=async()=>result;
    assert.equal(await createSessionRefresh(h.options)(pair(1).access_token),null);assert.equal(h.state().expired,1);
  }
});

test('a lock waiter waits for queued storage updates before rejecting an attempted predecessor',async()=>{
  const h=setup();h.options.markAttempt('refresh-1');
  let receipts=0;
  const refresh=createSessionRefresh({...h.options,waitForChange:async()=>{
    receipts++;h.set(pair(2));return true;
  }});
  assert.equal(await refresh(pair(1).access_token),pair(2).access_token);
  assert.equal(receipts,1);assert.equal(h.state().calls,0);assert.equal(h.state().expired,0);
});

test('missing storage receipt never retries a consumed credential',async()=>{
  const h=setup();h.options.markAttempt('refresh-1');
  let receipts=0;
  const refresh=createSessionRefresh({...h.options,waitForChange:async()=>{receipts++;return false;}});
  await assert.rejects(refresh(pair(1).access_token),{name:'RefreshStorageUnavailableError'});
  assert.equal(receipts,1);assert.equal(h.state().calls,0);assert.equal(h.state().expired,0);
  assert.deepEqual(h.state().saved,pair(1),'An unconfirmed local cache cannot erase the shared store');
});

test('an intervening new login received by a lock waiter is preserved',async()=>{
  for(const received of [true,false]){
    const h=setup();h.options.markAttempt('refresh-1');
    const refresh=createSessionRefresh({...h.options,waitForChange:async()=>{h.set(pair(9,'other-session'));return received;}});
    assert.equal(await refresh(pair(1).access_token),null);
    assert.deepEqual(h.state().saved,pair(9,'other-session'));assert.equal(h.state().expired,0);
  }
});
