import React, { Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Navigate, NavLink, useLocation } from 'react-router-dom';
import { CalendarDays, ChartGantt, Columns3, ListTodo } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth, useSearch } from '../hooks/useAuth';
import { useNavigation } from '../hooks/useNavigation';
import { TaskFiltersProvider, TaskViewActive } from '../hooks/useTaskView';
import { TASK_TABS, taskTabForPath, taskDetailIdFromPath, TaskTabKey } from '../utils/taskNavigation';
import { TASKS_CHANGED_EVENT, notifyTasksChanged } from '../utils/taskEvents';
import PageLoader from '../components/loading/PageLoader';
import NotFound from './NotFound';
import api from '../services/mockApi';

const views = {
  list: React.lazy(() => import('./Tasks')),
  kanban: React.lazy(() => import('./KanbanBoard')),
  gantt: React.lazy(() => import('./GanttView')),
  calendar: React.lazy(() => import('./CalendarView')),
};
const icons = { list: ListTodo, kanban: Columns3, gantt: ChartGantt, calendar: CalendarDays };

function TaskPanels() {
  const { user } = useAuth();
  const { pages, policy, error, validatedLocation, refresh } = useNavigation();
  const location = useLocation();
  const { searchQuery, setSearchQuery } = useSearch();
  const active = taskTabForPath(location.pathname);
  const [visited, setVisited] = useState<TaskTabKey[]>([]);
  const queryClient = useQueryClient();
  const list = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { void queryClient.invalidateQueries({ queryKey: ['tasks'], refetchType: 'none' }); api.clearTaskViewCache(); }, [queryClient]);
  const ready = !!policy && validatedLocation === location.pathname + location.search;
  const page = pages.find(page => page.id === active?.pageId);
  const allowed = ready && page?.access === 'allowed' && !error;
  const tabs = pages.filter(page => page.navigationLocation === 'task-tab' && page.visible)
    .flatMap(page => TASK_TABS.filter(tab => tab.pageId === page.id).map(tab => ({ ...tab, label: page.label })));
  useEffect(() => { if (allowed && active) setVisited(previous => previous.includes(active.key) ? previous : [...previous, active.key]); }, [allowed, active?.key]);
  const changed = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['tasks'] });
  }, [queryClient]);
  useEffect(() => { window.addEventListener(TASKS_CHANGED_EVENT, changed); return () => window.removeEventListener(TASKS_CHANGED_EVENT, changed); }, [changed]);
  // Search remains the established application search; the URL adds deep-link persistence.
  const initialSearch = useRef(false);
  useEffect(() => {
    const value = new URLSearchParams(location.search).get('search');
    if (value !== null || initialSearch.current) setSearchQuery(value || '');
    initialSearch.current = true;
  }, [location.search, setSearchQuery]);
  useEffect(() => {
    const reveal = () => list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    reveal();
    window.addEventListener('resize', reveal);
    if (allowed) window.dispatchEvent(new Event('resize'));
    return () => window.removeEventListener('resize', reveal);
  }, [active?.key, allowed]);
  const keyboard = (event: React.KeyboardEvent<HTMLAnchorElement>, index: number) => {
    if (event.key === ' ') { event.preventDefault(); event.currentTarget.click(); return; }
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    const link = list.current?.querySelectorAll<HTMLAnchorElement>('[role=tab]')[next];
    link?.focus(); link?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  };
  if (ready && active && page?.access !== 'allowed') return <Navigate to="/settings/profile" replace state={{ navigationDenial: 'Your organization does not allow access to this task view.' }} />;
  const detailId = taskDetailIdFromPath(location.pathname);
  if (detailId) {
    const params = new URLSearchParams(location.search);
    params.set('taskId', detailId);
    return <Navigate replace to={{ pathname: '/tasks', search: params.toString(), hash: location.hash }} state={location.state} />;
  }
  return <div className="tasks-hub min-w-0 space-y-6 pb-8">
    <header className="rounded-xl border border-border-color bg-surface p-5 shadow-sm sm:p-6">
      <div className="flex items-start gap-3"><ListTodo className="mt-1 h-7 w-7 shrink-0 text-primary" aria-hidden="true" />
        <div><h1 className="text-2xl font-semibold text-text-primary">All Tasks</h1>
          <p className="mt-1 text-sm text-text-secondary">Manage tasks, track progress, visualize workflows, and plan schedules.</p></div></div>
      <div ref={list} role="tablist" aria-label="Task views" className="mt-6 flex gap-2 overflow-x-auto pb-2">
        {tabs.map((tab, index) => { const Icon = icons[tab.key], selected = active?.key === tab.key;
          const params = new URLSearchParams(location.search);
          params.delete('search');
          if (searchQuery) params.set('search', searchQuery);
          return <NavLink end key={tab.key} to={{ pathname: tab.path, search: params.toString(), hash: location.hash }} state={location.state}
            role="tab" id={`tasks-tab-${tab.key}`} aria-selected={selected} aria-controls={`tasks-panel-${tab.key}`} tabIndex={selected || (!tabs.some(item => item.key === active?.key) && index === 0) ? 0 : -1}
            onKeyDown={event => keyboard(event, index)} className={`flex shrink-0 items-center gap-2 whitespace-nowrap rounded-lg border px-4 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${selected ? 'border-primary bg-primary/15 text-primary' : 'border-border-color text-text-secondary hover:border-primary/40'}`}>
            <Icon className="h-4 w-4" aria-hidden="true" />{tab.label}</NavLink>; })}
      </div>
    </header>
    {error && <div role="alert" className="rounded-xl border border-border-color p-5">{error}<button onClick={() => void refresh()} className="ml-3 underline">Retry navigation configuration</button></div>}
    {!ready && !error && <PageLoader />}
    {!active && ready && <NotFound />}
    {TASK_TABS.map(tab => {
      if (pages.find(page => page.id === tab.pageId)?.access !== 'allowed') return null;
      const mounted = visited.includes(tab.key) || (allowed && active?.key === tab.key);
      const View = views[tab.key], selected = allowed && active?.key === tab.key;
      return <section key={tab.key} hidden={!selected} inert={!selected} role="tabpanel" id={`tasks-panel-${tab.key}`} aria-labelledby={tabs.some(item => item.key === tab.key) ? `tasks-tab-${tab.key}` : undefined} aria-label={tab.label} className="min-w-0">
        {mounted && <TaskViewActive.Provider value={selected}><Suspense fallback={<PageLoader />}><View /></Suspense></TaskViewActive.Provider>}
      </section>;
    })}
  </div>;
}
export default function AllTasks() {
  const { user } = useAuth();
  const { policy } = useNavigation();
  return <TaskFiltersProvider><TaskPanels key={`${policy?.tenantId}:${user?.id}:${user?.role}`} /></TaskFiltersProvider>;
}
