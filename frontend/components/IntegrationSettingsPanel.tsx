import React, { useEffect, useState } from 'react';
import api from '../services/mockApi';
import { MultipleSmtpConfig, OAuthConfig } from '../types';
import { useUnsavedChanges } from '../hooks/useUnsavedChanges';

type Kind = 'smtp' | 'oauth';
type Entry = MultipleSmtpConfig | OAuthConfig;
const emptyForm = () => ({ name: '', host: '', port: '587', username: '', password: '', encryption: 'tls', notificationTypes: 'task_notifications', redirectUrl: '', scopes: 'tasks.read', n8nIntegration: false });
const fieldClass = 'mt-1 w-full min-w-0 rounded-md border border-border-color bg-background px-3 py-2 text-text-primary';
const buttonClass = 'rounded-lg border border-border-color px-3 py-2 text-sm transition hover:border-primary focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50';

// The existing service owns all payload conversion, authorization and requests.
// Credentials returned by the server never populate editable password fields.
const IntegrationSettingsPanel: React.FC<{ kind: Kind }> = ({ kind }) => {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [baseline, setBaseline] = useState(() => JSON.stringify(emptyForm()));
  const [editingId, setEditingId] = useState<string | number | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [testAddress, setTestAddress] = useState('');
  const [revealedId, setRevealedId] = useState<string | number | null>(null);
  const confirmDiscard = useUnsavedChanges(JSON.stringify(form) !== baseline || busy);
  const isSmtp = kind === 'smtp';

  useEffect(() => {
    let active = true;
    setLoading(true);
    (isSmtp ? api.getMultipleSmtpConfigs() : api.getOAuthConfigs())
      .then((data) => { if (active) setEntries(data); })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : 'Unable to load configuration.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [isSmtp]);

  const loadEntry = (entry?: Entry) => {
    if (!confirmDiscard()) return;
    const next = emptyForm();
    if (entry) {
      next.name = entry.name;
      if ('host' in entry) {
        Object.assign(next, { host: entry.host, port: String(entry.port), username: entry.username, encryption: entry.encryption, notificationTypes: entry.notification_types.join(', ') });
      } else {
        Object.assign(next, { redirectUrl: entry.redirect_url, scopes: entry.scopes.join(', '), n8nIntegration: entry.n8n_integration });
      }
    }
    setForm(next); setBaseline(JSON.stringify(next)); setEditingId(entry?.id ?? null); setRevealedId(null); setError(''); setStatus('');
  };
  const runAction = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError(''); setStatus('');
    try { await action(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to save configuration.'); }
    finally { setBusy(false); }
  };
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.name.trim() || (isSmtp && (!form.host.trim() || !form.username.trim())) || (!isSmtp && !form.scopes.trim())) {
      setError('Complete all required configuration fields.');
      return;
    }
    await runAction(async () => {
      let saved: Entry;
      if (isSmtp) {
        const payload = { name: form.name.trim(), host: form.host.trim(), port: Number(form.port), username: form.username.trim(), encryption: form.encryption, notification_types: form.notificationTypes.split(',').map((value) => value.trim()).filter(Boolean), ...(form.password ? { password: form.password } : {}) };
        saved = editingId ? await api.updateMultipleSmtpConfig(String(editingId), payload) : await api.createMultipleSmtpConfig(payload);
      } else {
        const payload = { name: form.name.trim(), redirect_url: form.redirectUrl.trim(), scopes: form.scopes.split(',').map((value) => value.trim()).filter(Boolean), n8n_integration: form.n8nIntegration };
        saved = editingId ? await api.updateOAuthConfig(editingId, payload) : await api.createOAuthConfig(payload);
      }
      setEntries((previous) => [saved, ...previous.filter((item) => item.id !== saved.id)]);
      const next = { ...form, password: '' };
      setForm(next); setBaseline(JSON.stringify(next)); setEditingId(saved.id); setStatus('Configuration saved.');
    });
  };
  const remove = (entry: Entry) => {
    if (!confirmDiscard() || !window.confirm(`Delete ${entry.name}?`)) return;
    void runAction(async () => {
      if (isSmtp) await api.deleteMultipleSmtpConfig(String(entry.id)); else await api.deleteOAuthConfig(entry.id);
      setEntries((previous) => previous.filter((item) => item.id !== entry.id));
      if (editingId === entry.id) { const next = emptyForm(); setForm(next); setBaseline(JSON.stringify(next)); setEditingId(null); }
      setStatus('Configuration deleted.');
    });
  };
  return (
    <section className="min-w-0 space-y-5 rounded-xl border border-border-color bg-surface p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">{isSmtp ? 'SMTP configuration' : 'OAuth configuration'}</h2>
        <button type="button" className={buttonClass} disabled={busy} onClick={() => loadEntry()}>New configuration</button>
      </div>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      {status && <p role="status" className="text-sm text-green-400">{status}</p>}
      {loading ? <p role="status">Loading configuration...</p> : entries.length === 0 ? <p className="text-text-secondary">No configuration yet.</p> : (
        <ul className="space-y-2">
          {entries.map((entry) => <li key={entry.id} className="flex min-w-0 flex-wrap items-center gap-3 rounded-lg border border-border-color p-3">
            <span className="min-w-0 flex-1 break-words">{entry.name}</span>
            <button type="button" className={buttonClass} disabled={busy} onClick={() => loadEntry(entry)} aria-label={`Edit ${entry.name}`}>Edit</button>
            <button type="button" className={buttonClass} disabled={busy} onClick={() => remove(entry)} aria-label={`Delete ${entry.name}`}>Delete</button>
            {'client_id' in entry && <>
              <span className="w-full break-all text-xs text-text-secondary">Client ID: {entry.client_id}</span>
              <button type="button" className={buttonClass} onClick={() => setRevealedId(revealedId === entry.id ? null : entry.id)}>{revealedId === entry.id ? 'Hide credentials' : 'Reveal credentials'}</button>
              {revealedId === entry.id && <dl className="w-full break-all text-sm"><dt>Client secret</dt><dd>{entry.client_secret}</dd><dt>API key</dt><dd>{entry.api_key || 'Not configured'}</dd></dl>}
              <button type="button" className={buttonClass} disabled={busy} onClick={() => {
                if (!window.confirm(`Rotate credentials for ${entry.name}? Existing integrations must be updated.`)) return;
                void runAction(async () => { const updated = await api.rotateOAuthConfig(entry.id, { rotate_client_secret: true, rotate_api_key: true }); setEntries((previous) => previous.map((item) => item.id === entry.id ? updated : item)); setRevealedId(null); setStatus('Credentials rotated.'); });
              }}>Rotate credentials</button>
            </>}
          </li>)}
        </ul>
      )}
      <form onSubmit={save} className="grid min-w-0 gap-4 sm:grid-cols-2">
        <label className="min-w-0 text-sm">Configuration name<input className={fieldClass} required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
        {isSmtp ? <>
          <label className="min-w-0 text-sm">SMTP host<input className={fieldClass} required value={form.host} onChange={(event) => setForm({ ...form, host: event.target.value })} /></label>
          <label className="min-w-0 text-sm">Port<input className={fieldClass} type="number" min={1} max={65535} required value={form.port} onChange={(event) => setForm({ ...form, port: event.target.value })} /></label>
          <label className="min-w-0 text-sm">Username<input className={fieldClass} required autoComplete="username" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} /></label>
          <label className="min-w-0 text-sm">Password{editingId ? ' (leave blank to keep existing)' : ''}<input className={fieldClass} type="password" autoComplete="new-password" required={!editingId} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /></label>
          <label className="min-w-0 text-sm">Encryption<select className={fieldClass} value={form.encryption} onChange={(event) => setForm({ ...form, encryption: event.target.value })}><option value="tls">TLS</option><option value="ssl">SSL</option><option value="none">None</option></select></label>
          <label className="min-w-0 text-sm sm:col-span-2">Notification types (comma separated)<input className={fieldClass} value={form.notificationTypes} onChange={(event) => setForm({ ...form, notificationTypes: event.target.value })} /></label>
        </> : <>
          <label className="min-w-0 text-sm">Redirect URL<input className={fieldClass} type="url" required value={form.redirectUrl} onChange={(event) => setForm({ ...form, redirectUrl: event.target.value })} /></label>
          <label className="min-w-0 text-sm sm:col-span-2">Scopes (comma separated)<input className={fieldClass} required value={form.scopes} onChange={(event) => setForm({ ...form, scopes: event.target.value })} /></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.n8nIntegration} onChange={(event) => setForm({ ...form, n8nIntegration: event.target.checked })} />n8n integration</label>
        </>}
        <div className="sm:col-span-2"><button type="submit" className={buttonClass} disabled={busy || loading}>{busy ? 'Saving...' : 'Save configuration'}</button></div>
      </form>
      {isSmtp && editingId && <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
        event.preventDefault();
        void runAction(async () => { await api.sendSmtpTestEmail(String(editingId), { notification_type: form.notificationTypes.split(',')[0].trim(), to_address: testAddress }); setStatus('Test email requested.'); });
      }}>
        <label className="min-w-0 flex-1 text-sm">Test recipient<input type="email" required className={fieldClass} value={testAddress} onChange={(event) => setTestAddress(event.target.value)} /></label>
        <button type="submit" className={buttonClass} disabled={busy}>Send test email</button>
      </form>}
    </section>
  );
};

export default IntegrationSettingsPanel;
