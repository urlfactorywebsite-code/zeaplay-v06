import React, { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { previewMcpConsent, decideMcpConsent, McpConsentPreview } from '../services/mcpConsent';

export default function McpConsent() {
  const embedded = typeof window !== 'undefined' && window.self !== window.top;
  const { search } = useLocation();
  const { user } = useAuth();
  const request = new URLSearchParams(search).get('request') || '';
  const identity = JSON.stringify([request, user?.id, user?.role]);
  const [state, setState] = useState<{ identity: string; preview?: McpConsentPreview; error?: boolean }>();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (embedded) return;
    const controller = new AbortController();
    void previewMcpConsent(request, controller.signal).then(preview => {
      if (!controller.signal.aborted) setState({ identity, preview });
    }).catch(() => { if (!controller.signal.aborted) setState({ identity, error: true }); });
    return () => controller.abort();
  }, [identity, request, embedded]);
  const value = state?.identity === identity ? state : undefined;
  async function decide(approve: boolean) {
    if (embedded || !value?.preview || busy) return;
    setBusy(true);
    try { window.location.assign(await decideMcpConsent(request, value.preview.csrf, approve)); }
    catch { setState({ identity, error: true }); setBusy(false); }
  }
  return <section className="mx-auto max-w-2xl space-y-5 rounded-xl border border-border-color bg-surface p-5 text-text-primary shadow-sm sm:p-8">
    <h1 className="text-2xl font-semibold">Authorize isolated MCP access</h1>
    <p className="text-sm text-text-secondary">This test client will act as your current ZeaPlay account. Existing task visibility and tenant permissions apply to every call. External production integrations remain unavailable.</p>
    {embedded ? <p role="alert">Consent cannot be approved in an embedded page. Open this request directly in your browser.</p> : !value ? <p role="status">Verifying consent request…</p> : value.error || !value.preview ? <p role="alert">Consent request is unavailable, expired or no longer authorized. Return to the client to start again.</p> : <>
      <dl className="space-y-3 break-words"><div><dt className="text-text-secondary">Client</dt><dd>{value.preview.client_name}</dd></div><div><dt className="text-text-secondary">Your account</dt><dd>{user?.name}</dd></div><div><dt className="text-text-secondary">Organization</dt><dd className="break-all">{value.preview.tenant_context}</dd></div><div><dt className="text-text-secondary">Requested scopes</dt><dd>{value.preview.scopes.join(', ')}</dd></div></dl>
      <p className="font-medium">Read-only tools permitted by current policy</p><ul className="list-disc space-y-2 pl-5 text-sm">{value.preview.tools.map(tool => <li key={tool} className="break-all">{tool}</li>)}</ul>
      <p className="text-sm text-text-secondary">Access ends when the linked session or grant expires or is revoked. Administrators can disable tools or revoke grants.</p>
      <div className="flex flex-wrap gap-3"><button type="button" disabled={busy} onClick={() => void decide(false)} className="rounded-lg border border-border-color px-4 py-2 disabled:opacity-50">Deny</button><button type="button" disabled={busy} onClick={() => void decide(true)} className="rounded-lg bg-primary px-4 py-2 text-white disabled:opacity-50">Approve read-only access</button></div>
      {busy && <p role="status">Confirming your decision…</p>}
    </>}
  </section>;
}
