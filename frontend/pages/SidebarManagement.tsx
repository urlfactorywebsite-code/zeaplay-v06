import { useEffect, useRef, useState, type FormEvent } from 'react';
import SidebarEditor, { EditorItem } from '../components/SidebarEditor';
import { navigationError, useNavigation } from '../hooks/useNavigation';
import { useUnsavedChanges } from '../hooks/useUnsavedChanges';
import { NavigationPolicy, NavigationRule } from '../types/navigation';
import api from '../services/mockApi';

export default function SidebarManagement() {
  const { policy, preferences, refresh, savePreferences } = useNavigation();
  const [items, setItems] = useState<EditorItem[]>([]);
  const [baseline, setBaseline] = useState('');
  const [version, setVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ error: boolean; text: string } | null>(null);
  const initialized = useRef(false);
  const dirty = initialized.current && JSON.stringify(items) !== baseline;
  useUnsavedChanges(dirty || saving);
  const initialize = (next: NavigationPolicy) => {
    const order = [...new Set([...preferences.order, ...next.pages.map(page => page.id)])];
    const rows = order.flatMap(id => {
      const page = next.pages.find(page => page.id === id);
      return page ? [{ ...page, label: preferences.labels[id] || page.defaultLabel, defaultIndex: next.pages.indexOf(page) }] : [];
    });
    setItems(rows); setBaseline(JSON.stringify(rows)); setVersion(next.version); initialized.current = true;
  };
  useEffect(() => { if (policy && !initialized.current) initialize(policy); }, [policy, preferences]);
  if (!policy) return null;
  const invalid = items.some(item => !item.label.trim() || item.label.trim().length > 48);
  const globalChanged = items.some(item => {
    const previous = policy.pages.find(page => page.id === item.id)!;
    return item.enabled !== previous.enabled || item.hidden !== previous.hidden || [...item.allowedRoles].sort().join() !== [...previous.allowedRoles].sort().join();
  });
  const discard = async () => {
    if (dirty && !window.confirm('Discard your unsaved navigation changes?')) return;
    const next = await refresh();
    if (next) { initialize(next); setNotice(null); }
  };
  const reset = () => {
    if (!window.confirm('Reset your display names and ordering, and all policies you are authorized to change? Changes are saved only when you choose Save Changes.')) return;
    setItems([...items].sort((a, b) => a.defaultIndex - b.defaultIndex).map(item => ({ ...item, label: item.defaultLabel,
      hidden: false, enabled: policy.canChangeAccess ? true : item.enabled,
      allowedRoles: policy.canChangeAccess ? [...item.permittedRoles] : item.allowedRoles })));
    setNotice(null);
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (invalid || saving || !dirty) return;
    if (globalChanged && !window.confirm('Apply organization-wide navigation changes? Disabled modules and removed role access will block direct access for affected users. Data will be preserved.')) return;
    setSaving(true); setNotice(null);
    let globalSaved = false;
    try {
      if (globalChanged) {
        const rules = Object.fromEntries(items.map(item => [item.id, { enabled: item.enabled, hidden: item.hidden, allowedRoles: item.allowedRoles } satisfies NavigationRule]));
        const updated = await api.updateNavigationPolicy(version, rules);
        setVersion(updated.version); globalSaved = true;
      }
      // Retain unknown/temporarily absent legacy entries for future compatibility.
      const known = new Set(items.map(item => item.id));
      const nextPreferences = { order: [...items.map(item => item.id), ...preferences.order.filter(id => !known.has(id))], labels: { ...preferences.labels } };
      items.forEach(item => {
        if (item.label.trim() === item.defaultLabel) delete nextPreferences.labels[item.id];
        else nextPreferences.labels[item.id] = item.label.trim();
      });
      savePreferences(nextPreferences);
      const normalized = items.map(item => ({ ...item, label: item.label.trim() }));
      setItems(normalized); setBaseline(JSON.stringify(normalized));
      await refresh();
      setNotice({ error: false, text: globalSaved ? 'Organization policy and personal layout saved. Other sessions revalidate on navigation, focus, and every 30 seconds.' : 'Your personal names and ordering were saved in this browser.' });
    } catch (failure) {
      setNotice({ error: true, text: globalSaved ? 'Organization policy was saved, but browser preferences could not be saved. Enable browser storage, then retry.' : navigationError(failure) });
    } finally { setSaving(false); }
  };
  return <form onSubmit={save} className="min-w-0 space-y-5" aria-label="Sidebar Management">
    <header><h2 className="text-2xl font-semibold">Sidebar Management</h2><p className="mt-1 text-text-secondary">Customize navigation, control page visibility, and manage role-based access.</p></header>
    <div className="rounded-xl border border-border-color bg-surface p-4 text-sm text-text-secondary">
      <p>Names and ordering apply to your account in this browser. Availability, hidden navigation, and role restrictions apply to this organization across sessions.</p>
      <p className="mt-2">{policy.canChangeAccess ? 'Owner: you can change module availability and narrow existing role permissions.' : 'Admin: you can customize your layout and hide navigation. Only the Owner can change module availability or role access.'} Protected recovery pages always remain accessible.</p>
      <p className="mt-2">Shared data APIs stay available through other authorized views. Hiding a link alone does not revoke access.</p>
      <p className="mt-2">Policy version {version}{policy.updatedAt ? ` | Updated ${new Date(policy.updatedAt).toLocaleString()}` : ' | Default policy'}{policy.updatedBy ? ` | By ${policy.updatedBy}` : ''}</p>
    </div>
    {policy.version !== version && <p role="alert" className="rounded-lg border border-amber-500 p-3">The organization policy changed in another session. Your draft is preserved. Discard and reload before saving policy changes.</p>}
    {notice && <p role={notice.error ? 'alert' : 'status'} className={`rounded-lg border p-3 ${notice.error ? 'border-red-500' : 'border-emerald-500'}`}>{notice.text}</p>}
    <div className="flex flex-wrap gap-3">
      <button type="submit" disabled={!dirty || invalid || saving || (globalChanged && policy.version !== version)} className="rounded-lg bg-primary px-4 py-2 font-semibold text-white disabled:opacity-40">{saving ? 'Saving…' : 'Save Changes'}</button>
      <button type="button" disabled={saving} onClick={() => void discard()} className="rounded-lg border border-border-color px-4 py-2">Discard Changes / Reload</button>
      <button type="button" disabled={saving} onClick={reset} className="rounded-lg border border-border-color px-4 py-2">Reset Defaults</button>
      {dirty && <span role="status" className="self-center text-sm text-amber-500">Unsaved changes</span>}
    </div>
    {invalid && <p role="alert" className="text-sm text-red-500">Each display name must contain 1–48 characters.</p>}
    <SidebarEditor items={items} roles={policy.roles} canChangeAccess={policy.canChangeAccess} disabled={saving} onChange={setItems} />
  </form>;
}
