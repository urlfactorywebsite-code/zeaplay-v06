import React, { useEffect, useRef, useState } from 'react';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import { AlertTriangle, Clock3, Pause, Play, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { DateTime } from 'luxon';
import api from '../services/mockApi';
import { useAuth } from '../hooks/useAuth';
import { useTaskActivity } from '../hooks/useTaskActivity';
import { Role, TaskStatus } from '../types';
import type { ActivityContext, ConfirmedWork } from '../types/taskActivity';
import { activityWarning, fiveSlots, notifyActivityChanged, workDuration } from '../utils/taskActivity';
import { actualTimeOptions, actualTimeToUtc, actualWallTime } from '../utils/subtaskWorkflow';
import ActivityElapsed from './ActivityElapsed';
import { watchActivity } from '../utils/taskActivity';

const input = 'w-full rounded-lg border border-border-color bg-background px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-primary';
const button = 'rounded-lg border border-border-color px-3 py-2 text-sm font-medium hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary';
const message = (error: unknown) => error instanceof Error ? error.message : 'Unable to update activity. Refresh and retry.';

function LocalTime({ label, value, offset, setValue, setOffset, zone }: { label: string; value: string; offset: string; setValue: (v: string) => void; setOffset: (v: string) => void; zone: string }) {
  const options = actualTimeOptions(value, zone);
  return <label className="block space-y-1 text-sm">{label}<input aria-label={label} required type="datetime-local" step="1" className={input} value={value} onChange={e => { setValue(e.target.value); setOffset(''); }} />
    {options.length > 1 && <select aria-label={`${label} UTC offset`} required className={input} value={offset} onChange={e => setOffset(e.target.value)}>
      <option value="">Confirm UTC offset</option>{options.map(x => <option value={x.offset} key={x.offset}>{x.label}</option>)}
    </select>}
  </label>;
}

function TaskActivityControl({ enabled, socketStatus }: { enabled: boolean; socketStatus: string }) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState('');
  const own = useTaskActivity(enabled, undefined, socketStatus === 'connected');
  const viewed = useTaskActivity(enabled && open && !!target && target !== user?.id, target, socketStatus === 'connected');
  const sample = target && target !== user?.id ? viewed : own;
  const frame = sample.frame;
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState('');
  const [selectedTask, setSelectedTask] = useState('');
  const [selectedSubtask, setSelectedSubtask] = useState('');
  const [workTask, setWorkTask] = useState('');
  const [workSubtask, setWorkSubtask] = useState<string | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [startOffset, setStartOffset] = useState('');
  const [endOffset, setEndOffset] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState('');
  const [supersedes, setSupersedes] = useState<string | undefined>();
  const tasks = useQuery({ queryKey: ['activity-task-choices', user?.id, user?.role], enabled: enabled && open && !!user && !frame?.read_only,
    queryFn: () => api.getTasks(user!.id, user!.role), staleTime: 0 });
  const users = useQuery({ queryKey: ['activity-report-users', user?.id, user?.role], enabled: enabled && open && !!user && user.role !== Role.USER,
    queryFn: () => api.getUsers(), staleTime: 30_000 });
  const log = useQuery({ queryKey: ['activity-work-log', user?.id, workTask], enabled: enabled && open && !!workTask && !frame?.read_only,
    queryFn: () => api.getTaskWorkIntervals(workTask), staleTime: 0 });
  useEffect(() => {
    watchActivity(enabled && open && target ? target : user?.id);
    return () => watchActivity(user?.id);
  }, [enabled, open, target, user?.id]);
  useEffect(() => { if (socketStatus === 'connected') { own.refresh(); } }, [socketStatus, own.refresh]);
  useEffect(() => { if (socketStatus === 'connected' && open && target && target !== user?.id) viewed.refresh(); }, [socketStatus, open, target, user?.id, viewed.refresh]);
  useEffect(() => { setOpen(false); setTarget(''); setError(''); }, [user?.id]);
  const current = own.frame?.contexts.find(x => x.status === 'RUNNING') ?? own.frame?.contexts.find(x => x.status === 'PAUSED');
  const warning = activityWarning(own.frame);
  const allChoices = (tasks.data ?? []).filter(task => task.createdBy === user?.id || task.assignedTo?.includes(user?.id ?? '') || user?.role !== Role.USER);
  const choices = allChoices.filter(task => task.status !== TaskStatus.DONE && String(task.status) !== 'DEPLOYED');
  const choice = choices.find(task => task.id === selectedTask);
  const zone = own.frame?.timezone ?? 'UTC';
  const displayTime = (value: string | null, inZone = frame?.timezone ?? zone) => value ? DateTime.fromISO(value, { zone: 'utc' }).setZone(inZone).toFormat('dd LLL yyyy, HH:mm:ss') : 'Not recorded';
  const perform = async (taskId: string, action: 'START' | 'PAUSE' | 'RESUME' | 'STOP', child: string | null) => {
    if (pending.current || !user) return;
    pending.current = true; setBusy(true); setError('');
    try {
      const version = own.frame?.contexts.find(x => x.task_id === taskId)?.version ?? 0;
      const next = await api.changeTaskActivity(taskId, { action, subtask_id: child, expected_version: version, request_id: crypto.randomUUID() });
      own.accept(next);
    } catch (failure) { setError(message(failure)); setTarget(''); setOpen(true); own.refresh(); }
    finally { pending.current = false; setBusy(false); }
  };
  const chooseLog = (row: ConfirmedWork) => {
    setSupersedes(row.id); setWorkSubtask(row.subtask_id);
    setStart(actualWallTime(row.started_at, zone)); setEnd(actualWallTime(row.ended_at, zone));
    setStartOffset(String(DateTime.fromISO(row.started_at).setZone(zone).offset));
    setEndOffset(String(DateTime.fromISO(row.ended_at).setZone(zone).offset));
    setNote(row.note ?? ''); setConfirmed(false); setError('');
  };
  const record = async (event: React.FormEvent) => {
    event.preventDefault();
    if (pending.current || !confirmed || !workTask || frame?.read_only) return;
    pending.current = true; setBusy(true); setError('');
    try {
      const started_at = actualTimeToUtc(start, zone, startOffset);
      const ended_at = actualTimeToUtc(end, zone, endOffset);
      if (Date.parse(ended_at) <= Date.parse(started_at)) throw new Error('Work end must be after work start.');
      await api.recordTaskWork(workTask, { started_at, ended_at, subtask_id: workSubtask, note, confirmed: true, request_id: crypto.randomUUID(), supersedes_id: supersedes });
      setStart(''); setEnd(''); setConfirmed(false); setSupersedes(undefined); setNote('');
      await log.refetch(); notifyActivityChanged(user?.id);
    } catch (failure) { setError(message(failure)); }
    finally { pending.current = false; setBusy(false); }
  };
  const contextCard = (row: ActivityContext, receivedAt: number) => row.restricted ? <p className="text-sm">Occupied slot · task details are outside your visibility.</p> : <div className="space-y-2 break-words" key={row.id}>
    <div className="flex flex-wrap items-start justify-between gap-2"><strong>{row.task_title}</strong><span className="rounded bg-primary/10 px-2 py-1 text-xs">{row.priority ?? 'Restricted'} · {row.status}</span></div>
    <p className="text-sm">{row.subtask_title || 'Parent task activity'}</p>
    <p className="text-xs text-text-secondary">Workflow: {row.subtask_status ?? row.task_status ?? 'Restricted'}</p>
    <dl className="grid gap-2 text-xs sm:grid-cols-2"><div><dt>Parent activity elapsed</dt><dd className="font-mono text-base"><ActivityElapsed row={row} receivedAt={receivedAt} /></dd></div>
      <div><dt>Confirmed productive work, parent total</dt><dd className="font-mono text-base">{workDuration(row.productive_seconds)}</dd></div>
      {row.subtask_id && <><div><dt>Selected subtask activity elapsed</dt><dd className="font-mono text-base"><ActivityElapsed row={row} receivedAt={receivedAt} selected /></dd></div><div><dt>Selected subtask productive work</dt><dd className="font-mono text-base">{workDuration(row.subtask_productive_seconds ?? 0)}</dd></div></>}
      <div><dt>Manual actual start</dt><dd>{displayTime(row.actual_start_at)}</dd></div><div><dt>Manual actual end</dt><dd>{displayTime(row.actual_end_at)}</dd></div>
      <div className="sm:col-span-2"><dt>Deadline ({frame?.timezone})</dt><dd>{displayTime(row.deadline)}</dd></div></dl>
    <div className="flex flex-wrap gap-2">{!frame?.read_only && <>
      {row.status === 'RUNNING' ? <button className={button} disabled={busy} onClick={() => void perform(row.task_id, 'PAUSE', row.subtask_id)}>Pause</button>
        : <button className={button} disabled={busy || !row.can_start || (frame?.active_count ?? 5) >= 5} onClick={() => void perform(row.task_id, row.status === 'PAUSED' ? 'RESUME' : 'START', row.subtask_id)}>{row.status === 'PAUSED' ? 'Resume' : 'Start'}</button>}
      <button className={button} disabled={busy} onClick={() => void perform(row.task_id, 'STOP', row.subtask_id)}>Stop activity</button>
      <button className={button} onClick={() => { setWorkTask(row.task_id); setWorkSubtask(row.subtask_id); setSupersedes(undefined); }}>Log productive work</button>
    </>}{row.task_title !== 'Task access changed' && <Link className={button} to={`/tasks?taskId=${encodeURIComponent(row.task_id)}`} onClick={() => setOpen(false)}>Open task details</Link>}</div>
  </div>;
  if (!enabled || !user) return null;
  return <>
    <div className="flex min-w-0 items-center gap-1">
      <button type="button" aria-label={`Task activity ${own.frame?.active_count ?? 'unknown'} out of five`} aria-haspopup="dialog" aria-expanded={open}
        title={current ? `${current.task_title}${current.subtask_title ? ` / ${current.subtask_title}` : ''} · ${current.status}` : 'Task activity and workload'}
        className="zea-header-control flex h-11 max-w-[200px] items-center gap-2 rounded-xl border border-border-color px-2 text-left" onClick={() => { setTarget(''); setOpen(true); }}>
        {warning ? <AlertTriangle aria-label="Workload warning" className="h-4 w-4 shrink-0 text-amber-500" /> : <Clock3 className="h-4 w-4 shrink-0" />}
        <span className="min-w-0"><span className="block truncate text-xs font-semibold">{own.frame ? `${own.frame.active_count}/5` : '—/5'} · {current ? `${current.task_title}${current.subtask_title ? ` / ${current.subtask_title}` : ''}` : 'Task activity'}</span>
          <span className="block truncate font-mono text-[10px]">{own.isError ? 'Activity unavailable' : current ? <>{current.status === 'RUNNING' ? 'Working' : 'Paused'} <ActivityElapsed row={current} receivedAt={own.receivedAt} selected /></> : 'No active work'}</span></span>
      </button>
      {current && <button type="button" className="zea-header-icon-button flex h-10 w-10 items-center justify-center rounded-lg disabled:opacity-40" disabled={busy || (current.status === 'PAUSED' && (own.frame?.active_count ?? 5) >= 5)}
        aria-label={`${current.status === 'RUNNING' ? 'Pause' : 'Resume'} current activity`} onClick={() => void perform(current.task_id, current.status === 'RUNNING' ? 'PAUSE' : 'RESUME', current.subtask_id)}>
        {current.status === 'RUNNING' ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      </button>}
    </div>
    <Dialog open={open} onClose={() => setOpen(false)} className="fixed inset-0 z-[100]">
      <div className="fixed inset-0 bg-black/65" aria-hidden="true" />
      <div className="fixed inset-0 overflow-y-auto p-3 sm:p-6"><DialogPanel className="mx-auto my-4 max-w-5xl rounded-2xl border border-border-color bg-surface p-4 text-text-primary shadow-2xl sm:p-6">
        <div className="flex items-center justify-between gap-3"><DialogTitle className="text-lg font-semibold">Task activity and workload</DialogTitle><button aria-label="Close task activity" className={button} onClick={() => setOpen(false)}><X className="h-4 w-4" /></button></div>
        <p className="mt-2 text-sm text-text-secondary">Five parent-task slots per person. Activity elapsed is not productive work. Switching subtasks keeps the same parent slot and parent elapsed total.</p>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-text-secondary"><span>{socketStatus === 'connected' ? 'Connected · synced across sessions' : 'Reconnecting · activity will refresh automatically'}</span><button className={button} onClick={sample.refresh}>Refresh activity</button></div>
        {user.role !== Role.USER && <label className="mt-3 block text-sm">View workload (others are read only)<select className={`${input} mt-1`} value={target || user.id} onChange={e => { setTarget(e.target.value); setError(''); }}>
          <option value={user.id}>My activity</option>{(users.data ?? []).filter(x => x.id !== user.id && (user.role !== Role.MANAGER || x.managerId === user.id)).map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select></label>}
        {(error || sample.error) && <p role="alert" className="mt-3 rounded-lg border border-red-500/40 p-3 text-sm text-red-500">{error || message(sample.error)}</p>}
        {!frame ? <p className="py-6">{sample.isError ? 'Activity is unavailable. Refresh to retry.' : 'Loading server activity…'}</p> : <>
          <div className="mt-4 flex flex-wrap items-center gap-3"><strong>{frame.user_name}: {frame.active_count}/5 active parents</strong><span className="text-xs text-text-secondary">{frame.timezone} · Today</span></div>
          <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3"><div className="rounded-xl border border-border-color p-3">Manual productive work <strong className="block font-mono">{workDuration(frame.workload.manual_seconds)}</strong></div>
            <div className="rounded-xl border border-border-color p-3">Estimated remaining <strong className="block font-mono">{workDuration(frame.workload.estimated_remaining_seconds)}</strong><span className="text-xs">{frame.workload.unestimated_tasks} tasks without estimates</span></div>
            <div className="rounded-xl border border-border-color p-3">Configured capacity <strong className="block font-mono">{frame.workload.capacity_seconds === null ? 'Unknown' : workDuration(frame.workload.capacity_seconds)}</strong><span className="text-xs">Overtime: {frame.workload.overtime_seconds === null ? 'Unknown' : workDuration(frame.workload.overtime_seconds)}</span></div></div>
          {frame.workload.capacity_note && <p className="mt-2 text-xs text-text-secondary">{frame.workload.capacity_note}</p>}
          {frame.workload.overlap_seconds > 0 && <p role="status" className="mt-2 text-sm text-amber-600">Historical overlaps detected. Shared minutes are counted once, assigned to the earliest confirmed interval. Correct your work log to resolve conflicts.</p>}
          <p className="mt-3 text-sm">Next {frame.workload.near_deadline_window_hours} hours: {frame.workload.near_deadline.length} deadlines · Overdue: {frame.workload.overdue_tasks.length} tasks, {frame.workload.overdue_subtasks.length} subtasks</p>
          <p className="mt-1 text-sm">Remaining available hours: {frame.workload.remaining_capacity_seconds == null ? 'Unknown — configure capacity or a shift' : workDuration(frame.workload.remaining_capacity_seconds)}</p>
          {frame.workload.remaining_capacity_seconds != null && frame.workload.estimated_remaining_seconds > frame.workload.remaining_capacity_seconds && <p role="status" className="mt-1 text-sm text-amber-600">Estimated workload exceeds remaining available hours.</p>}
          <details className="mt-2 text-sm"><summary className="cursor-pointer">View deadline warnings</summary><ul className="mt-2 space-y-1">{[...frame.workload.overdue_tasks, ...frame.workload.overdue_subtasks, ...frame.workload.near_deadline].map((x, i) => <li key={`${x.task_id}:${x.subtask_id}:${i}`}><Link to={`/tasks?taskId=${encodeURIComponent(x.task_id)}`} onClick={() => setOpen(false)} className="underline">{x.title}</Link> · {displayTime(x.deadline)}</li>)}</ul></details>
          <div aria-label="Five possible task slots" className="mt-4 grid gap-3 md:grid-cols-2">{fiveSlots(frame).map(slot => <section key={slot.number} className="min-w-0 rounded-xl border border-border-color p-3"><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-secondary">Slot {slot.number}</h3>{slot.context ? contextCard(slot.context, sample.receivedAt) : <p className="text-sm text-text-secondary">Available task slot</p>}</section>)}</div>
          {frame.contexts.some(x => x.status === 'PAUSED') && <section className="mt-4"><h3 className="font-semibold">Paused activity · no active slot used</h3><div className="mt-2 grid gap-3 md:grid-cols-2">{frame.contexts.filter(x => x.status === 'PAUSED').map(row => <div key={row.id} className="min-w-0 rounded-xl border border-border-color p-3">{contextCard(row, sample.receivedAt)}</div>)}</div></section>}
          {!frame.read_only && <section className="mt-4 space-y-3 rounded-xl border border-border-color p-3"><h3 className="font-semibold">Start personal activity</h3>
            <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Parent task<select aria-label="Activity parent task" className={`${input} mt-1`} value={selectedTask} onChange={e => { setSelectedTask(e.target.value); setSelectedSubtask(''); }}><option value="">Choose a task</option>{choices.map(task => <option key={task.id} value={task.id}>{task.title}</option>)}</select></label>
              <label className="text-sm">Subtask (optional)<select aria-label="Activity subtask" className={`${input} mt-1`} value={selectedSubtask} onChange={e => setSelectedSubtask(e.target.value)}><option value="">Parent task</option>{(choice?.subtasks ?? []).filter(x => !x.completed && !x.deletedAt).map(x => <option key={x.id} value={x.id}>{x.title}</option>)}</select></label></div>
            {tasks.isError && <p role="alert">{message(tasks.error)}</p>}
            <button className={button} disabled={busy || !selectedTask || frame.active_count >= 5 && !frame.contexts.some(x => x.task_id === selectedTask && x.status === 'RUNNING')} onClick={() => void perform(selectedTask, 'START', selectedSubtask || null)}>Start activity</button>
            {frame.active_count >= 5 && <p className="text-xs text-amber-600">All five slots are occupied. Pause a parent task before starting or resuming another.</p>}
          </section>}
          {!frame.read_only && <section className="mt-4 space-y-3 rounded-xl border border-border-color p-3"><h3 className="font-semibold">Confirmed productive work</h3><p className="text-xs text-text-secondary">Enter work intervals manually in {zone}. Timers and subtask actual start/end values are kept separate. New overlaps are rejected; corrections retain original history.</p>
            <label className="block text-sm">Work-log parent task<select aria-label="Work log parent task" className={`${input} mt-1`} value={workTask} onChange={e => { setWorkTask(e.target.value); setWorkSubtask(null); setSupersedes(undefined); setConfirmed(false); }}><option value="">Choose a task</option>{allChoices.map(task => <option key={task.id} value={task.id}>{task.title}</option>)}</select></label>
            {workTask && <><form onSubmit={record} className="space-y-3"><fieldset disabled={busy} className="space-y-3">
              {supersedes && <p className="text-sm text-amber-600">Correcting interval {supersedes}. The original will be retained.</p>}
              <label className="block text-sm">Work-log subtask<select aria-label="Work log subtask" disabled={!!supersedes} className={`${input} mt-1`} value={workSubtask ?? ''} onChange={e => { setWorkSubtask(e.target.value || null); setConfirmed(false); }}><option value="">Parent task</option>{(allChoices.find(t => t.id === workTask)?.subtasks ?? []).map(x => <option key={x.id} value={x.id}>{x.title}</option>)}</select></label>
              <div className="grid gap-3 sm:grid-cols-2"><LocalTime label="Productive work start" value={start} offset={startOffset} setValue={v => { setStart(v); setConfirmed(false); }} setOffset={v => { setStartOffset(v); setConfirmed(false); }} zone={zone} /><LocalTime label="Productive work end" value={end} offset={endOffset} setValue={v => { setEnd(v); setConfirmed(false); }} setOffset={v => { setEndOffset(v); setConfirmed(false); }} zone={zone} /></div>
              <label className="block text-sm">Note<textarea className={`${input} mt-1`} value={note} maxLength={10000} onChange={e => setNote(e.target.value)} /></label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I confirm these manually entered productive work times in {zone}.</label>
              <div className="flex flex-wrap gap-2"><button className={button} type="submit" disabled={!confirmed || !start || !end}>{supersedes ? 'Save correction' : 'Save confirmed work'}</button>{supersedes && <button type="button" className={button} onClick={() => { setSupersedes(undefined); setStart(''); setEnd(''); setConfirmed(false); }}>Cancel correction</button>}</div>
            </fieldset></form><h4 className="text-sm font-semibold">Recent confirmed intervals</h4>{log.isError && <p role="alert">{message(log.error)}</p>}<ul className="space-y-2">{(log.data ?? []).map(row => <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-color p-2 text-xs"><span>{displayTime(row.started_at, zone)} → {displayTime(row.ended_at, zone)}{row.superseded && ' · Superseded'}</span>{!row.superseded && <button className={button} disabled={busy} onClick={() => chooseLog(row)}>Correct interval</button>}</li>)}</ul></>}
          </section>}
        </>}
      </DialogPanel></div>
    </Dialog>
  </>;
}
export default React.memo(TaskActivityControl);
