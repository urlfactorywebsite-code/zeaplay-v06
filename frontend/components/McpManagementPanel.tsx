import React, { useState } from 'react';
import { LockKeyhole, RefreshCw } from 'lucide-react';
import type { McpManagementSnapshot, McpPolicyDraft } from '../types/mcpManagement';
import { useUnsavedChanges } from '../hooks/useUnsavedChanges';

export const MCP_SECTIONS = ['Overview', 'Tools', 'Connections', 'Permissions', 'Security', 'Activity Logs'] as const;
type Section = typeof MCP_SECTIONS[number];
const CLIENTS = ['ChatGPT', 'Claude', 'Cursor', 'VS Code', 'Other MCP-compatible clients'];
const buttonStyle = 'rounded-lg border border-border-color px-4 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50';

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="min-w-0 rounded-lg border border-border-color p-4"><dt className="text-sm text-text-secondary">{label}</dt><dd className="mt-2 break-words font-semibold text-text-primary">{children}</dd></div>;
}

export default function McpManagementPanel({ data, onReload, onSave, onEmergency, onRevoke, initialSection = 'Overview' }: {
  data: McpManagementSnapshot; onReload: () => void; initialSection?: Section;
  onSave?: (draft: McpPolicyDraft) => Promise<void>; onEmergency?: (reason: string) => Promise<void>;
  onRevoke?: (id: string) => Promise<void>;
}) {
  const [section, setSection] = useState<Section>(initialSection);
  const { overview, configuration, security } = data;
  const isolated = configuration.available && configuration.isolated === true;
  const [enabled, setEnabled] = useState(configuration.enabled);
  const [tools, setTools] = useState(configuration.allowed_tool_ids);
  const [roles, setRoles] = useState(configuration.allowed_roles);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const dirty = enabled !== configuration.enabled || JSON.stringify(tools) !== JSON.stringify(configuration.allowed_tool_ids)
    || JSON.stringify(roles) !== JSON.stringify(configuration.allowed_roles) || reason !== '';
  const confirmDiscard = useUnsavedChanges(dirty);
  const editable = isolated && !!onSave && !busy && !configuration.emergency_disabled;
  const toggle = (values: string[], value: string) => values.includes(value) ? values.filter(item => item !== value) : [...values, value];
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); onReload(); }
    catch { setError('Change was not confirmed. Reload status before retrying. Your session and current server policy remain authoritative.'); }
    finally { setBusy(false); }
  }
  return <div className="min-w-0 space-y-5 text-text-primary">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h2 className="text-2xl font-semibold">MCP Management</h2><p className="mt-1 text-sm text-text-secondary">Manage your organization's MCP readiness and approved read-only tools.</p></div>
      <button type="button" disabled={busy} onClick={() => { if (confirmDiscard()) onReload(); }} className={`${buttonStyle} flex items-center gap-2`}><RefreshCw className="h-4 w-4" aria-hidden="true" />Reload status</button>
    </header>
    <div className="flex items-start gap-3 rounded-xl border border-amber-500/50 bg-amber-500/5 p-4 text-sm" role="note">
      <LockKeyhole className="h-5 w-5 shrink-0 text-amber-500" aria-hidden="true" />
      <div><p className="font-semibold">Remote MCP access is blocked</p><p className="mt-1 text-text-secondary">{isolated ? 'OAuth and delegated consent are configured for isolated testing only. External production integrations and deployment remain unavailable.' : `OAuth, delegated consent and deployment approval are pending. ${configuration.blocker}`}</p></div>
    </div>
    {error && <p role="alert" className="rounded-lg border border-red-500/40 p-3 text-sm">{error}</p>}
    {busy && <p role="status" className="text-sm">Waiting for server confirmation…</p>}
    <nav aria-label="MCP sections" className="flex flex-wrap gap-2">
      {MCP_SECTIONS.map(name => <button key={name} type="button" aria-pressed={section === name} aria-controls="mcp-section" onClick={() => setSection(name)} className={`${buttonStyle} ${section === name ? 'border-primary bg-primary/15 text-primary' : 'bg-surface text-text-secondary hover:text-text-primary'}`}>{name}</button>)}
    </nav>
    <section id="mcp-section" aria-labelledby="mcp-section-title" className="min-w-0 space-y-4 rounded-xl border border-border-color bg-surface p-4 shadow-sm sm:p-6">
      <h3 id="mcp-section-title" className="text-lg font-semibold">{section}</h3>
      {section === 'Overview' && <>
        <dl className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <Fact label="MCP service status">{isolated ? 'Configured for isolated OAuth only' : 'Not configured for remote access'}</Fact>
          <Fact label="Available tool catalog">{overview.total_tools}</Fact>
          <Fact label="Enabled tools">{overview.enabled_tools}</Fact>
          <Fact label="Active connections">{overview.active_connections ?? 'Unavailable'}</Fact>
          <Fact label="Security mode">{overview.security_mode}</Fact>
          <Fact label="MCP endpoint">{overview.endpoint ?? 'Not configured'}</Fact>
        </dl>
        <p className="text-sm text-text-secondary">Service health is not monitored. No live health check has been performed. The five tools currently support offline and isolated testing only.</p>
      </>}
      {section === 'Tools' && <>
        <p id="mcp-tools-blocker" className="text-sm text-text-secondary">{isolated ? 'Only these five read-only tools are approved. Changes are drafts until saved in Permissions. Server policy and existing task permissions apply to every call.' : 'Only these five tools are approved. Tenant enable/disable controls are unavailable until policy storage and server enforcement are approved.'}</p>
        <ul className="space-y-3">{data.tools.map(tool => <li key={tool.id} className="min-w-0 rounded-lg border border-border-color p-4">
          <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h4 className="font-medium">{tool.name}</h4><code className="block break-all text-xs text-text-secondary">{tool.id}</code></div><span className="rounded-full bg-primary/10 px-3 py-1 text-xs text-primary">Read-only</span></div>
          <p className="mt-2 text-sm text-text-secondary">{tool.description}</p>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm"><span className="text-text-secondary">Scope: {tool.scope}</span><label className="flex items-center gap-2"><input type="checkbox" checked={tools.includes(tool.id)} disabled={!editable} onChange={() => { if (editable) setTools(toggle(tools, tool.id)); }} aria-describedby="mcp-tools-blocker" />Enable {tool.name}</label></div>
        </li>)}</ul>
      </>}
      {section === 'Connections' && <>
        <p className="text-sm text-text-secondary">{data.connections.reason} {data.connections.available ? `Showing up to 50 of ${data.connections.total} saved grants. Active means currently authorized, not an open network connection.` : 'Connection inventory is unavailable; no live connections are reported.'}</p>
        {data.connections.available && <ul className="space-y-3" aria-label="Saved OAuth grants">{data.connections.items.length === 0 && <li>No OAuth grants recorded.</li>}{data.connections.items.map(item => <li key={item.id} className="min-w-0 space-y-2 rounded-lg border border-border-color p-4 text-sm"><p className="break-all font-medium">{item.client_id} · {item.status}</p><p className="break-all text-text-secondary">User: {item.user_id}</p><p>Scopes: {item.scopes.join(', ')}</p><p className="break-words">Expires: {item.expires_at}</p><button type="button" className={buttonStyle} disabled={busy || !onRevoke || !!item.revoked_at} onClick={() => void run(() => onRevoke!(item.id))}>Revoke grant</button></li>)}</ul>}
        <ul className="grid gap-3 sm:grid-cols-2">{CLIENTS.map(client => <li key={client} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border-color p-4"><span className="font-medium">{client}</span><span className="text-sm text-text-secondary">Setup pending</span><button type="button" disabled className={buttonStyle} aria-label={`Connect ${client}: unavailable`}>Connect unavailable</button></li>)}</ul>
        <p className="text-sm text-text-secondary">No production connections can be created. MCP does not accept pasted API keys or ZeaPlay session tokens.</p>
      </>}
      {section === 'Permissions' && <>
        <p id="mcp-policy-blocker" className="text-sm text-text-secondary">{isolated ? `Isolated tenant policy, revision ${configuration.revision}. Changes take effect only after server confirmation. ${configuration.emergency_disabled ? 'Emergency lock is active; recovery requires a separately reviewed procedure.' : ''}` : `${configuration.blocker} These are safe disabled defaults, not saved tenant preferences.`}</p>
        <fieldset disabled={!editable} aria-describedby="mcp-policy-blocker" className="space-y-4 rounded-lg border border-border-color p-4">
          <legend className="px-2 font-medium">Tenant policy</legend>
          <label className="flex items-center gap-2"><input type="checkbox" checked={enabled} onChange={event => { if (editable) setEnabled(event.target.checked); }} />Enable tenant MCP</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked disabled readOnly />Read-only mode (required)</label>
          <p className="text-sm text-text-secondary">Roles allowed to use MCP tools</p>
          <div className="flex flex-wrap gap-4">{['user', 'manager', 'admin', 'owner'].map(role => <label key={role} className="flex items-center gap-2 capitalize"><input type="checkbox" checked={roles.includes(role)} onChange={() => { if (editable) setRoles(toggle(roles, role)); }} />{role}</label>)}</div>
          {isolated && <label className="block text-sm">Reason for policy change<textarea value={reason} onChange={event => setReason(event.target.value)} maxLength={500} className="mt-2 block w-full rounded-lg border border-border-color bg-surface p-3" /></label>}
          <button type="button" disabled={!editable || !reason.trim()} className={buttonStyle} onClick={() => void run(() => onSave!({ enabled, read_only: true, allowed_tool_ids: tools, allowed_roles: roles, reason: reason.trim(), expected_revision: configuration.revision! }))}>{isolated ? 'Save isolated policy' : 'Save policy unavailable'}</button>
        </fieldset>
        <p className="text-sm text-text-secondary">Only authenticated Owners and Admins can access management. Tool permissions cannot broaden existing task visibility or tenant access. Tool-level controls appear in Tools.</p>
        <div className="rounded-lg border border-red-500/40 p-4"><h4 className="font-medium">Tenant emergency disable</h4><p className="mt-2 text-sm text-text-secondary">{isolated ? 'Disables all tool execution for this tenant. Ordinary policy updates cannot clear the emergency lock.' : 'A durable emergency switch is unavailable until policy storage and execution enforcement exist. Remote access is already blocked; no emergency stop has been recorded.'}</p><button type="button" disabled={!isolated || busy || !onEmergency || !!configuration.emergency_disabled} className={`${buttonStyle} mt-3`} aria-describedby="mcp-policy-blocker" onClick={() => void run(() => onEmergency!('Administrator emergency disable'))}>{isolated ? 'Emergency disable tenant MCP' : 'Emergency disable unavailable'}</button></div>
      </>}
      {section === 'Security' && <>
        <dl className="grid gap-3 sm:grid-cols-2">
          <Fact label="Management authentication">{security.management_authentication}</Fact>
          <Fact label="MCP authentication readiness">{security.mcp_authentication}</Fact>
          <Fact label="OAuth / delegation">{security.oauth_delegation}</Fact>
          <Fact label="Credential handling">{security.credential_handling}</Fact>
          <Fact label="Remote connections">{security.remote_connections}</Fact>
        </dl>
        <h4 className="font-medium">Security restrictions</h4><ul className="list-disc space-y-2 pl-5 text-sm text-text-secondary">{security.restrictions.map(restriction => <li key={restriction}>{restriction}</li>)}</ul>
      </>}
      {section === 'Activity Logs' && <div className="rounded-lg border border-dashed border-border-color p-6"><h4 className="font-medium">{data.activity.available ? 'Recent MCP audit events' : 'MCP activity unavailable'}</h4><p className="mt-2 text-sm text-text-secondary">{data.activity.reason}</p>{data.activity.available ? <ul className="mt-4 space-y-3">{data.activity.items.length === 0 && <li>No MCP events recorded.</li>}{data.activity.items.map(item => <li key={item.id} className="min-w-0 break-words rounded-lg border border-border-color p-3 text-sm"><p>{item.event} · {item.outcome}</p><p>{item.occurred_at}</p>{item.tool_id && <p className="break-all">{item.tool_id}</p>}<p className="break-all text-text-secondary">Correlation: {item.correlation_id}</p></li>)}</ul> : <p className="mt-2 text-sm text-text-secondary">General ZeaPlay audit records are not presented as MCP activity.</p>}</div>}
    </section>
  </div>;
}
