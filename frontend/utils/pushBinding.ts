// The worker stores a routing nonce, never an authentication token.
let generation = 0;
const pageNotices = new Set<Notification>();
export function trackBrowserNotice(notice: Notification) {
  pageNotices.add(notice);
  notice.addEventListener?.('close', () => pageNotices.delete(notice), { once: true });
  while (pageNotices.size > 100) {
    const first = pageNotices.values().next().value!; first.close(); pageNotices.delete(first);
  }
}
export function clearPageNotices() { pageNotices.forEach(notice => notice.close()); pageNotices.clear(); }
export async function setPushBinding(registration: ServiceWorkerRegistration, key: string | null, current = () => true): Promise<boolean> {
  if (!current()) return false;
  const worker = registration.active;
  if (!worker) return false;
  return new Promise(resolve => {
    const channel = new MessageChannel();
    const timeout = setTimeout(() => { channel.port1.close(); resolve(false); }, 1500);
    channel.port1.onmessage = event => {
      clearTimeout(timeout); channel.port1.close(); resolve(Boolean(event.data?.ok) && current());
    };
    worker.postMessage({ type: 'zea:push-binding', key }, [channel.port2]);
  });
}

export function clearPushBinding(): void {
  clearPageNotices();
  const expected = ++generation;
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
  // Reach a controlling worker immediately, then its registration if necessary.
  navigator.serviceWorker.controller?.postMessage({ type: 'zea:push-binding', key: null });
  void navigator.serviceWorker.getRegistration().then(async registration => {
    if (registration && expected === generation) await setPushBinding(registration, null, () => expected === generation);
  }).catch(() => undefined);
}

export function beginPushBinding(): number { return ++generation; }
export function bindingGeneration(): number { return generation; }
