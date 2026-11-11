import React, { useCallback, useEffect, useId, useMemo, useState } from 'react';
import { Dialog, DialogDescription, DialogPanel, DialogTitle, Tab, TabGroup, TabList, TabPanel, TabPanels } from '@headlessui/react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { getAccessToken } from '../services/tokenStorage';
import { useAuth } from '../hooks/useAuth';
import { TASKS_CHANGED_EVENT } from '../utils/taskEvents';
import { TASK_ACTIVITY_CHANGED, workDuration } from '../utils/taskActivity';
import { APP_REFRESH_EVENT } from '../utils/appEvents';
import { coalesceActivityRefresh } from '../utils/activityRefresh';
import { formatInformationTime, informationLastPage, informationScope, informationZone, isInformationTimestamp, taskInformationQueryOptions } from '../utils/taskInformation';
import type { InformationEvent, InformationOptions, InformationSection, InformationSubtask, TaskInformation } from '../types/taskInformation';

const button = 'rounded-lg border border-border-color px-3 py-2 text-sm hover:bg-primary/10 disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary';
const sections: { key: InformationSection; title: string }[] = [
  { key: 'overview', title: 'Overview' }, { key: 'timeline', title: 'Status timeline' },
  { key: 'subtasks', title: 'Subtasks' }, { key: 'points', title: 'Points' }, { key: 'activity', title: 'Activity' },
];
const text = (value: unknown): string => value == null ? 'Not recorded' : typeof value === 'string' ? value : JSON.stringify(value);
const status = (value: string | null) => value ? value.replaceAll('_', ' ') : 'Not recorded';

function useInformation(taskId: string, options: InformationOptions) {
  const { user } = useAuth();
  return useQuery(taskInformationQueryOptions(informationScope(taskId, user), taskId, options, user?.id));
}

function usePageBounds(data: TaskInformation | undefined, page: number, change: (page: number) => void) {
  useEffect(() => {
    if (data && page > informationLastPage(data.total, data.page_size)) change(informationLastPage(data.total, data.page_size));
  }, [data, page, change]);
}

function Pager({ data, page, change }: { data: TaskInformation; page: number; change: (page: number) => void }) {
  return <nav aria-label="History pagination" className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
    <span>{data.total} records · Page {page} of {informationLastPage(data.total, data.page_size)}</span>
    <div className="flex gap-2"><button className={button} disabled={page <= 1} onClick={() => change(page - 1)}>Previous</button>
      <button className={button} disabled={page * data.page_size >= data.total} onClick={() => change(page + 1)}>Next</button></div>
  </nav>;
}

function SnapshotValues({ values, format }: { values: Record<string, unknown>; format: (date: string | null) => string }) {
  return <dl>{Object.entries(values).map(([key, value]) => <div className="break-words" key={key}><dt className="inline font-medium">{key}: </dt><dd className="inline whitespace-pre-wrap">{isInformationTimestamp(key, value) ? <time dateTime={value} title={`UTC ${value}`}>{format(value)}</time> : text(value)}</dd></div>)}</dl>;
}

