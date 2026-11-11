import React, { useEffect, useState } from 'react';
import type { NotificationPreference } from '../types';

export default function WorkloadAlertSettings({ preference, onSave }: {
  preference: NotificationPreference; onSave: (value: NotificationPreference) => Promise<void>;
}) {
  const [draft, setDraft] = useState(preference);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => setDraft(preference), [preference]);
  const input = 'rounded-lg border border-border-color bg-background p-2 text-text-primary';
  return <form aria-label="Workload alert preferences" className="space-y-3 rounded-xl border border-border-color p-4"
    onSubmit={async event => {
      event.preventDefault(); if (saving) return;
      if (!!draft.quietStart !== !!draft.quietEnd) { setError('Enter both quiet-hour times, or clear both.'); return; }
      setSaving(true); setError('');
      try { await onSave(draft); } catch { setError('Unable to save workload preferences. Please retry.'); }
      finally { setSaving(false); }
    }}>
    <h3 className="font-semibold">Workload alerts</h3>
    <p className="text-sm text-text-secondary">In-app alerts remain available when browser notifications are blocked. Blank capacity uses your configured shift and breaks. Quiet hours use your profile timezone.</p>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="flex flex-col gap-1 text-sm">Approaching deadline (hours)<input className={input} type="number" min="1" max="8760" required value={draft.nearDeadlineHours ?? 24} onChange={e => setDraft({ ...draft, nearDeadlineHours: e.target.valueAsNumber })} /></label>
      <label className="flex flex-col gap-1 text-sm">Productive capacity override (hours per day)<input className={input} type="number" min="0.01" max="24" step="0.01" value={draft.productiveCapacityHours ?? ''} onChange={e => setDraft({ ...draft, productiveCapacityHours: e.target.value === '' ? null : e.target.valueAsNumber })} /></label>
      <label className="flex flex-col gap-1 text-sm">Overtime alert after (minutes)<input className={input} type="number" min="0" max="1440" required value={draft.overtimeThresholdMinutes ?? 0} onChange={e => setDraft({ ...draft, overtimeThresholdMinutes: e.target.valueAsNumber })} /></label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.soundEnabled ?? false} onChange={e => setDraft({ ...draft, soundEnabled: e.target.checked })} />Notification sound</label>
      <label className="flex flex-col gap-1 text-sm">Quiet hours start<input className={input} type="time" value={draft.quietStart ?? ''} onChange={e => setDraft({ ...draft, quietStart: e.target.value || null })} /></label>
      <label className="flex flex-col gap-1 text-sm">Quiet hours end<input className={input} type="time" value={draft.quietEnd ?? ''} onChange={e => setDraft({ ...draft, quietEnd: e.target.value || null })} /></label>
    </div>
    {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
    <button disabled={saving} className="rounded-lg border border-border-color px-3 py-2 text-sm disabled:opacity-50">{saving ? 'Saving…' : 'Save workload alerts'}</button>
  </form>;
}
