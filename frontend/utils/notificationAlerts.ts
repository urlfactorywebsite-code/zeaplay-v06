import type { Notification as InboxNotification } from '../types';
import { trackBrowserNotice } from './pushBinding';

export const NOTIFICATIONS_CHANGED = 'zea:notifications-changed';
export const notifyNotificationsChanged = () => window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
const seenInMemory = new Map<string, string[]>();

export function knownNotificationIds(userId: string): Set<string> {
  let stored: string[] = [];
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(`zea:notification-seen:${userId}`) || '[]');
    if (Array.isArray(parsed)) stored = parsed.slice(-1000).filter((id): id is string => typeof id === 'string');
  } catch { /* The per-page cache still prevents repeats when storage is blocked. */ }
  return new Set([...(seenInMemory.get(userId) || []), ...stored]);
}

export function rememberNotifications(userId: string, ids: string[]) {
  const known = [...new Set([...knownNotificationIds(userId), ...ids])].slice(-1000);
  seenInMemory.set(userId, known);
  while (seenInMemory.size > 16) seenInMemory.delete(seenInMemory.keys().next().value!);
  try { localStorage.setItem(`zea:notification-seen:${userId}`, JSON.stringify(known)); } catch { /* optional */ }
}

export function notificationDelivery(policy: { pushEnabled: boolean; soundEnabled: boolean; quiet: boolean },
  permission: NotificationPermission | 'unsupported', visible: boolean) {
  return {
    browser: policy.pushEnabled && !policy.quiet && permission === 'granted',
    sound: policy.soundEnabled && !policy.quiet && visible,
  };
}

export async function presentNotifications(userId: string, items: InboxNotification[],
  policy: { pushEnabled: boolean; soundEnabled: boolean; quiet: boolean }, isCurrent: () => boolean = () => true) {
  const run = async () => {
    if (!isCurrent()) return;
    const seen = knownNotificationIds(userId);
    const fresh = items.filter(item => item.alertKind && !item.isRead && !seen.has(item.id));
    rememberNotifications(userId, items.map(item => item.id));
    if (!fresh.length) return;
    const delivery = notificationDelivery(policy, 'Notification' in window ? Notification.permission : 'unsupported', !document.hidden);
    if (delivery.browser) {
      let registration: ServiceWorkerRegistration | undefined;
      try { registration = 'serviceWorker' in navigator ? await navigator.serviceWorker.getRegistration() : undefined; }
      catch { /* Native fallback remains available. */ }
      if (!isCurrent()) return;
      for (const item of fresh) {
        try {
          const options = { body: item.message, tag: `zea:${item.id}`, silent: true,
            data: { url: item.deepLink || (item.relatedTaskId ? `/tasks/${item.relatedTaskId}` : '/dashboard') } };
          if (!isCurrent()) return;
          if (registration) await registration.showNotification(item.title || 'ZeaPlay', options);
          else {
            const alert = new Notification(item.title || 'ZeaPlay', options);
            trackBrowserNotice(alert);
            alert.onclick = () => { if (isCurrent()) { window.focus(); window.location.hash = options.data.url; } alert.close(); };
          }
        } catch { /* Browser denial or unavailable services never affect the inbox. */ }
      }
    }
    if (delivery.sound) {
      try {
        const audio = new AudioContext();
        if (audio.state === 'suspended') { void audio.close(); return; }
        const oscillator = audio.createOscillator(), gain = audio.createGain();
        gain.gain.value = 0.06; oscillator.frequency.value = 660;
        oscillator.connect(gain); gain.connect(audio.destination);
        oscillator.onended = () => { void audio.close(); };
        oscillator.start(); oscillator.stop(audio.currentTime + 0.12);
        setTimeout(() => { if (audio.state !== 'closed') void audio.close(); }, 1000);
      } catch { /* Autoplay may require a prior user gesture. */ }
    }
  };
  // One audible presentation across tabs where Web Locks is available. Browser
  // notification tags also replace retried Web Push deliveries with the same ID.
  if (navigator.locks) {
    try { await navigator.locks.request(`zea:notification:${userId}`, run); }
    catch { await run(); }
  } else await run();
}
