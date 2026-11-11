import React, { useEffect, useState } from 'react';
import api from '../services/mockApi';
import { useUnsavedChanges } from '../hooks/useUnsavedChanges';

const ProviderSettingsPanel: React.FC = () => {
  const [provider, setProvider] = useState('');
  const [baseline, setBaseline] = useState('');
  const [key, setKey] = useState('');
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  useUnsavedChanges(!loading && Boolean(key || provider !== baseline || saving));
  useEffect(() => {
    let active = true;
    api.getApiConfig().then((config) => {
      if (!active) return;
      setProvider(config.provider); setBaseline(config.provider); setConfigured(Boolean(config.apiKey));
    }).catch(() => { if (active) setError('Unable to load provider configuration.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (saving || !provider.trim() || !key.trim()) return;
    setSaving(true); setError(''); setStatus('');
    try {
      const result = await api.updateApiConfig({ provider: provider.trim(), apiKey: key.trim() });
      setProvider(result.provider); setBaseline(result.provider); setKey(''); setConfigured(true); setStatus('Provider configuration saved.');
    } catch { setError('Unable to save provider configuration.'); }
    finally { setSaving(false); }
  };
  const fieldClass = 'mt-1 w-full min-w-0 rounded-md border border-border-color bg-background px-3 py-2';
  return <section className="space-y-4 rounded-xl border border-border-color bg-surface p-4 sm:p-6">
    <h2 className="text-xl font-semibold">AI provider configuration</h2>
    <p className="text-sm text-text-secondary">AI requests run through the authenticated backend. The provider key is kept on the server. Enter a replacement key to update this configuration.</p>
    {loading ? <p role="status">Loading configuration...</p> : <p className="text-sm text-text-secondary">Database provider key: {configured ? 'Configured' : 'Not configured'}. Server environment keys may also be configured.</p>}
    {error && <p role="alert" className="text-red-400">{error}</p>}
    {status && <p role="status" className="text-green-400">{status}</p>}
    <form onSubmit={save} className="max-w-xl space-y-4">
      <label className="block text-sm">Provider name<input className={fieldClass} required value={provider} onChange={(event) => setProvider(event.target.value)} /></label>
      <label className="block text-sm">New provider key<input className={fieldClass} type="password" required autoComplete="new-password" value={key} onChange={(event) => setKey(event.target.value)} /></label>
      <button type="submit" disabled={loading || saving} className="rounded-lg border border-border-color px-4 py-2 transition hover:border-primary disabled:opacity-50">{saving ? 'Saving...' : 'Save provider configuration'}</button>
    </form>
  </section>;
};

export default ProviderSettingsPanel;
