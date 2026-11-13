import type { Socket } from 'socket.io-client';
import { sessionIdentity } from './sessionRefresh';

type Credential = { access_token: string; subject: string; expires_at: string };
type ConnectionOptions = {
    subject: string;
    isCurrent: () => boolean;
    getCredential: () => Promise<Credential>;
    openSocket: (token: string) => Socket;
    onSocket: (socket: Socket) => void;
    onState: (state: 'connecting' | 'connected' | 'offline', error?: string) => void;
    now?: () => number;
    schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>;
    cancel?: (timer: ReturnType<typeof setTimeout>) => void;
};

// Identity comparison survives a normal access-token refresh, but not logout or
// switching user/tenant. This is a client race guard, never server authorization.
export function presenceIdentity(token: string | null): string | null {
    return sessionIdentity(token);
}

export function createPresenceConnection(options: ConnectionOptions) {
    const now = options.now ?? Date.now;
    const schedule = options.schedule ?? setTimeout;
    const cancel = options.cancel ?? clearTimeout;
    let stopped = false;
    let generation = 0;
    let socket: Socket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let state: 'connecting' | 'connected' | 'offline' = 'offline';
    let lastAttempt = -Infinity;

    const clear = () => {
        if (timer !== undefined) cancel(timer);
        timer = undefined;
        socket?.removeAllListeners();
        socket?.disconnect();
        socket = undefined;
    };
    const report = (next: typeof state, error?: string) => {
        state = next;
        options.onState(next, error);
    };
    const plan = (callback: () => void, delay: number) => {
        if (timer !== undefined) cancel(timer);
        timer = schedule(callback, delay);
    };
    const start = async () => {
        if (stopped || !options.isCurrent()) return;
        const attempt = ++generation;
        lastAttempt = now();
        clear();
        report('connecting');
        const current = () => !stopped && attempt === generation && options.isCurrent();
        const unavailable = () => {
            if (!current()) return;
            report('offline', 'Presence offline');
            plan(() => { void start(); }, 5000);
        };
        try {
            // Always request the dedicated credential; never fall back to API JWTs.
            const credential = await options.getCredential();
            if (!current()) return;
            const expires = Date.parse(credential.expires_at);
            if (credential.subject !== options.subject || !credential.access_token
                || !Number.isFinite(expires) || expires <= now()) {
                throw new Error('Invalid presence credential');
            }
            socket = options.openSocket(credential.access_token);
            socket.on('connect', () => { if (current()) report('connected'); });
            socket.on('disconnect', unavailable);
            socket.on('connect_error', unavailable);
            options.onSocket(socket);
            // Re-authenticate before expiry with current backend membership/status.
            plan(() => { void start(); }, Math.max(1000, expires - now() - 30000));
        } catch { unavailable(); }
    };
    return {
        start,
        reconnect() {
            if (state === 'offline' && now() - lastAttempt >= 5000) void start();
        },
        stop() { stopped = true; generation++; clear(); },
    };
}
