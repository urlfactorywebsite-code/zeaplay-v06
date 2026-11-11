import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { getAccessToken } from '../services/tokenStorage';
import { TASK_ACTIVITY_WATCH } from '../utils/taskActivity';
import { taskReconnectDelay } from '../utils/taskSocket';

type TaskSocketStatus = 'connected' | 'connecting' | 'offline';

type TaskSocketEvent = Record<string, unknown>;

type UseTaskWebSocketOptions = {
  enabled?: boolean;
  onEvent?: (payload: TaskSocketEvent) => void;
  userId?: string;
};

const resolveTasksSocketUrl = (): string | null => {
  const base =
    import.meta.env.VITE_API_URL ??
    import.meta.env.VITE_API_BASE_URL ??
    (typeof window !== 'undefined' ? window.location.origin : '');

  if (!base) {
    return null;
  }

  const url = new URL(base, window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `${url.pathname.replace(/\/$/, '')}/ws/tasks`;
  return url.toString();
};

export const useTaskWebSocket = ({ enabled = true, onEvent, userId }: UseTaskWebSocketOptions) => {
  const token = getAccessToken();
  const [status, setStatus] = useState<TaskSocketStatus>('offline');
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const retryCountRef = useRef(0);
  const callback = useRef(onEvent);
  callback.current = onEvent;
  const disposed = useRef(false);
  const detach = useRef<(() => void) | null>(null);
  const watched = useRef<string | undefined>(undefined);
  const lastSeen = useRef(0);

  const cleanup = useCallback(() => {
    if (reconnectRef.current) {
      window.clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
    detach.current?.(); detach.current = null;
    const socket = socketRef.current;
    socketRef.current = null;
    socket?.close();
  }, []);

  const connect = useCallback(() => {
    if (!enabled || disposed.current || !navigator.onLine || socketRef.current?.readyState === WebSocket.OPEN || socketRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }
    const wsUrl = resolveTasksSocketUrl();
    if (!token || !wsUrl) {
      setStatus('offline');
      return;
    }

    const url = `${wsUrl}?token=${encodeURIComponent(token)}`;
    setStatus('connecting');
    const socket = new WebSocket(url);
    socketRef.current = socket;
    lastSeen.current = performance.now();

    const opened = () => {
      if (disposed.current || socketRef.current !== socket) return;
      lastSeen.current = performance.now();
      retryCountRef.current = 0;
      setStatus('connected');
      if (watched.current && watched.current !== userId) socket.send(JSON.stringify({ type: 'activity.watch', user_id: watched.current }));
    };

    const received = (event: MessageEvent) => {
      if (disposed.current || socketRef.current !== socket) return;
      lastSeen.current = performance.now();
      try {
        const payload = JSON.parse(event.data);
        if (payload?.type === 'ping') {
          socket.send(JSON.stringify({ type: 'pong' }));
          return;
        }
        if (payload?.type === 'activity.watching') return;
        callback.current?.(payload);
      } catch {
        // ignore malformed payload
      }
    };

    const closed = () => {
      if (!enabled || disposed.current || socketRef.current !== socket) {
        return;
      }
      detach.current?.(); detach.current = null;
      socketRef.current = null;
      setStatus('offline');
      if (!navigator.onLine) return;
      const retryDelay = taskReconnectDelay(retryCountRef.current, Math.random());
      retryCountRef.current += 1;
      reconnectRef.current = window.setTimeout(() => {
        reconnectRef.current = null;
        connect();
      }, retryDelay);
    };

    const failed = () => { if (socketRef.current === socket) socket.close(); };
    socket.addEventListener('open', opened);
    socket.addEventListener('message', received);
    socket.addEventListener('close', closed);
    socket.addEventListener('error', failed);
    detach.current = () => {
      socket.removeEventListener('open', opened); socket.removeEventListener('message', received);
      socket.removeEventListener('close', closed); socket.removeEventListener('error', failed);
    };
  }, [enabled, token, userId]);

  useEffect(() => {
    disposed.current = false;
    if (!enabled || !token) {
      cleanup();
      setStatus('offline');
      return;
    }
    connect();
    const watch = (event: Event) => {
      watched.current = (event as CustomEvent<{ userId?: string }>).detail?.userId;
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'activity.watch', user_id: watched.current || null }));
    };
    const offline = () => { cleanup(); setStatus('offline'); };
    const online = () => { cleanup(); connect(); };
    const check = () => {
      if (document.hidden || !navigator.onLine) return;
      if (socketRef.current && performance.now() - lastSeen.current > 90_000) socketRef.current.close();
      else if (!socketRef.current && reconnectRef.current === null) connect();
    };
    window.addEventListener(TASK_ACTIVITY_WATCH, watch);
    window.addEventListener('offline', offline); window.addEventListener('online', online);
    document.addEventListener('visibilitychange', check);
    const watchdog = window.setInterval(check, 30_000);
    return () => {
      disposed.current = true;
      cleanup();
      window.clearInterval(watchdog);
      window.removeEventListener(TASK_ACTIVITY_WATCH, watch);
      window.removeEventListener('offline', offline); window.removeEventListener('online', online);
      document.removeEventListener('visibilitychange', check);
    };
  }, [cleanup, connect, enabled, token]);

  return useMemo(
    () => ({
      status,
    }),
    [status],
  );
};
