// Retain the artwork already used by the desktop and mobile navigation.
const base = 'https://res.cloudinary.com/dqhcbck76/image/upload/';
export const navigationIcons: Record<string, string> = Object.fromEntries(Object.entries({
  dashboard: 'v1770241422/dashboard_pvjlbg.png', tasks: 'v1770241423/task-actions_urhfeq.png',
  kanban: 'v1770241422/kanban_ysnojm.png', tickets: 'v1770343495/support-ticket_fku5gp.png',
  calendar: 'v1770241422/calendar_xbhksz.png', 'tool-library': 'v1770623739/open-box_ljkslo.png',
  users: 'v1770241423/Users_b58wty.png', gantt: 'v1770343495/gantt-chart_gjwr5s.png',
  reports: 'v1770343494/report_boqlo0.png', achievements: 'v1770241421/achivement_ckvs6i.png',
  points: 'v1770241423/points_jgi3yh.png', templates: 'v1770241423/layout_xgg1fa.png', levels: 'v1770241421/level-up_l6lcwq.png',
}).map(([key, path]) => [key, base + path]));
