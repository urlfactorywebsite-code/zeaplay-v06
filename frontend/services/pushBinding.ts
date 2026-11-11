import api from './mockApi';
import { getAccessToken } from './tokenStorage';
import { beginPushBinding, bindingGeneration, setPushBinding } from '../utils/pushBinding';

export async function bindPushSubscription(registration: ServiceWorkerRegistration, subscription: PushSubscription, current = () => true): Promise<boolean> {
  const token = getAccessToken();
  const generation = beginPushBinding();
  const valid = () => current() && getAccessToken() === token && generation === bindingGeneration();
  // Require the new worker's acknowledgement before enabling background delivery.
  if (!valid() || !await setPushBinding(registration, null, valid)) return false;
  const json = subscription.toJSON();
  const key = await api.subscribePush({ endpoint: subscription.endpoint,
    keys: { p256dh: json.keys?.p256dh ?? '', auth: json.keys?.auth ?? '' },
    userAgent: navigator.userAgent, deviceLabel: navigator.platform });
  return Boolean(key) && valid() && await setPushBinding(registration, key, valid);
}

export async function rebindExistingPush(current: () => boolean): Promise<void> {
  if (!('serviceWorker' in navigator) || typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  const registration = await navigator.serviceWorker.getRegistration();
  if (!registration || !current()) return;
  await registration.update().catch(() => undefined);
  const subscription = await registration.pushManager.getSubscription();
  if (subscription && current()) await bindPushSubscription(registration, subscription, current);
}
