import React, { Suspense, useEffect, useRef } from 'react';
import { matchPath, NavLink, Outlet, useLocation } from 'react-router-dom';
import { Settings as SettingsIcon, UserRound, LifeBuoy, ShieldCheck, Code, ScrollText, Images, PanelLeft } from 'lucide-react';
import { useNavigation } from '../hooks/useNavigation';
import PageLoader from '../components/loading/PageLoader';
import { SettingsTabKey } from '../utils/settingsNavigation';
import { UnsavedChangesProvider } from '../hooks/useUnsavedChanges';

const tabIcons = {
  profile: UserRound,
  support: LifeBuoy,
  'master-control': ShieldCheck,
  api: Code,
  logs: ScrollText,
  'media-library': Images,
  'sidebar-management': PanelLeft,
} satisfies Record<SettingsTabKey, typeof UserRound>;

const Settings: React.FC = () => {
  const { pages } = useNavigation();
  const { pathname } = useLocation();
  const tabs = pages.filter(page => page.navigationLocation === 'settings-tab' && page.visible).map(page => ({ key: page.id.slice('settings.'.length) as SettingsTabKey, path: page.route, label: page.label }));
  const activeTab = tabs.find((tab) => matchPath(tab.path, pathname));
  const tabList = useRef<HTMLDivElement>(null);
  useEffect(() => {
    tabList.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [activeTab?.key]);
  useEffect(() => {
    const list = tabList.current;
    if (!list) return;
    const observer = new ResizeObserver(() => {
      const selected = list.querySelector<HTMLElement>('[aria-selected="true"]');
      if (!selected) return;
      const container = list.getBoundingClientRect(), tab = selected.getBoundingClientRect();
      if (tab.left < container.left) list.scrollLeft -= container.left - tab.left;
      else if (tab.right > container.right) list.scrollLeft += tab.right - container.right;
    });
    observer.observe(list);
    return () => observer.disconnect();
  }, []);

  // Manual activation avoids loading a page while exploring the tab bar.
  const handleTabKeyDown = (event: React.KeyboardEvent<HTMLAnchorElement>, index: number) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      if (event.key === ' ') {
        event.preventDefault();
        event.currentTarget.click();
      }
      return;
    }
    event.preventDefault();
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    const next = event.currentTarget.parentElement?.querySelectorAll<HTMLAnchorElement>('[role="tab"]')[nextIndex];
    next?.focus();
    next?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  };

  return (
    <div className="min-w-0 space-y-6 pb-12">
      <header className="rounded-xl border border-border-color bg-surface p-5 shadow-sm sm:p-6">
        <div className="flex items-start gap-3">
          <SettingsIcon className="mt-1 h-7 w-7 shrink-0 text-primary" aria-hidden="true" />
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold text-text-primary">Settings</h1>
            <p className="mt-1 text-sm text-text-secondary">
              Manage your profile, application configuration, integrations, support, and administrative controls.
            </p>
          </div>
        </div>
        <div ref={tabList} role="tablist" aria-label="Settings" aria-orientation="horizontal" className="mt-6 flex gap-2 overflow-x-auto pb-2">
          {tabs.map((tab, index) => {
            const Icon = tabIcons[tab.key];
            const selected = tab === activeTab;
            return (
              <NavLink
                key={tab.key}
                to={tab.path}
                role="tab"
                id={`settings-tab-${tab.key}`}
                aria-selected={selected}
                aria-controls="settings-panel"
                tabIndex={selected || (!activeTab && index === 0) ? 0 : -1}
                onKeyDown={(event) => handleTabKeyDown(event, index)}
                className={`flex shrink-0 items-center gap-2 whitespace-nowrap rounded-lg border px-4 py-2 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface ${selected
                  ? 'border-primary bg-primary/15 text-primary shadow-sm'
                  : 'border-border-color text-text-secondary hover:border-primary/40 hover:bg-primary/5 hover:text-text-primary'}`}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {tab.label}
              </NavLink>
            );
          })}
        </div>
      </header>
      <section id="settings-panel" role="tabpanel" aria-labelledby={activeTab ? `settings-tab-${activeTab.key}` : undefined} tabIndex={0} className="min-w-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
        <Suspense fallback={<PageLoader />}>
          <Outlet />
        </Suspense>
      </section>
    </div>
  );
};

const SettingsWithDraftProtection: React.FC = () => <UnsavedChangesProvider><Settings /></UnsavedChangesProvider>;
export default SettingsWithDraftProtection;
