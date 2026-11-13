import React, { useEffect, useState } from 'react';
import McpManagementPanel from '../components/McpManagementPanel';
import { useAuth } from '../hooks/useAuth';
import { useNavigation } from '../hooks/useNavigation';
import { getMcpManagement, saveMcpPolicy, emergencyDisableMcp, revokeMcpGrant } from '../services/mcpManagement';
import type { McpManagementSnapshot } from '../types/mcpManagement';

export default function McpManagement() {
  const { user } = useAuth();
  const { policy } = useNavigation();
  const [reload, setReload] = useState(0);
  const [result, setResult] = useState<{ identity: string; data?: McpManagementSnapshot; error?: string }>();
  const tenant = policy?.tenantId;
  const identity = JSON.stringify([user?.id, user?.role, tenant, reload]);
  useEffect(() => {
    if (!user || !tenant) return;
    const controller = new AbortController();
    void getMcpManagement(controller.signal, tenant).then(data => {
      if (!controller.signal.aborted) setResult({ identity, data });
    }).catch(error => {
      if (controller.signal.aborted) return;
      const status = error?.response?.status;
      setResult({ identity, error: status === 403 ? 'Your current role or organization policy does not allow MCP management.'
        : status === 401 ? 'Your session could not be verified. Sign in again.'
        : 'MCP management is unavailable. No configuration changes were made.' });
    });
    return () => controller.abort();
  }, [identity, tenant, user?.id, user?.role]);
  // Never render another account's data or keep stale success after a failed reload.
  if (!result || result.identity !== identity) return <p role="status" className="p-5 text-text-secondary">Loading MCP management…</p>;
  if (result.error || !result.data) return <div role="alert" className="space-y-3 rounded-xl border border-border-color bg-surface p-5"><h2 className="text-xl font-semibold">MCP Management</h2><p>{result.error}</p><button type="button" className="rounded-lg border border-border-color px-4 py-2" onClick={() => setReload(value => value + 1)}>Retry</button></div>;
  return <McpManagementPanel key={identity} data={result.data} onReload={() => setReload(value => value + 1)}
    onSave={saveMcpPolicy} onEmergency={emergencyDisableMcp} onRevoke={revokeMcpGrant} />;
}
