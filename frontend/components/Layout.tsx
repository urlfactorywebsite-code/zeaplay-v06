import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
﻿

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useNavigation } from '../hooks/useNavigation';
import { navigationIcons } from '../utils/navigationIcons';
import { Menu, Settings as SettingsIcon } from 'lucide-react';
import Sidebar from './Sidebar';
import Header from './Header';
import TaskDetailModal from './TaskDetailModal';
import api from '../services/mockApi';
import { User, Role, ReleaseNotes, ReleaseNotesUpdate } from '../types';
import ClaimedRewardModal from './ClaimedRewardModal';
import Chatbot from './Chatbot';
import { APP_REFRESH_EVENT } from '../utils/appEvents';
import { useAuth, useTheme } from '../hooks/useAuth';
import { ToastProvider } from '../hooks/useToast';
import ReleaseNotesModal from './ReleaseNotesModal';
import ReleaseNotesEditorModal from './ReleaseNotesEditorModal';

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const { user } = useAuth();
  const { pages, error: navigationError } = useNavigation();
  const location = useLocation();
  const { theme } = useTheme();
  const [modalTaskId, setModalTaskId] = useState<string | null>(null);
  const [viewingRewardId, setViewingRewardId] = useState<string | null>(null);
  const [usersMap, setUsersMap] = useState<Map<string, User>>(new Map());
  const [isSidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [releaseNotes, setReleaseNotes] = useState<ReleaseNotes | null>(null);
  const [releaseNotesLoading, setReleaseNotesLoading] = useState(false);
  const [releaseNotesError, setReleaseNotesError] = useState<string | null>(null);
  const [releaseNotesSaving, setReleaseNotesSaving] = useState(false);
  const [isReleaseNotesOpen, setReleaseNotesOpen] = useState(false);
  const [isReleaseNotesEditorOpen, setReleaseNotesEditorOpen] = useState(false);
  const [isMobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [mobileMenuView, setMobileMenuView] = useState<'grid' | 'list'>('grid');

  const fetchUsers = useCallback(async () => {
    try {
      const allUsers = await api.getUsers();
      const map = new Map<string, User>();
      allUsers.forEach(u => map.set(u.id, u));
      setUsersMap(map);
    } catch (error) {
      console.error("Failed to fetch users for layout:", error);
    }
  }, []);

  const fetchReleaseNotes = useCallback(async () => {
    setReleaseNotesLoading(true);
    setReleaseNotesError(null);
    try {
      const notes = await api.getReleaseNotes();
      setReleaseNotes(notes);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to load release notes.';
      setReleaseNotesError(message);
    } finally {
      setReleaseNotesLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = () => {
      if (cancelled) return;
      fetchUsers();
    };
    if (refreshKey > 0) {
      run();
      return () => {
        cancelled = true;
      };
    }
    const idleWindow = window;
    if ('requestIdleCallback' in idleWindow) {
      const idleId = idleWindow.requestIdleCallback(run);
      return () => {
        cancelled = true;
        idleWindow.cancelIdleCallback(idleId);
      };
    }
    const timeoutId = window.setTimeout(run, 150);
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [fetchUsers, refreshKey]);

  useEffect(() => {
    fetchReleaseNotes();
  }, [fetchReleaseNotes]);

  useEffect(() => {
    const handleRefresh = () => {
      setRefreshKey((prev) => prev + 1);
    };
    window.addEventListener(APP_REFRESH_EVENT, handleRefresh);
    return () => window.removeEventListener(APP_REFRESH_EVENT, handleRefresh);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    if (window.innerWidth < 1024) {
      setSidebarCollapsed(true);
    }
  }, []);

  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 1024px)');
    const closeOnDesktop = () => { if (desktop.matches) setMobileMenuOpen(false); };
    desktop.addEventListener('change', closeOnDesktop);
    return () => desktop.removeEventListener('change', closeOnDesktop);
  }, []);

  const handleCloseModal = () => {
    setModalTaskId(null);
  };

  const handleTaskDeleted = (_taskId: string) => {
    setModalTaskId(null);
  };
  
  const handleCloseRewardModal = () => {
    setViewingRewardId(null);
  }

  const isOwner = user?.role === Role.OWNER;

  const mobileLinks = useMemo(() => navigationError ? [] : pages.filter(page => page.navigationLocation === 'sidebar' && page.mobile && page.visible).map(page => ({ to: page.route, label: page.label, icon: navigationIcons[page.icon] || '' })), [pages, navigationError]);

  const bottomBarLinks = useMemo(
    () => mobileLinks.filter((link) => ['/dashboard', '/tasks', '/kanban'].includes(String(link.to))),
    [mobileLinks],
  );

  const handleOpenReleaseNotes = () => {
    setReleaseNotesOpen(true);
    fetchReleaseNotes();
  };

  const handleCloseReleaseNotes = () => {
    setReleaseNotesOpen(false);
  };

  const handleOpenReleaseNotesEditor = () => {
    if (!isOwner) {
      return;
    }
    setReleaseNotesOpen(false);
    setReleaseNotesEditorOpen(true);
    if (!releaseNotes) {
      fetchReleaseNotes();
    }
  };

  const handleCloseReleaseNotesEditor = () => {
    setReleaseNotesEditorOpen(false);
  };

  const handleSaveReleaseNotes = async (payload: ReleaseNotesUpdate) => {
    setReleaseNotesSaving(true);
    try {
      const updated = await api.updateReleaseNotes(payload);
      setReleaseNotes(updated);
      setReleaseNotesEditorOpen(false);
      setReleaseNotesOpen(true);
    } catch (error) {
      throw error;
    } finally {
      setReleaseNotesSaving(false);
    }
  };

  return (
    <ToastProvider>
      <div className="flex h-screen flex-col bg-background text-text-primary">
        <Header 
        onNotificationClick={(taskId) => taskId && setModalTaskId(taskId)}
        onRewardNotificationClick={(rewardId) => rewardId && setViewingRewardId(rewardId)}
      />
      <div className="flex flex-1 overflow-hidden">
        <div className="hidden lg:block">
          <Sidebar
            isCollapsed={isSidebarCollapsed}
            onToggleCollapse={() => setSidebarCollapsed((prev) => !prev)}
            onVersionClick={handleOpenReleaseNotes}
            versionLabel={releaseNotes?.versionLabel}
          />
        </div>
        <main
          key={refreshKey}
          className={`layout-main-surface min-w-0 flex-1 overflow-x-hidden overflow-y-auto bg-background pt-4 pr-4 pb-24 pl-4 sm:pt-6 sm:pr-6 sm:pb-24 sm:pl-6 lg:p-6 ${theme === 'colorful' ? 'layout-main-colorful' : ''}`}
        >
        <style>
          {`
            @keyframes colorShift {
              0% { background-position: 0% 50%; }
              50% { background-position: 100% 50%; }
              100% { background-position: 0% 50%; }
            }
            @keyframes darkShift {
              0% { background-position: 0% 50%; }
              50% { background-position: 100% 50%; }
              100% { background-position: 0% 50%; }
            }
            @keyframes lightShift {
              0% { background-position: 0% 50%; }
              50% { background-position: 100% 50%; }
              100% { background-position: 0% 50%; }
            }
          `}
        </style>
        {location.state?.navigationDenial && <div role="alert" className="mb-4 rounded-xl border border-amber-500/50 bg-surface p-4 text-text-primary">{location.state.navigationDenial}</div>}
        {children}
      </main>
      </div>
      <div className="lg:hidden">
        <div className="mobile-nav-shell">
          {bottomBarLinks.slice(0, 2).map((link) => (
            <NavLink key={String(link.to)} to={link.to} className="mobile-nav-item" onClick={() => setMobileMenuOpen(false)}>
              <img src={link.icon} alt={link.label} className="h-5 w-5" />
              <span>{link.label}</span>
            </NavLink>
          ))}
          <button
            type="button"
            onClick={() => setMobileMenuOpen((prev) => !prev)}
            className="mobile-nav-center"
            aria-label="Open pages menu"
            aria-expanded={isMobileMenuOpen}
            aria-controls="mobile-pages-menu"
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </button>
          {bottomBarLinks.slice(2, 4).map((link) => (
            <NavLink key={String(link.to)} to={link.to} className="mobile-nav-item" onClick={() => setMobileMenuOpen(false)}>
              <img src={link.icon} alt={link.label} className="h-5 w-5" />
              <span>{link.label}</span>
            </NavLink>
          ))}
        </div>
        {isMobileMenuOpen && (
          <Dialog open={isMobileMenuOpen} onClose={() => setMobileMenuOpen(false)} className="fixed inset-0 z-[80]">
          <div className="mobile-menu-overlay" style={{ zIndex: 80 }}>
            <DialogPanel id="mobile-pages-menu" className="mobile-menu-card">
              <div className="mobile-menu-header">
                <DialogTitle>Pages</DialogTitle>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setMobileMenuView('grid')}
                    aria-pressed={mobileMenuView === 'grid'}
                    className={`mobile-menu-toggle ${mobileMenuView === 'grid' ? 'mobile-menu-toggle-active' : ''}`}
                  >
                    Grid
                  </button>
                  <button
                    type="button"
                    onClick={() => setMobileMenuView('list')}
                    aria-pressed={mobileMenuView === 'list'}
                    className={`mobile-menu-toggle ${mobileMenuView === 'list' ? 'mobile-menu-toggle-active' : ''}`}
                  >
                    List
                  </button>
                  <button type="button" onClick={() => setMobileMenuOpen(false)} className="mobile-menu-close">
                    Close
                  </button>
                </div>
              </div>
              <div className={`mobile-menu-grid ${mobileMenuView === 'list' ? 'mobile-menu-grid-list' : ''}`}>
                {mobileLinks.map((link) => (
                  <NavLink
                    key={String(link.to)}
                    to={link.to}
                    className={({ isActive }) => `mobile-menu-link ${link.to === '/settings' && isActive ? 'ring-2 ring-primary' : ''}`}
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    {link.to === '/settings' ? <SettingsIcon className="h-6 w-6" aria-hidden="true" /> : <img src={link.icon} alt={link.label} className="h-6 w-6" />}
                    <span>{link.label}</span>
                  </NavLink>
                ))}
              </div>
            </DialogPanel>
          </div>
          </Dialog>
        )}
      </div>
       {modalTaskId && (
        <TaskDetailModal
          taskId={modalTaskId}
          isOpen={!!modalTaskId}
          onClose={handleCloseModal}
          usersMap={usersMap}
          onTaskDeleted={handleTaskDeleted}
        />
      )}
      {viewingRewardId && (
        <ClaimedRewardModal
            isOpen={!!viewingRewardId}
            rewardId={viewingRewardId}
            onClose={handleCloseRewardModal}
        />
      )}
      {isReleaseNotesOpen && (
        <ReleaseNotesModal
          isOpen={isReleaseNotesOpen}
          onClose={handleCloseReleaseNotes}
          onEdit={handleOpenReleaseNotesEditor}
          isOwner={!!isOwner}
          isLoading={releaseNotesLoading}
          errorMessage={releaseNotesError}
          releaseNotes={releaseNotes}
        />
      )}
      {isReleaseNotesEditorOpen && (
        <ReleaseNotesEditorModal
          isOpen={isReleaseNotesEditorOpen}
          onClose={handleCloseReleaseNotesEditor}
          onSave={handleSaveReleaseNotes}
          isSaving={releaseNotesSaving}
          releaseNotes={releaseNotes}
        />
      )}
      <Chatbot />
    </div>
  </ToastProvider>
);
};

export default Layout;



