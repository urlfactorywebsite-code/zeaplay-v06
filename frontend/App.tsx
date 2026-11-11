import { LEGACY_TASK_ROUTES } from './utils/taskNavigation';
﻿
import React, { Suspense } from 'react';
import { createHashRouter, RouterProvider, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { AuthProvider, useAuth, SearchProvider, ThemeProvider, useTheme } from './hooks/useAuth';
import { LoadingProvider } from './components/loading/LoadingProvider';
import PageLoader from './components/loading/PageLoader';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';
import Login from './pages/Login';
import NotFound from './pages/NotFound';
import { Role } from './types';
import PreserveLocationRedirect from './components/PreserveLocationRedirect';
import { LEGACY_SETTINGS_ROUTES, SETTINGS_TABS, SettingsTabKey } from './utils/settingsNavigation';
import { NavigationProvider } from './hooks/useNavigation';

const Dashboard = React.lazy(() => import('./pages/Dashboard'));
const AllTasks = React.lazy(() => import('./pages/AllTasks'));
const Users = React.lazy(() => import('./pages/Users'));
const Reports = React.lazy(() => import('./pages/Reports'));
const Settings = React.lazy(() => import('./pages/Settings'));
const ProfileSettings = React.lazy(() => import('./pages/ProfileSettings'));
const SupportForm = React.lazy(() => import('./components/SupportFormModal'));
const Achievements = React.lazy(() => import('./pages/Achievements'));
const ApiOverview = React.lazy(() => import('./pages/ApiOverview'));
const MediaLibraryPage = React.lazy(() => import('./pages/MediaLibrary'));
const Tickets = React.lazy(() => import('./pages/TicketPage'));
const Chat = React.lazy(() => import('./pages/Chat'));
const Logs = React.lazy(() => import('./pages/Logs'));
const ToolLibrary = React.lazy(() => import('./pages/ToolLibrary'));
const MasterControl = React.lazy(() => import('./pages/MasterControl'));
const SidebarManagement = React.lazy(() => import('./pages/SidebarManagement'));

const settingsPages: Record<SettingsTabKey, React.ReactElement> = {
    profile: <ProfileSettings />,
    support: <SupportForm isOpen embedded onClose={() => {}} />,
    'master-control': <MasterControl />,
    api: <ApiOverview />,
    logs: <Logs />,
    'media-library': <MediaLibraryPage />,
    'sidebar-management': <SidebarManagement />,
};

const ProtectedLayout: React.FC = () => {
    return (
        <ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]} validateNavigation={false}>
            <Layout>
                <Suspense fallback={<PageLoader />}>
                    <Outlet />
                </Suspense>
            </Layout>
        </ProtectedRoute>
    );
};

const AppRoutes: React.FC = () => {
    const { user } = useAuth();

    return (
        <Routes>
            <Route path="/login" element={<Login />} />
            
            <Route path="/" element={<ProtectedLayout />}>
                <Route index element={<Navigate to={user?.role === Role.USER ? "/dashboard" : "/tasks"} replace />} />
                
                <Route path="dashboard" element={<ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]}><Dashboard /></ProtectedRoute>} />
                <Route path="tasks/*" element={<ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]} validateNavigation={false}><AllTasks /></ProtectedRoute>} />
                <Route path="admin/users" element={<ProtectedRoute roles={[Role.MANAGER, Role.ADMIN, Role.OWNER]}><Users /></ProtectedRoute>} />
                <Route path="admin/rewards" element={<ProtectedRoute roles={[Role.MANAGER, Role.ADMIN, Role.OWNER]}><Navigate to="/achievements?tab=rewards" replace /></ProtectedRoute>} />
                <Route path="admin/points-table" element={<ProtectedRoute roles={[Role.OWNER]}><Navigate to="/achievements?tab=points" replace /></ProtectedRoute>} />
                <Route path="reports" element={<ProtectedRoute roles={[Role.MANAGER, Role.ADMIN, Role.OWNER]}><Reports /></ProtectedRoute>} />
                <Route path="tool-library" element={<ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]}><ToolLibrary /></ProtectedRoute>} />
                <Route path="settings" element={<Settings />}>
                    <Route index element={<PreserveLocationRedirect to="/settings/profile" />} />
                    {SETTINGS_TABS.map((tab) => (
                        <Route key={tab.key} path={tab.key} element={<ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]}>{settingsPages[tab.key]}</ProtectedRoute>} />
                    ))}
                    <Route path="*" element={<NotFound />} />
                </Route>
                <Route path="achievements" element={<ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]}><Achievements /></ProtectedRoute>} />
                <Route path="levels" element={<ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]}><Navigate to="/achievements?tab=levels" replace /></ProtectedRoute>} />
                <Route path="tickets" element={<ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]}><Tickets /></ProtectedRoute>} />
                <Route path="chat" element={<ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]}><Chat /></ProtectedRoute>} />
                <Route path="chat/:conversationId" element={<ProtectedRoute roles={[Role.USER, Role.MANAGER, Role.ADMIN, Role.OWNER]}><Chat /></ProtectedRoute>} />
                <Route path="template-editor" element={<ProtectedRoute roles={[Role.OWNER]}><Navigate to="/achievements?tab=templates" replace /></ProtectedRoute>} />
                {Object.entries(LEGACY_TASK_ROUTES).map(([from, to]) => (
                    <Route key={from} path={from.slice(1)} element={<PreserveLocationRedirect to={to} />} />
                ))}
                {Object.entries(LEGACY_SETTINGS_ROUTES).map(([from, to]) => (
                    <Route key={from} path={from.slice(1)} element={<PreserveLocationRedirect to={to} />} />
                ))}


            </Route>
            
            <Route path="*" element={<NotFound />} />
        </Routes>
    );
};

const AppContent: React.FC = () => {
  const { theme } = useTheme();
  const backgroundImage = theme === 'colorful' ? `url('https://res.cloudinary.com/dqhcbck76/image/upload/v1770622362/4882066_gjwlts.jpg')` : 'none';
  return (
    <div style={{ backgroundImage, backgroundSize: 'cover', backgroundPosition: 'center', backgroundRepeat: 'no-repeat', minHeight: '100vh' }}>
      <AppRoutes />
    </div>
  );
};

const AppProviders: React.FC = () => {
  return (
      <ThemeProvider>
        <LoadingProvider>
          <AuthProvider>
            <SearchProvider>
              <NavigationProvider><AppContent /></NavigationProvider>
            </SearchProvider>
          </AuthProvider>
        </LoadingProvider>
      </ThemeProvider>
  );
};

// Retain hash URLs and existing routes while enabling supported form blockers,
// including browser Back/Forward navigation.
const router = createHashRouter([{ path: '*', element: <AppProviders /> }]);
const App: React.FC = () => <RouterProvider router={router} />;

export default App;

