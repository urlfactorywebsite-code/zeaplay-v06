import React, { createContext, useCallback, useContext, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { updateTaskFilter } from '../utils/taskNavigation';
import { useSearch } from './useAuth';

type Filters = { search: string; set: (key: string, value: React.SetStateAction<string>, empty: string) => void };
const Context = createContext<Filters | null>(null);
export const TaskViewActive = createContext(true);
export function TaskFiltersProvider({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { searchQuery } = useSearch();
  const currentSearch = useRef(searchQuery);
  currentSearch.current = searchQuery;
  const latest = useRef(location);
  latest.current = location;
  const set = useCallback<Filters['set']>((key, value, empty) => {
    const current = latest.current;
    const previous = new URLSearchParams(current.search).get(key) || empty;
    const next = typeof value === 'function' ? value(previous) : value;
    const base = key === 'search' ? current.search : updateTaskFilter(current.search, 'search', currentSearch.current);
    const search = updateTaskFilter(base, key, next);
    latest.current = { ...current, search: search ? `?${search}` : '' };
    navigate({ pathname: current.pathname, search, hash: current.hash }, { replace: true, state: current.state });
  }, [navigate]);
  return <Context.Provider value={{ search: location.search, set }}>{children}</Context.Provider>;
}
/** One URL contract; each view only consumes filters it already supports. */
export function useTaskFilter<T extends string = string>(key: string, empty: T = '' as T): [T, React.Dispatch<React.SetStateAction<T>>] {
  const context = useContext(Context);
  if (!context) throw new Error('TaskFiltersProvider is required');
  const setter = useCallback<React.Dispatch<React.SetStateAction<T>>>(value => context.set(key, previous => typeof value === 'function' ? value((previous || empty) as T) : value, empty), [context.set, key, empty]);
  return [(new URLSearchParams(context.search).get(key) || empty) as T, setter];
}
export const useTaskViewActive = () => useContext(TaskViewActive);
