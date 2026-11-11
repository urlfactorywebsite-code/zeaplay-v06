import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function worker(visible = false, storage = new Map<string, Response>()) {
  const handlers: Record<string, (event: any) => void> = {};
  const shown: any[] = [], opened: string[] = [];
  const self = {
    location: { origin: 'https://zea.example.test' },
    addEventListener: (name: string, handler: (event: any) => void) => { handlers[name] = handler; },
    registration: { getNotifications: async () => [], showNotification: async (title: string, options: unknown) => { shown.push({ title, options }); } },
    clients: { matchAll: async () => visible ? [{ visibilityState: 'visible' }] : [], openWindow: async (url: string) => { opened.push(url); } },
  };
  const cache = { match: async (url: string) => storage.get(url)?.clone(), put: async (url: string, response: Response) => { storage.set(url, response); }, delete: async (url: string) => storage.delete(url) };
  vm.runInNewContext(readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8'), { self, URL, Response, caches: { open: async () => cache } });
  const bind = async (key: string | null) => { let done: Promise<unknown>; handlers.message({ data: { type: 'zea:push-binding', key }, ports: [{ postMessage() {} }], waitUntil: (p: Promise<unknown>) => { done = p; } }); await done!; };
  return { shown, opened, handlers, bind, storage };
}
test('service worker deduplicates retried push by notification ID and respects silent preference', async () => {
  const w = worker(); let done: Promise<unknown>;
  await w.bind('00000000-0000-0000-0000-000000000001');
  const event = { data: { json: () => ({ binding_key: '00000000-0000-0000-0000-000000000001', notification_id: 'ledger-1', silent: true, url: '/tasks/task-1' }) }, waitUntil: (p: Promise<unknown>) => { done = p; } };
  w.handlers.push(event); await done!;
  assert.equal(w.shown[0].options.tag, 'zea:ledger-1');
  assert.equal(w.shown[0].options.renotify, false);
  assert.equal(w.shown[0].options.silent, true);
});
test('browser task/subtask links preserve context inside the existing hash router', async () => {
  const w = worker(); let done: Promise<unknown>;
  w.handlers.notificationclick({ notification: { close() {}, data: { url: '/tasks/task-1?subtask=child-2' } }, waitUntil: (p: Promise<unknown>) => { done = p; } });
  await done!;
  assert.equal(w.opened[0], 'https://zea.example.test/#/tasks/task-1?subtask=child-2');
});
test('legacy push payloads retain the browser default sound behavior', async () => {
  const w = worker(); let done: Promise<unknown>;
  await w.bind('00000000-0000-0000-0000-000000000001');
  w.handlers.push({ data: { json: () => ({ binding_key: '00000000-0000-0000-0000-000000000001', title: 'Existing chat alert' }) }, waitUntil: (p: Promise<unknown>) => { done = p; } });
  await done!;
  assert.equal(w.shown[0].options.silent, undefined);
});
test('untrusted browser notification links stay inside the application', async () => {
  const w = worker(); let done: Promise<unknown>;
  w.handlers.notificationclick({ notification: { close() {}, data: { url: 'https://other.example.test/private' } }, waitUntil: (p: Promise<unknown>) => { done = p; } });
  await done!;
  assert.equal(w.opened[0], 'https://zea.example.test/');
});

test('worker drops unbound, logged-out and previous-account push payloads', async () => {
  const w = worker();
  const push = async (binding_key?: string) => { let done: Promise<unknown>; w.handlers.push({ data: { json: () => ({ binding_key, title: 'Private task' }) }, waitUntil: (p: Promise<unknown>) => { done = p; } }); await done!; };
  const first = '00000000-0000-0000-0000-000000000001', second = '00000000-0000-0000-0000-000000000002';
  await push(); await push(first); assert.equal(w.shown.length, 0);
  await w.bind(first); await push(first); assert.equal(w.shown.length, 1);
  await w.bind(null); await push(first); assert.equal(w.shown.length, 1);
  await w.bind(second); await push(first); assert.equal(w.shown.length, 1);
  await push(second); assert.equal(w.shown.length, 2);
});

test('foreground worker push does not duplicate the application sound', async () => {
  const w = worker(true); const key = '00000000-0000-0000-0000-000000000001';
  await w.bind(key); let done: Promise<unknown>;
  w.handlers.push({ data: { json: () => ({ binding_key: key, silent: false, title: 'Reward' }) }, waitUntil: (p: Promise<unknown>) => { done = p; } });
  await done!;
  assert.equal(w.shown[0].options.silent, true);
});

async function push(w: ReturnType<typeof worker>, payload: object) {
  let done: Promise<unknown>;
  w.handlers.push({data:{json:()=>payload},waitUntil:(p:Promise<unknown>)=>{done=p;}});
  await done!;
}
const binding = '00000000-0000-0000-0000-000000000001';
test('concurrent repeated push is presented once after cards are dismissed and worker restarts', async () => {
  const first = worker(false);
  await first.bind(binding);
  const payload = {binding_key:binding,notification_id:'repeated-reward',silent:false};
  await Promise.all([push(first,payload),push(first,payload),push(first,payload)]);
  assert.equal(first.shown.length,1);
  assert.equal(first.shown[0].options.silent,false); // no visible clients: enabled background sound
  const restarted = worker(false,first.storage);
  await push(restarted,payload);
  assert.equal(restarted.shown.length,0);
  await push(restarted,{...payload,notification_id:'next-event',silent:true});
  assert.equal(restarted.shown.length,1);
  assert.equal(restarted.shown[0].options.silent,true);
});

test('out of order background events remain independently idempotent', async () => {
  const w=worker(false);await w.bind(binding);
  for(const id of ['reversed','credited','reversed','credited']) await push(w,{binding_key:binding,notification_id:id,silent:true});
  assert.equal(w.shown.length,2);
  assert.deepEqual(w.shown.map(n=>n.options.tag),['zea:reversed','zea:credited']);
});
