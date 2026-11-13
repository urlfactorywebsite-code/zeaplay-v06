import { useEffect, useMemo, useState } from 'react';
import { io } from 'socket.io-client';

import { useAuth } from './useAuth';
import { getAccessToken } from '../services/tokenStorage';
import api from '../services/mockApi';
import { createPresenceConnection, presenceIdentity } from '../services/presenceConnection';

type PresenceState = {
    onlineUserIds: Set<string>;
    status: 'connected' | 'connecting' | 'offline';
    error?: string;
};

const PRESENCE_PING_INTERVAL_MS = 15000;

const readRuntimePresenceUrl = (): string => {
    if (typeof window === 'undefined') {
        return '';
    }
    const runtimeConfig = (window as typeof window & {
        __RUNTIME_CONFIG__?: { PRESENCE_URL?: string };
    }).__RUNTIME_CONFIG__;
    if (!runtimeConfig?.PRESENCE_URL || typeof runtimeConfig.PRESENCE_URL !== 'string') {
        return '';
    }
    return runtimeConfig.PRESENCE_URL.trim();
};

const resolvePresenceUrl = (): string | null => {
    const runtimeUrl = readRuntimePresenceUrl();
    if (runtimeUrl) {
        return runtimeUrl;
    }
    const envUrl = import.meta.env.VITE_PRESENCE_URL;
    if (envUrl && typeof envUrl === 'string') {
        return envUrl;
    }
    if (typeof window === 'undefined') {
        return null;
    }
    const host = window.location.hostname;
    const isLocalhost = host === 'localhost' || host === '127.0.0.1';
    return isLocalhost ? 'http://localhost:7212' : null;
};

export const usePresence = (): PresenceState => {
    const { user } = useAuth();
    const [onlineUserIds, setOnlineUserIds] = useState<Set<string>>(new Set());
    const [status, setStatus] = useState<PresenceState['status']>('offline');
    const [error, setError] = useState<string | undefined>(undefined);
    useEffect(() => {
        const identity = presenceIdentity(getAccessToken());
        const presenceUrl = resolvePresenceUrl();
        setOnlineUserIds(new Set());
        if (!user || !identity || !presenceUrl) {
            setStatus('offline');
            setError(user && !presenceUrl ? 'Presence not configured' : undefined);
            return;
        }
        let pingTimer: ReturnType<typeof setInterval> | undefined;
        const connection = createPresenceConnection({
            subject: user.id,
            isCurrent: () => presenceIdentity(getAccessToken()) === identity,
            getCredential: () => api.getPresenceToken(),
            openSocket: token => io(presenceUrl, {
                auth: { token }, transports: ['websocket', 'polling'],
                reconnection: false, timeout: 10000,
            }),
            onState: (next, message) => {
                setStatus(next);
                setError(message);
                if (next !== 'connected') setOnlineUserIds(new Set());
            },
            onSocket: socket => {
                socket.on('connect', () => {
                    socket.emit('presence:get', (payload: { ok: boolean; users?: string[] }) => {
                        if (payload?.ok && presenceIdentity(getAccessToken()) === identity) {
                            setOnlineUserIds(new Set(payload.users ?? []));
                        }
                    });
                    socket.emit('presence:ping');
                });
                socket.on('presence:online', (payload: { userId: string }) => {
                    if (presenceIdentity(getAccessToken()) !== identity) return;
                    setOnlineUserIds(prev => new Set([...prev, payload.userId]));
                });
                socket.on('presence:offline', (payload: { userId: string }) => {
                    if (presenceIdentity(getAccessToken()) !== identity) return;
                    setOnlineUserIds(prev => {
                        const next = new Set(prev);
                        next.delete(payload.userId);
                        return next;
                    });
                });
                if (pingTimer !== undefined) clearInterval(pingTimer);
                pingTimer = setInterval(() => {
                    if (socket.connected && presenceIdentity(getAccessToken()) === identity) {
                        socket.emit('presence:ping');
                    }
                }, PRESENCE_PING_INTERVAL_MS);
            },
        });
        void connection.start();
        const handleVisibility = () => {
            if (document.visibilityState === 'visible') connection.reconnect();
        };
        window.addEventListener('focus', handleVisibility);
        document.addEventListener('visibilitychange', handleVisibility);
        return () => {
            connection.stop();
            if (pingTimer !== undefined) clearInterval(pingTimer);
            window.removeEventListener('focus', handleVisibility);
            document.removeEventListener('visibilitychange', handleVisibility);
        };
    }, [user]);

    return useMemo(
        () => ({
            onlineUserIds,
            status,
            error,
        }),
        [onlineUserIds, status, error],
    );
};
