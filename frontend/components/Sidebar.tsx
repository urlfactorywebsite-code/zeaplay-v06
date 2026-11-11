import { releaseVersionLabel } from '../utils/appVersion';
import React, { useEffect, useState } from 'react';

import { NavLink } from 'react-router-dom';
import { Menu, PanelLeftClose, Settings as SettingsIcon } from 'lucide-react';

import { useTheme } from '../hooks/useAuth';
import { useNavigation } from '../hooks/useNavigation';
import { navigationIcons } from '../utils/navigationIcons';

interface SidebarProps {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  onVersionClick: () => void;
  versionLabel?: string;
}

type ThemeKey = 'light' | 'dark' | 'colorful';

const THEME_ORDER: ThemeKey[] = ['dark', 'light', 'colorful'];

const THEME_ICON_URLS: Record<ThemeKey, string> = {
  dark: 'https://res.cloudinary.com/dqhcbck76/image/upload/v1770343927/moon_3_gy8i0p.png',
  light: 'https://res.cloudinary.com/dqhcbck76/image/upload/v1770343928/moon_ywhmbz.png',
  colorful: 'https://res.cloudinary.com/dqhcbck76/image/upload/v1770343927/moon_1_okpfg0.png',
};


const Sidebar: React.FC<SidebarProps> = ({ isCollapsed, onToggleCollapse, onVersionClick, versionLabel }) => {

    const { pages, error } = useNavigation();
    const { theme, setTheme } = useTheme();
    const [resolvedTheme, setResolvedTheme] = useState<ThemeKey>('light');
    const displayVersionLabel = releaseVersionLabel(versionLabel);



    useEffect(() => {
        if (typeof window === 'undefined') return;
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        const updateResolvedTheme = () => {
            if (theme === 'system') setResolvedTheme(mediaQuery.matches ? 'dark' : 'light');
            else setResolvedTheme(theme as ThemeKey);
        };
        updateResolvedTheme();
        mediaQuery.addEventListener('change', updateResolvedTheme);
        return () => mediaQuery.removeEventListener('change', updateResolvedTheme);
    }, [theme]);

    const activeTheme = (theme === 'system' ? resolvedTheme : theme) as ThemeKey;
    const handleThemeToggle = () => {
        const currentIndex = THEME_ORDER.indexOf(activeTheme);
        setTheme(THEME_ORDER[(currentIndex + 1) % THEME_ORDER.length]);
    };
    const themeLabel =
        activeTheme === 'dark' ? 'Dark Mode' : activeTheme === 'light' ? 'Light Mode' : 'Colorful Mode';

    const links = error ? [] : pages.filter(page => page.navigationLocation === 'sidebar' && page.desktop && page.visible);

    const navLinkClass = ({ isActive }: { isActive: boolean }) =>
        `sidebar-link flex items-center ${isCollapsed ? 'justify-center px-2' : 'space-x-3 px-4'} py-3 rounded-lg transition-all duration-300 ease-in-out ${
            isActive
                ? 'sidebar-link-active bg-blue-100 dark:bg-gray-900 text-gray-900 dark:text-white'
                : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-white'
        }`;



    return (

        <div
            className={`group/sidebar sidebar-shell sidebar-${activeTheme} relative border-r flex h-full flex-col rounded-2xl shadow-lg transition-all duration-300 lg:rounded-none lg:shadow-none ${isCollapsed ? 'w-16' : 'w-64'}`}
        >
            {isCollapsed && (
            <button
                type="button"
                onClick={onToggleCollapse}
                className="absolute left-1/2 top-4 z-40 flex h-10 w-10 -translate-x-1/2 items-center justify-center rounded-full border border-cyan-300/60 bg-slate-950/90 text-cyan-100 shadow-[0_0_14px_rgba(34,211,238,0.45)] transition duration-300 ease-in-out hover:scale-105 hover:border-cyan-200/80 hover:text-white focus-visible:opacity-100 focus-visible:pointer-events-auto dark:border-cyan-300/60 dark:bg-slate-950/90"
                aria-label="Expand sidebar"
            >
                <Menu className="h-5 w-5" strokeWidth={2.4} aria-hidden="true" />
            </button>
            )}
            {!isCollapsed && (
            <div className="px-4 pb-5 pt-7">
                <div className="flex items-center justify-center gap-2">
                    <button
                        type="button"
                        onClick={handleThemeToggle}
                        className="theme-pill-button mode-switch-button group flex h-10 items-center gap-2 rounded-full px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.28em]"
                        aria-label={themeLabel}
                    >
                        <img
                            src={THEME_ICON_URLS[activeTheme]}
                            alt={themeLabel}
                            className="h-6 w-6 object-contain drop-shadow-[0_0_8px_rgba(34,211,238,0.45)]"
                        />
                        <span className="hidden text-[10px] font-semibold uppercase tracking-[0.28em] sm:inline">
                            {themeLabel}
                        </span>
                    </button>
                    <button
                        type="button"
                        onClick={onToggleCollapse}
                        className="mode-switch-button flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition duration-300 ease-in-out hover:scale-105"
                        aria-label="Collapse sidebar"
                    >
                        <PanelLeftClose className="h-5 w-5" strokeWidth={2.4} aria-hidden="true" />
                    </button>
                </div>
            </div>
            )}
            <nav className={`flex-1 min-h-0 ${isCollapsed ? 'px-2 pt-16 pb-4' : 'px-4 pt-2 pb-6'} space-y-2 overflow-auto scrollbar-hide`} style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}>
                <style>{`nav::-webkit-scrollbar { display: none; }`}</style>
                {links.map((link) => (
                    <NavLink
                        key={link.id}
                        to={link.route}
                        className={navLinkClass}
                        title={isCollapsed ? link.label : undefined}
                        aria-label={link.label}
                    >
                        <span>{link.id === 'settings' ? <SettingsIcon className="h-6 w-6" aria-hidden="true" /> : <img src={navigationIcons[link.icon]} alt="" className="h-6 w-6 object-contain" />}</span>
                        {!isCollapsed && <span>{link.label}</span>}
                    </NavLink>
                ))}
            </nav>

            {!isCollapsed && (
            <div className="mt-auto px-4 py-3 border-t border-gray-200 dark:border-gray-900 text-sm">
                <button
                    type="button"
                    onClick={onVersionClick}
                    className="text-gray-400 hover:text-gray-200 transition"
                    aria-label="Open release notes"
                >
                    &copy; {displayVersionLabel}
                </button>
            </div>
            )}

        </div>

    );

};



export default Sidebar;

