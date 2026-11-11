export type NavigationRule = { enabled: boolean; hidden: boolean; allowedRoles: string[] };
export type NavigationPage = NavigationRule & {
  id: string; defaultLabel: string; route: string; permittedRoles: string[];
  parentId: string | null; isSystemProtected: boolean;
  navigationLocation: 'sidebar' | 'settings-tab' | 'task-tab'; desktop: boolean; mobile: boolean;
  icon: string; access: 'allowed' | 'disabled' | 'forbidden'; visible: boolean;
};
export type NavigationPolicy = {
  tenantId: string; version: number; updatedBy: string | null; updatedAt: string | null;
  roles: string[]; canManage: boolean; canChangeAccess: boolean; pages: NavigationPage[];
};
