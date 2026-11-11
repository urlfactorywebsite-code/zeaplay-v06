self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Opaque device/account routing nonce only; never store bearer credentials.
const bindingUrl = new URL('/__zea_push_binding__', self.location.origin).href;
const bindingCache = 'zea-push-binding-v1';
const receiptsUrl = new URL('/__zea_push_receipts__', self.location.origin).href;
const currentBinding = async () => {
  try { return await (await (await caches.open(bindingCache)).match(bindingUrl))?.text() || null; }
  catch { return null; } // In-app notifications continue if storage is unavailable.
};
let bindingWrites = Promise.resolve();
let pushDeliveries = Promise.resolve();
self.addEventListener('message', (event) => {
  if (event.data?.type !== 'zea:push-binding') return;
  const key = event.data.key;
  if (key !== null && !/^[0-9a-f-]{36}$/i.test(key || '')) return;
  bindingWrites = bindingWrites.catch(() => undefined).then(async () => {
    const cache = await caches.open(bindingCache);
    const previous = await currentBinding();
    if (key) await cache.put(bindingUrl, new Response(key));
    else await cache.delete(bindingUrl);
    if (previous !== key || !key) {
      const notices = await self.registration.getNotifications();
      notices.forEach(notice => notice.close());
    }
    event.ports?.[0]?.postMessage({ ok: true });
    event.ports?.[0]?.close?.();
  });
  event.waitUntil(bindingWrites);
});

self.addEventListener('push', (event) => {
  let payload = {};

  if (event.data) {
    try {
      payload = event.data.json();
    } catch {
      payload = { body: event.data.text() };
    }
  }

  const title = payload.title || 'ZeaPlay';
  const options = {
    body: payload.body || 'You have a new notification.',
    icon: payload.icon || '/favicon.ico',
    badge: payload.badge || '/favicon.ico',
    tag: payload.notification_id ? `zea:${payload.notification_id}` : undefined,
    renotify: false,
    silent: typeof payload.silent === 'boolean' ? payload.silent : undefined,
    data: {
      url: payload.url || '/',
      notificationId: payload.notification_id || null,
      eventType: payload.event_type || null,
      module: payload.module || null,
      bindingKey: payload.binding_key || null,
    },
  };

  // A worker can receive concurrent pushes and may restart between retries.
  // Serialize the small receipt cache; tags also cover interruption after show.
  pushDeliveries = pushDeliveries.catch(() => undefined).then(async () => {
    await bindingWrites;
    if (!payload.binding_key || payload.binding_key !== await currentBinding()) return;
    const cache = await caches.open(bindingCache);
    let seen = [];
    try {
      const saved = await (await cache.match(receiptsUrl))?.json();
      if (saved?.binding === payload.binding_key && Array.isArray(saved.ids)) seen = saved.ids.slice(-1000);
    } catch { /* A corrupt optional receipt cache cannot break the inbox. */ }
    const receipt = typeof payload.notification_id === 'string' && payload.notification_id.length <= 128 ? payload.notification_id : null;
    if (receipt && seen.includes(receipt)) return;
    // The open application renders its preferred foreground sound once across
    // tabs. Keep background delivery audible only when explicitly enabled.
    if (payload.silent === false) {
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      if (clients.some(client => client.visibilityState === 'visible')) options.silent = true;
    }
    if (payload.binding_key !== await currentBinding()) return;
    await self.registration.showNotification(title, options);
    if (payload.binding_key !== await currentBinding()) {
      const cards = await self.registration.getNotifications();
      cards.filter(card => card.data?.bindingKey === payload.binding_key).forEach(card => card.close());
      return;
    }
    if (receipt) await cache.put(receiptsUrl, new Response(JSON.stringify({ binding: payload.binding_key, ids: [...seen, receipt].slice(-1000) })));
  });
  event.waitUntil(pushDeliveries);
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  let target = new URL('/', self.location.origin);
  try {
    const requested = new URL(event.notification.data?.url || '/', self.location.origin);
    if (requested.origin === self.location.origin) target = requested;
  } catch { /* Keep malformed/untrusted links inside the application. */ }
  // The existing application uses a hash router. Keep task/subtask query
  // context inside that hash when opening a notification in a new tab.
  if (!target.hash && target.pathname !== '/') {
    target.hash = target.pathname + target.search;
    target.pathname = '/'; target.search = '';
  }
  const targetUrl = target.href;

  event.waitUntil(
    (async () => {
      await bindingWrites;
      if (event.notification.data?.bindingKey && event.notification.data.bindingKey !== await currentBinding()) return;
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of clients) {
        if ('focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }

      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }

      return undefined;
    })()
  );
});
