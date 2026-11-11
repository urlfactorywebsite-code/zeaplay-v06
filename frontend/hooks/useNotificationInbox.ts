import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import api from '../services/mockApi';
import { getAccessToken } from '../services/tokenStorage';
import { rebindExistingPush } from '../services/pushBinding';
import { clearPageNotices } from '../utils/pushBinding';
import { coalesceActivityRefresh } from '../utils/activityRefresh';
import { APP_REFRESH_EVENT } from '../utils/appEvents';
import { NOTIFICATIONS_CHANGED, presentNotifications, rememberNotifications } from '../utils/notificationAlerts';
import type { Notification } from '../types';

export function useNotificationInbox(userId?: string, role?: string, connected = false) {
  const token = getAccessToken();
  const identity = `${userId ?? ''}:${role ?? ''}:${token ?? ''}`;
  const scope = useMemo(() => ({}), [identity]);
  const [boundIdentity, setBoundIdentity] = useState(identity);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const refreshRef = useRef<() => void>(() => undefined);
  const refresh = useCallback(() => refreshRef.current(), []);
  useEffect(() => {
    let alive = true, running = false, queued = false, first = true;
    let presenting = false;
    let pendingPresentation: Awaited<ReturnType<typeof api.getNotificationInbox>> | undefined;
    setNotifications([]); setUnreadCount(0);
    setBoundIdentity(identity);
    const present = async (inbox: Awaited<ReturnType<typeof api.getNotificationInbox>>) => {
      pendingPresentation = inbox;
      if (presenting) return;
      presenting = true;
      try {
        while (alive && pendingPresentation) {
          const latest = pendingPresentation; pendingPresentation = undefined;
          await presentNotifications(userId!, latest.items, latest, () => alive && getAccessToken() === token);
        }
      } finally { presenting = false; }
    };
    const load = async () => {
      if (!alive || !userId || !navigator.onLine || document.hidden) return;
      if (running) { queued = true; return; }
      running = true;
      try {
        const inbox = await api.getNotificationInbox();
        if (!alive || inbox.userId !== userId || getAccessToken() !== token) return;
        setNotifications(inbox.items); setUnreadCount(inbox.unreadCount);
        if (!first) void present(inbox).catch(() => undefined);
        else {
          // Do not replay historical alerts on login/StrictMode remount.
          rememberNotifications(userId, inbox.items.map(n => n.id));
        }
        first = false;
      } catch { /* Preserve the durable inbox and refetch on reconnect. */ }
      finally {
        running = false;
        if (queued && alive) { queued = false; schedule(); }
      }
    };
    const scheduled = coalesceActivityRefresh(() => void load(), {
      later: fn => window.setTimeout(fn, 200), clear: id => window.clearTimeout(id),
    });
    const schedule = () => { if (alive) scheduled.request(); };
    refreshRef.current = schedule;
    const bind = () => { void rebindExistingPush(() => alive && getAccessToken() === token).catch(() => undefined); };
    bind();
    if ('serviceWorker' in navigator) navigator.serviceWorker.addEventListener('controllerchange', bind);
    window.addEventListener('online', bind);
    // Coalesce StrictMode replay and the initial socket connection as well.
    schedule();
    const events = [NOTIFICATIONS_CHANGED, APP_REFRESH_EVENT, 'online', 'focus'];
    events.forEach(name => window.addEventListener(name, schedule));
    document.addEventListener('visibilitychange', schedule);
    return () => {
      alive = false; pendingPresentation = undefined; scheduled.cancel(); refreshRef.current = () => undefined;
      clearPageNotices();
      if ('serviceWorker' in navigator) navigator.serviceWorker.removeEventListener('controllerchange', bind);
      window.removeEventListener('online', bind);
      events.forEach(name => window.removeEventListener(name, schedule));
      document.removeEventListener('visibilitychange', schedule);
    };
  }, [userId, token, identity]);
  useEffect(() => {
    // The shared socket is authoritative while healthy. One client recovery
    // timer is used only when it is unavailable; there is no per-task timer.
    if (connected || !userId) return;
    const interval = setInterval(() => refreshRef.current(), 30_000 + Math.floor(Math.random() * 5000));
    return () => clearInterval(interval);
  }, [connected, userId, identity]);
  return { scope, notifications: boundIdentity === identity ? notifications : [], setNotifications,
    unreadCount: boundIdentity === identity ? unreadCount : 0, setUnreadCount, refresh };
}
