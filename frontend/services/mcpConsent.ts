import { z } from 'zod';
import { http } from './mockApi';

const preview = z.object({ request_id: z.uuid(), client_name: z.string().min(1).max(128), tenant_context: z.uuid(),
  scopes: z.array(z.enum(['tasks:read', 'workload:read'])).min(1).max(2), expires_at: z.iso.datetime({ offset: true }),
  csrf: z.string().regex(/^[A-Za-z0-9_-]{43}$/), tools: z.array(z.enum(['zeaplay_list_tasks', 'zeaplay_get_task',
    'zeaplay_list_overdue_tasks', 'zeaplay_list_subtasks', 'zeaplay_get_workload_summary'])).max(5),
}).strict();
export type McpConsentPreview = z.infer<typeof preview>;

export async function previewMcpConsent(requestId: string, signal: AbortSignal) {
  if (!z.uuid().safeParse(requestId).success) throw new Error('Invalid consent request');
  const { data } = await http.post(`/mcp-oauth/requests/${requestId}/preview`, {}, { signal, timeout: 10000, withCredentials: true });
  const parsed = preview.safeParse(data);
  if (!parsed.success || parsed.data.request_id !== requestId) throw new Error('Consent is unavailable');
  return parsed.data;
}

export async function decideMcpConsent(requestId: string, csrf: string, approve: boolean) {
  if (!z.uuid().safeParse(requestId).success || !/^[A-Za-z0-9_-]{43}$/.test(csrf)) throw new Error('Invalid consent request');
  const { data } = await http.post(`/mcp-oauth/requests/${requestId}/decision`, { approve, csrf }, { timeout: 10000, withCredentials: true });
  const result = z.object({ redirect_uri: z.string().max(4096) }).strict().safeParse(data);
  if (!result.success) throw new Error('Consent was not confirmed');
  const uri = new URL(result.data.redirect_uri);
  if (uri.protocol !== 'http:' || uri.hostname !== '127.0.0.1' || !uri.port || uri.username || uri.password || uri.hash) throw new Error('Invalid isolated callback');
  return uri.href;
}
