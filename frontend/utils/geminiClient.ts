import api from '../services/mockApi';

export type AiGenerateRequest = {
    model: string;
    contents: string;
    config?: Record<string, unknown>;
};
const client = { models: { generateContent: (request: AiGenerateRequest) => api.generateAiContent(request) } };

// Keep the existing AI feature callbacks; provider authentication and key
// rotation now run on the server rather than in downloadable JavaScript.
export const withAiClient = <T,>(run: (ai: typeof client) => Promise<T>): Promise<T> => run(client);
