import api from '../services/mockApi';

export const BOT_FALLBACK_REPLY = "Sorry, I couldn't process that. Please try again.";
export const BOT_ERROR_MESSAGE = "I'm having trouble connecting right now. Please try again later.";
const candidateKeys = ['reply', 'message', 'output', 'text', 'response'];

export const generateSessionId = (): string => (
    Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15)
);

export const extractReply = (payload: unknown): string | undefined => {
    if (!payload) {
        return undefined;
    }

    if (typeof payload === 'string') {
        const trimmed = payload.trim();
        return trimmed.length > 0 ? trimmed : undefined;
    }

    if (Array.isArray(payload)) {
        for (const item of payload) {
            const result = extractReply(item);
            if (result) {
                return result;
            }
        }
        return undefined;
    }

    if (typeof payload === 'object') {
        const record = payload as Record<string, unknown>;
        for (const key of candidateKeys) {
            if (key in record) {
                const result = extractReply(record[key]);
                if (result) {
                    return result;
                }
            }
        }
        if ('data' in record) {
            const result = extractReply(record['data']);
            if (result) {
                return result;
            }
        }
    }

    return undefined;
};

export interface SendAiMessageOptions {
    message: string;
    sessionId?: string;
    payload?: Record<string, unknown>;
    signal?: AbortSignal;
}
export const sendAiMessage = async ({ message, sessionId, payload, signal }: SendAiMessageOptions): Promise<string> => {
    const result = await api.sendAiMessage({ message, sessionId, payload }, signal);
    return extractReply(result) ?? BOT_FALLBACK_REPLY;
};
