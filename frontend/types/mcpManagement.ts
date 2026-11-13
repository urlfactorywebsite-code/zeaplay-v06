export interface McpManagementSnapshot {
  tenant_context: string;
  configuration: {
    available: boolean; persisted: boolean; blocker: string; enabled: boolean;
    read_only: true; allowed_tool_ids: string[]; allowed_roles: string[];
    emergency_disabled: boolean | null; revision?: number; isolated?: true;
  };
  overview: {
    service_status: 'not_configured' | 'isolated_configured'; health_status: 'not_monitored'; last_checked_at: null;
    total_tools: number; enabled_tools: number; active_connections: number | null;
    security_mode: string; endpoint: string | null; remote_access_enabled: false;
  };
  tools: { id: string; name: string; description: string; scope: string; read_only: true; enabled: boolean; available: boolean }[];
  connections: { available: boolean; items: { id: string; client_id: string; user_id: string; scopes: string[];
    status: 'active' | 'blocked' | 'expired' | 'revoked'; created_at: string; expires_at: string; revoked_at: string | null }[]; reason: string; total?: number };
  security: {
    management_authentication: string; mcp_authentication: string; oauth_delegation: string;
    credential_handling: string; remote_connections: string; restrictions: string[];
  };
  activity: { available: boolean; items: { id: string; event: string; outcome: string; tool_id: string | null;
    grant_id: string | null; correlation_id: string; occurred_at: string }[]; reason: string };
}

export interface McpPolicyDraft { enabled: boolean; read_only: true; allowed_tool_ids: string[]; allowed_roles: string[]; reason: string; expected_revision: number }
