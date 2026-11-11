import assert from 'node:assert/strict';
import test from 'node:test';
import { createAvatarImageCache } from '../utils/avatarImageCache';

const picture = () => Promise.resolve(new Blob(['raster'], { type: 'image/webp' }));

test('simultaneous avatar consumers share one authenticated download and object URL', async () => {
  let downloads = 0, urls = 0;
  const revoked: string[] = [];
  const cache = createAvatarImageCache(() => `blob:${++urls}`, url => revoked.push(url));
  const load = () => { downloads++; return picture(); };
  const first = cache.acquire('/avatars/one/image', 'account-a', load);
  const second = cache.acquire('/avatars/one/image', 'account-a', load);
  assert.deepEqual(await Promise.all([first.promise, second.promise]), ['blob:1', 'blob:1']);
  first.release(); second.release();
  const remounted = cache.acquire('/avatars/one/image', 'account-a', load);
  assert.equal(await remounted.promise, 'blob:1');
  assert.equal(downloads, 1);
  cache.clear();
  assert.deepEqual(revoked, ['blob:1']);
});

test('a failed download can be retried and non-image content is rejected', async () => {
  const cache = createAvatarImageCache(() => 'blob:safe', () => {});
  await assert.rejects(cache.acquire('/image', 'a', () => Promise.reject(new Error('offline'))).promise, /offline/);
  await assert.rejects(cache.acquire('/image', 'a', () => Promise.resolve(new Blob(['<html/>'], { type: 'text/html' }))).promise, /Invalid avatar response/);
  assert.equal(await cache.acquire('/image', 'a', picture).promise, 'blob:safe');
  assert.equal(await cache.acquire('/bundled', 'a', () => Promise.resolve(new Blob(['<svg/>'], { type: 'image/svg+xml' }))).promise, 'blob:safe');
});

test('login changes revoke previous images and prevent late responses from crossing sessions', async () => {
  let complete!: (blob: Blob) => void;
  const revoked: string[] = [];
  const cache = createAvatarImageCache(() => 'blob:private', url => revoked.push(url));
  const pending = cache.acquire('/old', 'a', () => new Promise(resolve => { complete = resolve; }));
  const rejected = assert.rejects(pending.promise, /session changed/);
  await cache.acquire('/image', 'b', picture).promise;
  complete(new Blob(['old'], { type: 'image/webp' }));
  await rejected;
  cache.clear();
  assert.deepEqual(revoked, ['blob:private']);
});

test('unused cached images expire, while mounted consumers keep their URL', async () => {
  let time = 0, urls = 0;
  const revoked: string[] = [];
  const cache = createAvatarImageCache(() => `blob:${++urls}`, url => revoked.push(url), () => time);
  const idle = cache.acquire('/idle', 'a', picture);
  const mounted = cache.acquire('/mounted', 'a', picture);
  await Promise.all([idle.promise, mounted.promise]);
  idle.release(); idle.release();
  time = 300_001;
  await cache.acquire('/new', 'a', picture).promise;
  assert.deepEqual(revoked, ['blob:1']);
  assert.equal(await mounted.promise, 'blob:2');
  cache.clear();
});
