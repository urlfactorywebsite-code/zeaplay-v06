import assert from 'node:assert/strict';
import test, {after, beforeEach} from 'node:test';
import {waitForTokenChange} from '../services/tokenStorage';

// Component-only DOM/storage events; actual browser coverage is separate.
const windowDescriptor=Object.getOwnPropertyDescriptor(globalThis,'window');
const storageDescriptor=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
const data=new Map<string,string>();
const storage={getItem:(key:string)=>data.get(key)??null};
class TestWindow extends EventTarget {
  listeners=0;
  addEventListener(...args:Parameters<EventTarget['addEventListener']>){this.listeners++;super.addEventListener(...args);}
  removeEventListener(...args:Parameters<EventTarget['removeEventListener']>){this.listeners--;super.removeEventListener(...args);}
}
const win=new TestWindow();
Object.defineProperty(globalThis,'window',{configurable:true,value:win});
Object.defineProperty(globalThis,'localStorage',{configurable:true,value:storage});
beforeEach(()=>{data.clear();data.set('vee_access_token','old-access');data.set('vee_refresh_token','old-refresh');});
after(()=>{
  if(windowDescriptor)Object.defineProperty(globalThis,'window',windowDescriptor);else Reflect.deleteProperty(globalThis,'window');
  if(storageDescriptor)Object.defineProperty(globalThis,'localStorage',storageDescriptor);else Reflect.deleteProperty(globalThis,'localStorage');
});
function event(key:string|null,storageArea:unknown=storage){win.dispatchEvent(Object.assign(new Event('storage'),{key,storageArea}));}

test('already-completed update resolves without waiting and removes its listener',async()=>{
  data.set('vee_access_token','new-access');data.set('vee_refresh_token','new-refresh');
  assert.equal(await waitForTokenChange('old-access','old-refresh'),true);assert.equal(win.listeners,0);
});
test('only a complete pair received from local storage releases the waiter',async()=>{
  let settled=false;const waiting=waitForTokenChange('old-access','old-refresh').then(value=>{settled=true;return value;});
  data.set('vee_access_token','new-access');event('vee_access_token');await Promise.resolve();assert(!settled);
  data.set('vee_refresh_token','new-refresh');event('vee_refresh_token',{});await Promise.resolve();assert(!settled);
  event('vee_refresh_token');assert.equal(await waiting,true);assert.equal(win.listeners,0);
});
test('logout receipt releases the waiter after both credentials are removed',async()=>{
  const waiting=waitForTokenChange('old-access','old-refresh');data.clear();event(null);
  assert.equal(await waiting,true);assert.equal(win.listeners,0);
});
test('lost issuer is bounded without changing credentials or leaving listeners',async()=>{
  const start=Date.now();assert.equal(await waitForTokenChange('old-access','old-refresh'),false);
  assert(Date.now()-start>=7800);assert.equal(data.get('vee_access_token'),'old-access');assert.equal(win.listeners,0);
});
