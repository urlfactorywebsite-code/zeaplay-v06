// Route identities only. Authorization and labels come from the server registry.
const keys = ['profile', 'support', 'master-control', 'api', 'mcp-management', 'logs', 'media-library', 'sidebar-management'] as const;
export type SettingsTabKey = typeof keys[number];
export const SETTINGS_TABS = keys.map(key => ({ key, path: `/settings/${key}` }));

export const LEGACY_SETTINGS_ROUTES: Record<string, string> = {
  '/profile': '/settings/profile',
  '/support': '/settings/support',
  '/master-control': '/settings/master-control',
  '/api/overview': '/settings/api',
  '/logs': '/settings/logs',
  '/media': '/settings/media-library',
};
