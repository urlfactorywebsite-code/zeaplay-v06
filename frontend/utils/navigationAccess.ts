import type { NavigationPolicy } from '../types/navigation';
import { LEGACY_SETTINGS_ROUTES, SETTINGS_TABS } from './settingsNavigation';
import { LEGACY_TASK_ROUTES, TASK_TABS } from './taskNavigation';

export function validateNavigationPolicy(value: NavigationPolicy): NavigationPolicy {
  if (!value || typeof value.tenantId !== 'string' || !value.tenantId || !Number.isInteger(value.version) || value.version < 0 || !Array.isArray(value.pages)
      || !Array.isArray(value.roles) || !value.roles.every(role => typeof role === 'string')) throw new Error('Invalid navigation response');
  const ids = new Set<string>(), routes = new Map<string, string>();
  for (const page of value.pages) {
    const defaultTaskTab = page?.id === 'tasks.list' && page.parentId === 'tasks' && page.route === '/tasks' && page.navigationLocation === 'task-tab' && routes.get('/tasks') === 'tasks';
    if (!page || typeof page.id !== 'string' || ids.has(page.id) || typeof page.route !== 'string' || (routes.has(page.route) && !defaultTaskTab)
        || !['allowed', 'disabled', 'forbidden'].includes(page.access) || typeof page.visible !== 'boolean'
        || typeof page.enabled !== 'boolean' || typeof page.hidden !== 'boolean' || !Array.isArray(page.permittedRoles)
        || !Array.isArray(page.allowedRoles) || !page.allowedRoles.every(role => page.permittedRoles.includes(role))) throw new Error('Invalid navigation page');
    ids.add(page.id); routes.set(page.route, page.id);
  }
  if (!ids.has('settings') || SETTINGS_TABS.some(tab => !routes.has(tab.path)) || TASK_TABS.some(tab => !value.pages.some(page => page.id === tab.pageId && page.route === tab.path))) throw new Error('Incomplete navigation registry');
  return value;
}

export function navigationPage(policy: NavigationPolicy, pathname: string, search: string) {
  let normalized = pathname;
  try { normalized = decodeURIComponent(normalized); } catch { /* router rejects malformed paths */ }
  normalized = normalized.replace(/\/+$/, '').toLowerCase() || '/';
  const path = LEGACY_TASK_ROUTES[normalized] || LEGACY_SETTINGS_ROUTES[normalized] || normalized;
  const task = TASK_TABS.find(tab => tab.path === path);
  if (task) return policy.pages.find(page => page.id === task.pageId);
  if (path.startsWith('/chat/')) return policy.pages.find(page => page.id === 'chat');
  if (path === '/achievements') {
    const tab = new URLSearchParams(search).get('tab');
    if (tab && ['points', 'templates', 'levels'].includes(tab)) return policy.pages.find(page => page.id === tab);
  }
  return policy.pages.find(page => page.route === path);
}
