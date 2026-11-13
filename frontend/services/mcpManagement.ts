import { http } from './mockApi';
import type { McpManagementSnapshot, McpPolicyDraft } from '../types/mcpManagement';
import { validateMcpManagementResponse } from '../utils/mcpManagementResponse';

// Reuse session authentication/refresh. No client-selected tenant or credentials.
export async function getMcpManagement(signal: AbortSignal, expectedTenant: string): Promise<McpManagementSnapshot> {
  const { data } = await http.get<unknown>('/mcp-management', { signal, timeout: 10000 });
  return validateMcpManagementResponse(data, expectedTenant);
}

export async function saveMcpPolicy(draft: McpPolicyDraft) {
  await http.patch('/mcp-management/policy', draft, { timeout: 10000 });
}
export async function emergencyDisableMcp(reason: string) {
  await http.post('/mcp-management/emergency-disable', { reason }, { timeout: 10000 });
}
export async function revokeMcpGrant(id: string) {
  await http.post(`/mcp-oauth/grants/${encodeURIComponent(id)}/revoke`, {}, { timeout: 10000 });
}
