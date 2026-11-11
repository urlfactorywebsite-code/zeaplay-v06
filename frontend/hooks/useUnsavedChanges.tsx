import React, { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { useBeforeUnload, useBlocker } from 'react-router-dom';

const MESSAGE = 'You have unsaved changes. Discard them and leave this page?';
const UnsavedChangesContext = createContext<{
  register: (id: symbol, dirty: boolean) => void;
  confirmDiscard: () => boolean;
} | null>(null);

export const UnsavedChangesProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const drafts = useRef(new Set<symbol>());
  const register = useCallback((id: symbol, value: boolean) => {
    if (value) drafts.current.add(id); else drafts.current.delete(id);
  }, []);
  const confirmDiscard = useCallback(() => !drafts.current.size || window.confirm(MESSAGE), []);
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    drafts.current.size > 0 && nextLocation.pathname !== '/login' && currentLocation.pathname !== nextLocation.pathname,
  );
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    if (window.confirm(MESSAGE)) blocker.proceed(); else blocker.reset();
  }, [blocker]);
  useBeforeUnload(useCallback((event: BeforeUnloadEvent) => {
    if (!drafts.current.size) return;
    event.preventDefault();
    event.returnValue = '';
  }, []));
  const context = useMemo(() => ({ register, confirmDiscard }), [register, confirmDiscard]);
  return <UnsavedChangesContext.Provider value={context}>{children}</UnsavedChangesContext.Provider>;
};

export const useUnsavedChanges = (dirty: boolean) => {
  const context = useContext(UnsavedChangesContext);
  const id = useRef(Symbol('settings-draft'));
  const register = context?.register;
  // Register before the next user interaction; passive registration left a gap
  // in which a quick tab change could discard Sidebar Management edits.
  useLayoutEffect(() => {
    register?.(id.current, dirty);
    return () => register?.(id.current, false);
  }, [register, dirty]);
  return context?.confirmDiscard ?? (() => true);
};
