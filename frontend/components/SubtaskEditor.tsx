import React, { useRef, useState } from 'react';
import { DateTime } from 'luxon';
import api from '../services/mockApi';
import { Role, TaskPriority, type Subtask, type SubtaskActivity, type SubtaskChanges, type Task, type User } from '../types';
import { resolveTaskTimezone } from '../utils/taskCalendarDates';
import { actualTimeOptions, actualTimeToUtc, actualWallTime, plannedDatesError, subtaskActions, subtaskPriority, subtaskStatusLabels } from '../utils/subtaskWorkflow';

const field = 'modal-input w-full rounded-xl border border-white/15 bg-black/30 px-3 py-2 text-sm text-white';
const button = 'modal-secondary-button rounded-xl border border-white/15 px-3 py-2 text-xs font-semibold disabled:opacity-40';

function Row({ subtask, task, zone, disabled, save }: { subtask:Subtask; task:Task; zone:string; disabled:boolean; save:(id:string, changes:SubtaskChanges)=>Promise<void> }) {
  const [title, setTitle] = useState(subtask.title);
  const [start, setStart] = useState(subtask.plannedStartDate || '');
  const [end, setEnd] = useState(subtask.plannedEndDate || '');
  const [priority, setPriority] = useState(subtask.priorityOverride || '');
  const [actualStart, setActualStart] = useState(actualWallTime(subtask.actualStartAt, zone));
  const [actualEnd, setActualEnd] = useState(actualWallTime(subtask.actualEndAt, zone));
  const [actualEdited, setActualEdited] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [startOffset, setStartOffset] = useState(subtask.actualStartAt ? String(DateTime.fromISO(subtask.actualStartAt).setZone(zone).offset) : '');
  const [endOffset, setEndOffset] = useState(subtask.actualEndAt ? String(DateTime.fromISO(subtask.actualEndAt).setZone(zone).offset) : '');
  const [error, setError] = useState('');
  const [enroll, setEnroll] = useState(false);
  const status = subtask.status || (subtask.completed ? 'COMPLETED' : 'TODO');
  const dirty = title !== subtask.title || start !== (subtask.plannedStartDate || '') || end !== (subtask.plannedEndDate || '') || priority !== (subtask.priorityOverride || '') || actualEdited;
  const submit = async (event:React.FormEvent) => {
    event.preventDefault();
    setError('');
    try {
      if (subtask.managed || enroll) {
        const message = plannedDatesError(start, end);
        if (message) throw new Error(message);
      }
      const changes:SubtaskChanges = { version:subtask.version };
      if (title !== subtask.title) changes.title = title;
      if (start !== (subtask.plannedStartDate || '')) changes.plannedStartDate = start || null;
      if (end !== (subtask.plannedEndDate || '')) changes.plannedEndDate = end || null;
      if (priority !== (subtask.priorityOverride || '')) changes.priorityOverride = priority ? priority as TaskPriority : null;
      if (actualEdited) {
        if (!confirmed) throw new Error('Confirm the actual times before saving.');
        if (actualStart !== actualWallTime(subtask.actualStartAt, zone) || (actualStart && startOffset !== String(DateTime.fromISO(subtask.actualStartAt || '').setZone(zone).offset))) changes.actualStartAt = actualStart ? actualTimeToUtc(actualStart, zone, startOffset) : null;
        if (actualEnd !== actualWallTime(subtask.actualEndAt, zone) || (actualEnd && endOffset !== String(DateTime.fromISO(subtask.actualEndAt || '').setZone(zone).offset))) changes.actualEndAt = actualEnd ? actualTimeToUtc(actualEnd, zone, endOffset) : null;
        const finalStart = changes.actualStartAt === undefined ? subtask.actualStartAt : changes.actualStartAt;
        const finalEnd = changes.actualEndAt === undefined ? subtask.actualEndAt : changes.actualEndAt;
        if (finalStart && finalEnd && Date.parse(finalStart) > Date.parse(finalEnd)) throw new Error('Actual start must be on or before actual end.');
        changes.confirmActualTimes = true;
      }
      if (!subtask.managed && enroll) {
        changes.manage = true;
        changes.plannedStartDate = start;
        changes.plannedEndDate = end;
      }
      await save(subtask.id, changes);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to save subtask.'); }
  };
  const timeField = (label:string, value:string, setValue:(value:string)=>void, offset:string, setOffset:(value:string)=>void) => {
    const options = actualTimeOptions(value, zone);
    return <label className="space-y-1 text-xs text-white/70">{label}
      <input type="datetime-local" step="1" value={value} onChange={event => { setValue(event.target.value); setOffset(''); setActualEdited(true); setConfirmed(false); }} className={field} />
      {options.length > 1 && <select aria-label={`${label} UTC offset`} required value={offset} onChange={event => { setOffset(event.target.value); setActualEdited(true); setConfirmed(false); }} className={field}>
        <option value="">Confirm UTC offset</option>{options.map(option => <option key={option.offset} value={option.offset}>{option.label}</option>)}
      </select>}
    </label>;
  };
  return <div role="group" aria-label={`Subtask ${subtask.title}`} className="rounded-2xl border border-white/10 bg-black/30 px-4 py-3">
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-white/80">
      <span>{subtask.title}</span><span>{subtaskStatusLabels[status]} · {subtaskPriority(subtask, task.priority)}{!subtask.priorityOverride && ' (inherited)'}</span>
    </div>
    {!subtask.managed && !subtask.deletedAt && <label className="mt-2 flex items-center gap-2 text-xs text-white/70">
      <input type="checkbox" disabled={disabled} checked={subtask.completed} onChange={async event => { try { await save(subtask.id, { completed:event.target.checked, version:subtask.version }); } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to update checklist.'); } }} />
      Historical checklist · {subtask.completed ? 'Completed' : 'To Do'}
    </label>}
    {!subtask.deletedAt && <details className="mt-3 text-xs text-white/70"><summary className="cursor-pointer">Edit details and actual times</summary>
      <form onSubmit={submit} className="mt-3 space-y-3"><fieldset disabled={disabled} className="space-y-3">
        <label className="block space-y-1">Title<input required maxLength={255} value={title} onChange={event => setTitle(event.target.value)} className={field} /></label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1">Planned start<input type="date" required={subtask.managed || enroll} value={start} onChange={event => setStart(event.target.value)} className={field} /></label>
          <label className="space-y-1">Planned end<input type="date" required={subtask.managed || enroll} min={start || undefined} value={end} onChange={event => setEnd(event.target.value)} className={field} /></label>
          {timeField('Actual start', actualStart, setActualStart, startOffset, setStartOffset)}
          {timeField('Actual end', actualEnd, setActualEnd, endOffset, setEndOffset)}
        </div>
        <p>Actual times use {zone}. Enter and save them before completing.</p>
        {actualEdited && <label className="flex items-center gap-2"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I confirm these manually entered actual times in {zone}.</label>}
        <label className="block space-y-1">Priority<select value={priority} onChange={event => setPriority(event.target.value)} className={field}>
          <option value="">Inherit parent ({task.priority})</option>{Object.values(TaskPriority).map(value => <option key={value} value={value}>{value}</option>)}
        </select></label>
        {!subtask.managed && <label className="flex items-center gap-2"><input type="checkbox" checked={enroll} onChange={event => setEnroll(event.target.checked)} />Enable managed workflow with planned dates</label>}
        <button type="submit" className={button}>{enroll ? 'Save and enable workflow' : 'Save changes'}</button>
      </fieldset></form>
    </details>}
    {subtask.managed && !subtask.deletedAt && <div className="mt-3 flex flex-wrap gap-2">{subtaskActions[status].map(item => <button key={item.action} type="button" className={button}
      disabled={disabled || dirty || (item.action === 'COMPLETE' && (!subtask.actualStartAt || !subtask.actualEndAt))}
      onClick={async () => { setError(''); try { await save(subtask.id, { action:item.action, version:subtask.version }); } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to change status.'); } }}>{item.label}</button>)}</div>}
    {dirty && subtask.managed && <p className="mt-2 text-xs text-white/60">Save your edits before changing status.</p>}
    {(subtask.managed || subtask.deletedAt) && <button type="button" disabled={disabled || dirty} className={`${button} mt-3`} onClick={async () => {
      try { await save(subtask.id, { deleted:!subtask.deletedAt, version:subtask.version }); }
      catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to change deletion state.'); }
    }}>{subtask.deletedAt ? 'Restore subtask' : 'Delete subtask'}</button>}
    {error && <p role="alert" className="mt-2 text-sm text-rose-300">{error}</p>}
  </div>;
}

export default function SubtaskEditor({ task, user, onUpdated }: { task:Task; user:User | null; onUpdated:(task:Task)=>void }) {
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const historyPending = useRef(false);
  const [history, setHistory] = useState<SubtaskActivity[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState('');
  const [title, setTitle] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const zone = resolveTaskTimezone(user?.timezone);
  const canEdit = !!user && (user.role !== Role.USER || task.createdBy === user.id || !!task.assignedTo?.includes(user.id));
  const loadHistory = async () => {
    if (historyPending.current) return;
    historyPending.current = true; setHistoryLoading(true);
    try { setHistory((await api.getTask(task.id, true, true)).subtaskActivity ?? []); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to load audit history.'); }
    finally { historyPending.current = false; setHistoryLoading(false); }
  };
  const save = async (id:string, changes:SubtaskChanges) => {
    if (pending.current || !canEdit) return;
    pending.current = true;
    setBusy(true); setError('');
    try { onUpdated(await api.updateSubtask(task.id, id, changes)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to save subtask.'); try { onUpdated(await api.getTask(task.id, true)); } catch { /* Keep the entered form if refresh is unavailable. */ } throw failure; }
    finally { pending.current = false; setBusy(false); }
  };
  const create = async (event:React.FormEvent) => {
    event.preventDefault(); setError('');
    if (pending.current || !canEdit) return;
    const message = plannedDatesError(start, end);
    if (message) { setError(message); return; }
    pending.current = true; setBusy(true);
    try {
      onUpdated(await api.updateTask(task.id, { subtasks:[...task.subtasks, { id:'new', title, completed:false, plannedStartDate:start, plannedEndDate:end }] }, user!.id));
      setTitle(''); setStart(''); setEnd('');
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to add subtask.'); }
    finally { pending.current = false; setBusy(false); }
  };
  return <div className="mt-4 space-y-3" style={{ colorScheme:'dark' }}>
    {task.subtaskRewards && <p className="text-xs text-white/70">Additional subtask XP earned: {task.subtaskRewards.earned} · Uncompleted base available: {task.subtaskRewards.available_base} · Base capacity: {task.subtaskRewards.base_capacity}. Bonus and penalty are posted only on completion.</p>}
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    {task.subtasks.map(subtask => <Row key={`${subtask.id}:${subtask.version}:${zone}`} subtask={subtask} task={task} zone={zone} disabled={!canEdit || busy} save={save} />)}
    <details onToggle={event => { if (event.currentTarget.open) void loadHistory(); }} className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-xs text-white/80">
      <summary className="cursor-pointer">Subtask audit history</summary>
      <button type="button" onClick={loadHistory} disabled={historyLoading} className={`${button} mt-3`}>{historyLoading ? 'Loading history…' : 'Refresh history'}</button>
      <p className="mt-2 text-white/60">Latest 200 recorded events. Historical changes before audit activation have no fabricated events.</p>
      <ol className="mt-3 space-y-3">{history.map(item => <li key={item.id} className="break-words border-t border-white/10 pt-2">
        <p>{item.event_type} · {DateTime.fromISO(item.created_at).setZone(zone).toFormat('yyyy-MM-dd HH:mm:ss ZZZZ')} · Actor {item.actor_id}</p>
        <p>Subtask {task.subtasks.find(row => row.id === item.subtask_id)?.title || item.subtask_id || 'Task'}</p>
        {Array.from(new Set([...Object.keys(item.before || {}), ...Object.keys(item.after || {})])).map(key => <p key={key}>{key}: {JSON.stringify(item.before?.[key] ?? null)} → {JSON.stringify(item.after?.[key] ?? null)}</p>)}
      </li>)}</ol>
      {!historyLoading && !history.length && <p className="mt-3">No recorded events.</p>}
    </details>
    {canEdit && <details className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white/80"><summary className="cursor-pointer">Add subtask</summary>
      <form onSubmit={create} className="mt-3 space-y-3"><fieldset disabled={busy} className="space-y-3">
        <label className="block text-xs">Title *<input required maxLength={255} value={title} onChange={event => setTitle(event.target.value)} className={field} /></label>
        <div className="grid grid-cols-2 gap-3"><label className="text-xs">Planned start *<input type="date" required value={start} onChange={event => setStart(event.target.value)} className={field} /></label>
          <label className="text-xs">Planned end *<input type="date" required min={start || undefined} value={end} onChange={event => setEnd(event.target.value)} className={field} /></label></div>
        <p className="text-xs text-white/60">Assignment and default priority follow this task.</p>
        <button type="submit" className={button}>Add subtask</button>
      </fieldset></form>
    </details>}
  </div>;
}
