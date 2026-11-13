import { z } from 'zod';
import type { McpManagementSnapshot } from '../types/mcpManagement';

const toolIds = ['zeaplay_list_tasks', 'zeaplay_get_task', 'zeaplay_list_overdue_tasks',
  'zeaplay_list_subtasks', 'zeaplay_get_workload_summary'] as const;
const text = z.string().min(1).max(1000);
const empty = z.array(z.never()).length(0);
const scope = z.enum(['tasks:read', 'workload:read']);
const roles = z.array(z.enum(['user', 'manager', 'admin', 'owner'])).max(4).refine(items => new Set(items).size === items.length);
const allowed = z.array(z.enum(toolIds)).max(5).refine(items => new Set(items).size === items.length);
const time = z.iso.datetime({ offset: true });
const tool = z.object({
  id: z.enum(toolIds), name: text, description: text,
  scope,
  read_only: z.literal(true), enabled: z.boolean(), available: z.boolean(),
}).strict().refine(value => value.scope === (value.id === 'zeaplay_get_workload_summary' ? 'workload:read' : 'tasks:read'));

// Only disabled defaults or the explicit isolated contract are accepted.
const snapshot = z.object({
  tenant_context: z.uuid(),
  configuration: z.union([z.object({
    available: z.literal(false), persisted: z.literal(false), blocker: text,
    enabled: z.literal(false), read_only: z.literal(true), allowed_tool_ids: empty,
    allowed_roles: empty, emergency_disabled: z.null(),
  }).strict(), z.object({ available: z.literal(true), persisted: z.boolean(), blocker: z.literal(''),
    enabled: z.boolean(), read_only: z.literal(true), allowed_tool_ids: allowed, allowed_roles: roles,
    emergency_disabled: z.boolean(), revision: z.number().int().nonnegative(), isolated: z.literal(true),
  }).strict()]),
  overview: z.object({
    service_status: z.enum(['not_configured', 'isolated_configured']), health_status: z.literal('not_monitored'),
    last_checked_at: z.null(), total_tools: z.literal(5), enabled_tools: z.number().int().min(0).max(5),
    active_connections: z.number().int().nonnegative().nullable(), security_mode: text,
    endpoint: z.string().regex(/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}\/mcp$/).nullable(), remote_access_enabled: z.literal(false),
  }).strict(),
  tools: z.array(tool).length(5).refine(items => new Set(items.map(item => item.id)).size === 5),
  connections: z.union([z.object({ available: z.literal(false), items: empty, reason: text }).strict(),
    z.object({ available: z.literal(true), reason: text, total: z.number().int().nonnegative(), items: z.array(z.object({
      id: z.uuid(), client_id: z.string().min(1).max(128), user_id: z.string().min(1).max(36), scopes: z.array(scope).max(2),
      status: z.enum(['active','blocked','expired','revoked']), created_at: time, expires_at: time, revoked_at: time.nullable(),
    }).strict()).max(50) }).strict()]),
  security: z.object({
    management_authentication: text, mcp_authentication: text, oauth_delegation: text,
    credential_handling: text, remote_connections: text,
    restrictions: z.array(text).min(1).max(20),
  }).strict(),
  activity: z.union([z.object({ available: z.literal(false), items: empty, reason: text }).strict(),
    z.object({ available: z.literal(true), reason: text, items: z.array(z.object({ id: z.uuid(), event: text, outcome: text,
      tool_id: z.enum(toolIds).nullable(), grant_id: z.uuid().nullable(), correlation_id: z.uuid(), occurred_at: time,
    }).strict()).max(50) }).strict()]),
}).strict().refine(value => {
  const c = value.configuration, o = value.overview;
  const effective = c.available && c.enabled && !c.emergency_disabled;
  if (o.enabled_tools !== (effective ? c.allowed_tool_ids.length : 0)) return false;
  const selected = new Set<string>(c.allowed_tool_ids);
  if (!value.tools.every(t => t.enabled === selected.has(t.id) && t.available === (effective && t.enabled))) return false;
  if (!c.available) return o.service_status === 'not_configured' && o.endpoint === null && o.active_connections === null
    && o.security_mode === 'Read-only / remote access blocked' && !value.connections.available && !value.activity.available;
  return o.service_status === 'isolated_configured' && o.endpoint !== null && o.active_connections !== null
    && o.security_mode === 'Read-only / isolated OAuth' && value.connections.available && value.activity.available;
});

export function validateMcpManagementResponse(data: unknown, expectedTenant: string): McpManagementSnapshot {
  const parsed = snapshot.safeParse(data);
  // Do not expose validation input, extra fields or server credentials in errors.
  if (!parsed.success) throw new Error('MCP configuration response is unavailable or invalid');
  if (parsed.data.tenant_context !== expectedTenant) throw new Error('MCP tenant context changed');
  // The project disables strictNullChecks, which makes Zod union properties
  // appear optional in TypeScript. Runtime validation above checks every field.
  return parsed.data as McpManagementSnapshot;
}