const History = React.memo(function History({ rows, format, timeline = false }: { rows: InformationEvent[]; format: (date: string | null) => string; timeline?: boolean }) {
  if (!rows.length) return <p className="py-6 text-text-secondary">No recorded {timeline ? 'status transitions' : 'activity'} in this scope.</p>;
  return <ol aria-label={timeline ? 'Recorded status transitions' : 'Recorded audit activity'} className="space-y-4">
    {rows.map(row => <li key={row.id} className={`relative rounded-xl border border-border-color bg-background p-4 ${timeline ? 'ml-2 border-l-4 border-l-primary' : ''}`}>
      <div className="flex flex-wrap justify-between gap-2"><strong className="min-w-0 break-all">{row.event_type}</strong><time className="break-all" dateTime={row.timestamp} title={row.timestamp}>{format(row.timestamp)}<span className="block text-xs text-text-secondary">UTC {row.timestamp}</span></time></div>
      <p className="mt-1 text-sm text-text-secondary">{row.actor?.name ?? (row.source === 'ledger' ? 'See linked audit event' : 'Actor not recorded')} · {row.channel} · {row.source}{row.subtask_id ? ` · Subtask ${row.subtask_id}` : ''}</p>
      {row.new_status && <p className="mt-2 font-medium">{status(row.previous_status)} <span aria-hidden="true">→</span><span className="sr-only"> changed to </span> {status(row.new_status)}
        {row.duration_seconds != null && <span className="ml-2 text-sm text-text-secondary">{workDuration(row.duration_seconds)} until next recorded transition</span>}</p>}
      {timeline && row.event_type === 'work.switched' && <p className="mt-1 text-sm">Active subtask changed: {text(row.before?.subtask_id)} → {text(row.after?.subtask_id)}</p>}
      {!timeline && <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
        {row.before && Object.keys(row.before).length > 0 && <div><span className="text-text-secondary">Previous values</span><SnapshotValues values={row.before} format={format} /></div>}
        {row.after && Object.keys(row.after).length > 0 && <div><span className="text-text-secondary">New values</span><SnapshotValues values={row.after} format={format} /></div>}
        {Object.keys(row.details).length > 0 && <div className="sm:col-span-2"><SnapshotValues values={row.details} format={format} /></div>}
      </div>}
    </li>)}
  </ol>;
});

function ChildTimeline({ taskId, child, format, page, change }: { taskId: string; child: InformationSubtask; format: (date: string | null) => string; page: number; change: (page: number) => void }) {
  const query = useInformation(taskId, { section: 'timeline', page, subtask_id: child.id });
  usePageBounds(query.isError ? undefined : query.data, page, change);
  return <div className="space-y-3 p-3"><p>Created: {format(child.created_at)}</p>
    {query.isError ? <p role="alert">Unable to load subtask history. <button className={button} onClick={() => query.refetch()}>Retry</button></p>
      : !query.data ? <p role="status">Loading subtask history…</p>
        : <><History rows={query.data.items as InformationEvent[]} format={format} timeline /><Pager data={query.data} page={page} change={change} /></>}
  </div>;
}

const Subtasks = React.memo(function Subtasks({ taskId, rows, format, expanded, setExpanded, childPage, childPageChange }: {
  taskId: string; rows: InformationSubtask[]; format: (date: string | null) => string;
  expanded: string | null; setExpanded: (id: string | null) => void; childPage: number; childPageChange: (page: number) => void;
}) {
  const id = useId();
  return <>
    <p className="mb-3 text-sm text-text-secondary">Elapsed is contributor activity time at the snapshot. Productive time uses confirmed work intervals. Deleted records retain history and have no available reward.</p>
    <div className="overflow-x-auto rounded-xl border border-border-color" tabIndex={0} role="region" aria-label="Subtask information table">
      <table className="w-full min-w-[1250px] text-left text-sm"><caption className="sr-only">Subtask planning, manually confirmed times, activity and ledger information</caption><thead className="bg-background text-text-secondary"><tr>
        {['Subtask / history', 'Assignee', 'Priority', 'Planned dates', 'Manual actual times', 'Status', 'Elapsed / productive', 'Additional points'].map(label => <th className="p-3 font-medium" scope="col" key={label}>{label}</th>)}
      </tr></thead><tbody>{rows.map(row => {
        return <React.Fragment key={row.id}><tr className="border-t border-border-color align-top">
          <td className="max-w-xs p-3"><strong className="break-words">{row.name}</strong><div className="mt-2"><button className={button} aria-label={`Status history for ${row.name}`} aria-expanded={expanded === row.id} aria-controls={expanded === row.id ? `${id}-${row.id}` : undefined} onClick={() => setExpanded(expanded === row.id ? null : row.id)}>Status history</button></div></td>
          <td className="p-3">{row.assignee?.name ?? 'Unassigned'}</td><td className="p-3">{row.effective_priority}<div className="text-xs text-text-secondary">{row.priority_inherited ? 'Inherited' : 'Override'}</div></td>
          <td className="p-3">{row.planned_start_date ?? 'Not recorded'}<br />{row.planned_end_date ?? 'Not recorded'}</td>
          <td className="p-3">{format(row.actual_start_at)}<br />{format(row.actual_end_at)}</td>
          <td className="p-3">{status(row.status)}<div className="text-xs">{row.completed ? 'Completed' : 'Incomplete'}{row.deleted_at ? ' · Deleted' : ''}</div></td>
          <td className="p-3">{workDuration(row.elapsed_seconds)} elapsed<br />{workDuration(row.productive_seconds)} productive</td>
          <td className="p-3">{row.additional_base_value} base capacity<br />{row.available_base} available · {row.earned ?? 'Unknown legacy'} net earned
            <div className="text-xs text-text-secondary">Bonus {row.components.BONUS ?? 0} · Penalty {row.components.PENALTY ?? 0} · Reversals {row.components.REVERSAL ?? 0}</div>
            <div className="text-xs text-text-secondary">{row.policy_version}</div></td>
        </tr>{expanded === row.id && <tr id={`${id}-${row.id}`}><td colSpan={8}><ChildTimeline taskId={taskId} child={row} format={format} page={childPage} change={childPageChange} /></td></tr>}</React.Fragment>;
      })}</tbody></table>
    </div>{!rows.length && <p className="py-6 text-text-secondary">No matching subtasks.</p>}
  </>;
});

