// Adapted from the existing Zea sidebar preference utility. Keep the legacy
// account/tenant key untouched, and migrate route keys to stable page IDs.
import type { NavigationPage } from '../types/navigation';
export type SidebarPreferences = { order: string[]; labels: Record<string, string> };
export const emptySidebarPreferences = (): SidebarPreferences => ({ order: [], labels: {} });
export const sidebarStorageKey = (tenant: string, user: string) => `zea.sidebar.v2:${encodeURIComponent(tenant)}:${encodeURIComponent(user)}`;
export const legacySidebarStorageKey = (tenant: string, user: string) => `zea.sidebar.v1:${encodeURIComponent(tenant)}:${encodeURIComponent(user)}`;

export function parseSidebarPreferences(raw: string | null): SidebarPreferences {
  try {
    const value = JSON.parse(raw || 'null');
    if (!value || typeof value !== 'object') return emptySidebarPreferences();
    const order = Array.isArray(value.order) ? [...new Set<string>(value.order.filter((key: unknown): key is string => typeof key === 'string'))] : [];
    const labels: Record<string, string> = Object.create(null);
    if (value.labels && typeof value.labels === 'object' && !Array.isArray(value.labels)) {
      for (const [key, label] of Object.entries(value.labels)) {
        if (typeof label === 'string' && label.trim() && label.trim().length <= 48) labels[key] = label.trim();
      }
    }
    return { order, labels };
  } catch { return emptySidebarPreferences(); }
}

export function migrateSidebarPreferences(raw: string | null, pages: Pick<NavigationPage, 'id' | 'route'>[]): SidebarPreferences {
  const old = parseSidebarPreferences(raw);
  const aliases: Record<string, string> = { '/kanban': 'kanban', '/gantt': 'gantt', '/calendar': 'calendar', '/profile': 'settings.profile', '/support': 'settings.support', '/api/overview': 'settings.api', '/logs': 'settings.logs', '/media': 'settings.media-library', '/master-control': 'settings.master-control' };
  // The default task tab shares its parent's URL; old sidebar preferences belong
  // to the parent, while explicit tasks.list preferences remain independent.
  const ids = new Map(pages.flatMap(page => page.id === 'tasks.list' ? [[page.id, page.id]] : [[page.id, page.id], [page.route, page.id]]));
  const idFor = (key: string) => ids.get(key) || aliases[key] || key;
  return { order: [...new Set(old.order.map(idFor))], labels: Object.fromEntries(Object.entries(old.labels).map(([key, value]) => [idFor(key), value])) };
}

export function readSidebarPreferences(storage: Pick<Storage, 'getItem' | 'setItem'>, tenant: string, user: string, pages: NavigationPage[]) {
  try {
    const current = storage.getItem(sidebarStorageKey(tenant, user));
    if (current !== null) return parseSidebarPreferences(current);
    const legacy = storage.getItem(legacySidebarStorageKey(tenant, user));
    const migrated = migrateSidebarPreferences(legacy, pages);
    if (legacy !== null) {
      try { storage.setItem(sidebarStorageKey(tenant, user), JSON.stringify(migrated)); }
      catch { /* Read-only storage must not discard readable legacy preferences. */ }
    }
    return migrated;
  } catch { return emptySidebarPreferences(); }
}

export function applySidebarPreferences<T extends { id: string; defaultLabel: string }>(pages: T[], preferences: SidebarPreferences): (T & { label: string })[] {
  const byId = new Map(pages.map(page => [page.id, page]));
  return [...new Set([...preferences.order, ...byId.keys()])].filter(id => byId.has(id)).map(id => ({ ...byId.get(id)!, label: preferences.labels[id] || byId.get(id)!.defaultLabel }));
}
