import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './useAuth';
import api from '../services/mockApi';
import type { NavigationPolicy } from '../types/navigation';
import { applySidebarPreferences, emptySidebarPreferences, readSidebarPreferences, sidebarStorageKey, SidebarPreferences } from '../utils/sidebarPreferences';
import PageLoader from '../components/loading/PageLoader';
import { navigationPage, validateNavigationPolicy } from '../utils/navigationAccess';

type NavigationContextValue = {
  policy: NavigationPolicy | null; error: string; validatedLocation: string;
  preferences: SidebarPreferences; refresh: () => Promise<NavigationPolicy | null>;
  savePreferences: (value: SidebarPreferences) => void;
};
const NavigationContext = createContext<NavigationContextValue | null>(null);
export const navigationError = (error: unknown) => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : 'Unable to load or save navigation configuration. Please retry.';
};

export function NavigationProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const { pathname, search } = useLocation();
  const locationKey = pathname + search;
  const [policy, setPolicy] = useState<NavigationPolicy | null>(null);
  const [policyIdentity, setPolicyIdentity] = useState('');
  const [error, setError] = useState('');
  const [validatedLocation, setValidatedLocation] = useState('');
  const [preferences, setPreferences] = useState<SidebarPreferences>(emptySidebarPreferences);
  const generation = useRef(0);
  const loadedStorageKey = useRef('');
  const identity = user ? `${user.id}:${user.role}` : '';
  const refresh = useCallback(async () => {
    const request = ++generation.current;
    if (!user) { loadedStorageKey.current = ''; setPolicy(null); setError(''); return null; }
    try {
      const next = validateNavigationPolicy(await api.getNavigationPolicy());
      if (request !== generation.current) return null;
      const nextKey = sidebarStorageKey(next.tenantId, user.id);
      if (nextKey !== loadedStorageKey.current) {
        setPreferences(readSidebarPreferences(localStorage, next.tenantId, user.id, next.pages));
        loadedStorageKey.current = nextKey;
      }
      setPolicyIdentity(identity);
      setPolicy(next); setError(''); setValidatedLocation(locationKey);
      return next;
    } catch (failure) {
      if (request === generation.current) setError(navigationError(failure));
      return null;
    }
  }, [user?.id, user?.role, locationKey]);
  useEffect(() => {
    void refresh();
    const revalidate = () => { if (document.visibilityState !== 'hidden') void refresh(); };
    window.addEventListener('focus', revalidate);
    document.addEventListener('visibilitychange', revalidate);
    // Existing streams are domain-scoped; polling also works across API workers.
    const timer = window.setInterval(revalidate, 30000);
    return () => { ++generation.current; window.clearInterval(timer); window.removeEventListener('focus', revalidate); document.removeEventListener('visibilitychange', revalidate); };
  }, [refresh]);
  const storageKey = policy && user ? sidebarStorageKey(policy.tenantId, user.id) : '';
  useEffect(() => {
    if (!policy || !user) { setPreferences(emptySidebarPreferences()); return; }
    const load = () => setPreferences(readSidebarPreferences(localStorage, policy.tenantId, user.id, policy.pages));
    const changed = (event: StorageEvent) => { if (event.key === storageKey) load(); };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, [storageKey]);
  const savePreferences = (value: SidebarPreferences) => {
    if (!storageKey) throw new Error('Navigation identity is unavailable.');
    localStorage.setItem(storageKey, JSON.stringify(value));
    setPreferences(value);
  };
  return <NavigationContext.Provider value={{ policy: policyIdentity === identity ? policy : null, preferences: policyIdentity === identity ? preferences : emptySidebarPreferences(), error, validatedLocation, refresh, savePreferences }}>{children}</NavigationContext.Provider>;
}

export const useNavigation = () => {
  const context = useContext(NavigationContext);
  if (!context) throw new Error('NavigationProvider is required.');
  return { ...context, pages: applySidebarPreferences(context.policy?.pages || [], context.preferences) };
};

export function NavigationAccess({ children }: { children: React.ReactNode }) {
  const { policy, error, validatedLocation, refresh } = useNavigation();
  const { pathname, search } = useLocation();
  const failure = error ? <div role="alert" className="rounded-xl border border-border-color bg-surface p-6"><p>{error}</p><button className="mt-3 rounded border border-border-color px-4 py-2" onClick={() => void refresh()}>Retry navigation configuration</button></div> : null;
  if (!policy || validatedLocation !== pathname + search) return failure || <PageLoader />;
  const page = navigationPage(policy, pathname, search);
  if (page && page.access !== 'allowed') return <Navigate to="/settings/profile" replace state={{ navigationDenial: page.access === 'disabled' ? `${page.defaultLabel} is disabled by your organization. Its data is preserved.` : `Your role does not have access to ${page.defaultLabel}.` }} />;
  // Keep an existing draft mounted but inaccessible during a transient policy
  // failure. Never mount a new route before its authoritative validation.
  return <>{failure}<div hidden={!!error} inert={!!error}>{children}</div></>;
}