function Content({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const { user } = useAuth();
  const [tab, setTab] = useState(0);
  const [pages, setPages] = useState<Record<string, number>>({});
  const [search, setSearch] = useState('');
  const [settledSearch, setSettledSearch] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const section = sections[tab].key;
  const page = pages[section] ?? 1;
  const query = useInformation(taskId, { section, page, ...(section === 'subtasks' ? { search: settledSearch } : {}) });
  const client = useQueryClient();
  const token = getAccessToken();
  const scope = useMemo(() => informationScope(taskId, user), [taskId, user?.id, user?.role, user?.departmentId, user?.status, token]);
  useEffect(() => {
    if (search === settledSearch) return;
    const timer = window.setTimeout(() => { setSettledSearch(search); setPages(p => ({ ...p, subtasks: 1 })); }, 250);
    return () => window.clearTimeout(timer);
  }, [search, settledSearch]);
  useEffect(() => {
    const queued = coalesceActivityRefresh(() => {
      void client.invalidateQueries({ queryKey: scope, refetchType: document.hidden ? 'none' : 'active' });
    });
    const refresh = () => queued.request();
    const visible = () => { if (!document.hidden) refresh(); };
    const names = [TASKS_CHANGED_EVENT, TASK_ACTIVITY_CHANGED, APP_REFRESH_EVENT, 'online', 'focus'];
    names.forEach(name => window.addEventListener(name, refresh));
    document.addEventListener('visibilitychange', visible);
    const recovery = window.setInterval(visible, 30_000 + Math.floor(Math.random() * 5000));
    return () => {
      queued.cancel(); window.clearInterval(recovery);
      names.forEach(name => window.removeEventListener(name, refresh));
      document.removeEventListener('visibilitychange', visible);
      void client.cancelQueries({ queryKey: scope });
      client.removeQueries({ queryKey: scope });
    };
  }, [client, scope]);
  const zone = useMemo(() => informationZone(user?.timezone), [user?.timezone]);
  const format = useCallback((date: string | null) => formatInformationTime(date, zone), [zone]);
  const changePage = useCallback((next: number) => setPages(p => ({ ...p, [section]: next })), [section]);
  const childPageChange = useCallback((next: number) => setPages(p => ({ ...p, [`child:${expanded}`]: next })), [expanded]);
  const data = query.isError ? undefined : query.data;
  usePageBounds(data, page, changePage);
  const overview = data?.overview;
  const points = data?.points;
  const fields: [string, React.ReactNode][] = overview ? [
    ['Task ID', overview.id], ['Name', overview.name], ['Description', overview.description || 'No description'],
    ['Project', overview.project ?? 'Not supported on parent tasks'], ['Team', overview.team],
    ['Creator', overview.creator?.name ?? 'Not recorded'], ['Assignees', overview.assignees.map(p => p.name).join(', ') || 'Unassigned'],
    ['Priority', overview.priority], ['Status', status(overview.status)],
    ['Planned start', overview.planned_start_date ?? 'Not supported on parent tasks'], ['Planned end', overview.planned_end_date ?? 'Not supported on parent tasks'],
    ['Manual actual start', format(overview.actual_start_at)], ['Manual actual end', format(overview.actual_end_at)],
    ['Estimated duration', overview.estimated_hours == null ? 'Not recorded' : `${overview.estimated_hours} hours`],
    ['Manual productive duration', workDuration(overview.productive_seconds)], ['Elapsed activity', workDuration(overview.elapsed_seconds)],
    ['Created', format(overview.created_at)], ['Assigned', format(overview.assigned_at)], ['Updated', format(overview.updated_at)],
    ['Due date', format(overview.due_at)], ['Completed', format(overview.completed_at)],
    ['Approval', `${overview.approval_status}${overview.approval_required ? ' · Required' : ''}`],
  ] : [];
  return <DialogPanel className="mx-auto flex max-h-[92dvh] w-full max-w-6xl flex-col rounded-2xl border border-border-color bg-surface text-text-primary shadow-2xl">
    <div className="flex items-start justify-between gap-3 border-b border-border-color p-4 sm:p-6"><div><DialogTitle className="text-xl font-semibold">Task information</DialogTitle>
      <DialogDescription className="mt-1 break-all text-xs text-text-secondary">{taskId} · Times in {zone}</DialogDescription></div>
      <button className={button} onClick={onClose} aria-label="Close task information"><X className="h-5 w-5" /></button></div>
    <TabGroup selectedIndex={tab} onChange={setTab} className="flex min-h-0 flex-1 flex-col">
      <TabList className="flex shrink-0 gap-1 overflow-x-auto border-b border-border-color px-3 py-2" aria-label="Task information sections">
        {sections.map(item => <Tab key={item.key} className="shrink-0 rounded-lg px-3 py-2 text-sm font-medium text-text-secondary data-[selected]:bg-primary/15 data-[selected]:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">{item.title}</Tab>)}
      </TabList>
      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
        {section === 'subtasks' && <label className="mb-4 block text-sm">Search subtasks<input className="mt-1 block w-full rounded-lg border border-border-color bg-background px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary" value={search} maxLength={200} onChange={e => setSearch(e.target.value)} /></label>}
        <TabPanels>{sections.map(item => <TabPanel key={item.key}>
          {query.isError ? <div role="alert">Unable to load task information. <button className={button} onClick={() => query.refetch()}>Retry</button></div>
            : !data || data.section !== item.key ? <p role="status">Loading task information…</p>
              : <div className="space-y-4">
                <p className="text-xs text-text-secondary">Snapshot {format(data.as_of)}{query.isFetching ? ' · Refreshing…' : ''}</p>
                {item.key === 'overview' && overview && <><dl className="grid gap-4 sm:grid-cols-2">{fields.map(([label, value]) => <div key={label} className="min-w-0 rounded-xl border border-border-color p-3"><dt className="text-xs text-text-secondary">{label}</dt><dd className="mt-1 whitespace-pre-wrap break-words text-sm">{value}</dd></div>)}</dl><ul className="list-disc space-y-1 pl-5 text-xs text-text-secondary">{overview.limitations.map(note => <li key={note}>{note}</li>)}</ul></>}
                {item.key === 'timeline' && <><p className="text-sm">Created: {format(data.created_at)}</p><History rows={data.items as InformationEvent[]} format={format} timeline /><p className="text-xs text-text-secondary">Expand a subtask's Status history in the Subtasks tab for its individual timeline.</p></>}
                {item.key === 'subtasks' && <Subtasks taskId={taskId} rows={data.items as InformationSubtask[]} format={format} expanded={expanded} setExpanded={setExpanded} childPage={pages[`child:${expanded}`] ?? 1} childPageChange={childPageChange} />}
                {item.key === 'points' && points && <>
                  <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{([
                    ['Main task base value (current configuration)', points.main_base_value], ['Main task earned', points.main_earned],
                    ['Main task verified ledger subtotal', points.main_recorded_net],
                    ['Subtask base capacity', points.subtask_base_capacity], ['Subtask available base (incomplete)', points.subtask_available_base], ['Subtask net earned', points.subtask_earned],
                    ['Posted base', points.components.BASE], ['Posted bonus', points.components.BONUS], ['Posted penalty', points.components.PENALTY],
                    ['Other adjustments', points.components.ADJUSTMENT], ['Reversal adjustments (signed)', points.components.REVERSAL],
                    ['Verified ledger net earned', points.verified_net_earned], ['Full task net earned', points.total_net_earned],
                  ] as [string, number | null][]).map(([label, value]) => <div className="rounded-xl border border-border-color p-3" key={label}><dt className="text-xs text-text-secondary">{label}</dt><dd className="mt-1 text-lg font-semibold">{value ?? 'Unknown — incomplete history'}</dd></div>)}</dl>
                  <p className="text-sm text-text-secondary">{points.coverage}</p>
                  {points.main_recorded_components && <div className="grid gap-3 text-sm sm:grid-cols-2"><div><h4 className="font-medium">Main task ledger components</h4><p>{Object.entries(points.main_recorded_components).map(([key, value]) => `${key} ${value}`).join(' · ')}</p></div><div><h4 className="font-medium">Subtask ledger components</h4><p>{Object.entries(points.subtask_components).map(([key, value]) => `${key} ${value}`).join(' · ')}</p></div></div>}
                  <h3 className="font-semibold">Recipient distribution · verified ledger</h3>
                  {points.recipients.length ? <ul className="space-y-3">{points.recipients.map(recipient => <li key={recipient.id} className="rounded-xl border border-border-color p-3"><strong>{recipient.name}: {recipient.net}</strong>{recipient.main_net != null && <p className="text-sm">Main task {recipient.main_net} · Subtasks {recipient.subtask_net}</p>}<p className="mt-1 text-xs text-text-secondary">{Object.entries(recipient.components).map(([key, value]) => `${key} ${value}`).join(' · ')}</p></li>)}</ul> : <p className="text-text-secondary">No recorded task-linked rewards.</p>}
                </>}
                {item.key === 'activity' && <History rows={data.items as InformationEvent[]} format={format} />}
                {['timeline', 'subtasks', 'activity'].includes(item.key) && <Pager data={data} page={page} change={changePage} />}
                <p className="text-xs text-text-secondary">{data.coverage}</p>
              </div>}
        </TabPanel>)}</TabPanels>
      </div>
    </TabGroup>
  </DialogPanel>;
}

function Session({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const { user } = useAuth();
  const [token, setToken] = useState(getAccessToken);
  useEffect(() => {
    const changed = () => setToken(getAccessToken());
    window.addEventListener('storage', changed); window.addEventListener('focus', changed);
    return () => { window.removeEventListener('storage', changed); window.removeEventListener('focus', changed); };
  }, []);
  return <Content key={JSON.stringify([user?.id, user?.role, user?.departmentId, user?.status, token])} taskId={taskId} onClose={onClose} />;
}

export default function TaskInformationModal({ taskId, isOpen, onClose }: { taskId: string; isOpen: boolean; onClose: () => void }) {
  return <Dialog open={isOpen} onClose={onClose} className="fixed inset-0 z-[110]">
    <div className="fixed inset-0 bg-black/75" aria-hidden="true" />
    <div className="fixed inset-0 flex items-center justify-center p-2 sm:p-6">{isOpen && <Session key={taskId} taskId={taskId} onClose={onClose} />}</div>
  </Dialog>;
}
