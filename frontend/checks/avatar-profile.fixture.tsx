// Browser-only component fixture; Vite's production entry never imports this file.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider, SearchProvider, ThemeProvider, useAuth } from '../hooks/useAuth';
import Avatar from '../components/Avatar';
import EmployeeIdentityCard from '../components/EmployeeIdentityCard';
import ProfileSettings from '../pages/ProfileSettings';
import Users from '../pages/Users';

function ProfileFixture() {
  const { user } = useAuth();
  return <main className="mx-auto max-w-6xl p-4">
    <header data-testid="identity-menu" className="mb-4 flex items-center gap-3"><Avatar user={user} />{user?.name}</header>
    {new URLSearchParams(location.search).has('directory') ? <Users /> : <>
      {user && <EmployeeIdentityCard user={user} />}<ProfileSettings />
    </>}
  </main>;
}

createRoot(document.getElementById('root')!).render(<BrowserRouter><ThemeProvider><SearchProvider><AuthProvider><ProfileFixture /></AuthProvider></SearchProvider></ThemeProvider></BrowserRouter>);
