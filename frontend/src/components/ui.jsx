import React from 'react';
import { Navigate, NavLink, Outlet, useLocation } from 'react-router-dom';
import { FolderKanban, Users, Plug, LayoutDashboard, LogOut } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

export function Loading({ label = 'Loading' }) {
  return <p className="muted">{label}...</p>;
}

export function EmptyState({ title, children }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children && <p style={{ marginTop: 8, marginBottom: 0 }}>{children}</p>}
    </div>
  );
}

const STATUS_CLASS = { parsed: 'ok', failed: 'bad', queued: 'warn', parsing: 'info', registered: '' };
export function StatusBadge({ status }) {
  return <span className={`badge ${STATUS_CLASS[status] || ''}`}>{status}</span>;
}

export function ProtectedRoute() {
  const { user, workspace, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="auth-wrap"><Loading /></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (!workspace && loc.pathname !== '/onboarding' && !loc.pathname.startsWith('/invite/')) {
    return <Navigate to="/onboarding" replace />;
  }
  return <Outlet />;
}

export function Layout() {
  const { user, workspace, logout } = useAuth();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">TRACE</div>
        <nav className="nav">
          <NavLink to="/" end><LayoutDashboard size={16} strokeWidth={1.5} />Overview</NavLink>
          <NavLink to="/projects"><FolderKanban size={16} strokeWidth={1.5} />Projects</NavLink>
          <NavLink to="/team"><Users size={16} strokeWidth={1.5} />Team</NavLink>
          <NavLink to="/integrations"><Plug size={16} strokeWidth={1.5} />Integrations</NavLink>
        </nav>
        <div className="sidebar-foot">
          <div>{user?.name}</div>
          <div className="muted">{workspace?.name} ({workspace?.role})</div>
          <button className="btn sm" style={{ marginTop: 8 }} onClick={logout}><LogOut size={14} strokeWidth={1.5} />Sign out</button>
        </div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  );
}
