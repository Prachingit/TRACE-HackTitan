import React from 'react';
import { Navigate, NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  FolderKanban,
  Users,
  Plug,
  LayoutDashboard,
  LogOut,
  BookOpen,
  FileCheck2,
  AlertTriangle,
  Activity,
  MessageSquareText,
  ClipboardCheck,
} from 'lucide-react';
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

const STATUS_CLASS = {
  parsed: 'ok',
  done: 'ok',
  completed: 'ok',
  resolved: 'ok',
  failed: 'bad',
  open: 'bad',
  queued: 'warn',
  pending: 'warn',
  parsing: 'info',
  running: 'info',
  registered: '',
};

export function StatusBadge({ status }) {
  return (
    <span className={`badge ${STATUS_CLASS[status] || ''}`}>
      <span className="badge-dot" />
      {status}
    </span>
  );
}

const VERIFICATION_META = {
  verified: { cls: 'ok', label: 'Verified' },
  inferred: { cls: 'info', label: 'Inferred' },
  conflicting: { cls: 'bad', label: 'Conflicting' },
  missing: { cls: 'warn', label: 'Missing' },
};

export function VerificationBadge({ status }) {
  const m = VERIFICATION_META[status] || { cls: '', label: status || 'Unknown' };
  return (
    <span className={`badge ${m.cls}`}>
      <span className="badge-dot" />
      {m.label}
    </span>
  );
}

const ORIGIN_META = {
  'human-reviewed': { cls: 'ok', label: 'Human-reviewed' },
  'human-authored': { cls: 'ok', label: 'Human-authored' },
  'ai-extracted': { cls: 'info', label: 'AI-extracted' },
  'rule-extracted': { cls: '', label: 'Rule-extracted' },
};

export function OriginBadge({ origin }) {
  const m = ORIGIN_META[origin] || { cls: '', label: origin || 'Rule-extracted' };
  return (
    <span className={`badge ${m.cls}`}>
      <span className="badge-dot" />
      {m.label}
    </span>
  );
}

export function ProjectSubnav({ projectId }) {
  if (!projectId) return null;
  return (
    <nav className="subnav" aria-label="Project sections">
      <NavLink to={`/projects/${projectId}`} end>Sources</NavLink>
      <NavLink to={`/projects/${projectId}/reconstruct`}>Reconstruct</NavLink>
      <NavLink to={`/projects/${projectId}/activity`}>Activity timeline</NavLink>
      <NavLink to={`/projects/${projectId}/knowledge`}>Knowledge base</NavLink>
      <NavLink to={`/projects/${projectId}/ledger`}>Evidence ledger</NavLink>
      <NavLink to={`/projects/${projectId}/contradictions`}>Contradiction radar</NavLink>
      <NavLink to={`/projects/${projectId}/interview`}>Exit interview</NavLink>
      <NavLink to={`/projects/${projectId}/review`}>Review workbench</NavLink>
    </nav>
  );
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
          <NavLink to="/activity"><Activity size={16} strokeWidth={1.5} />Activity</NavLink>
          <NavLink to="/knowledge-base"><BookOpen size={16} strokeWidth={1.5} />Knowledge base</NavLink>
          <NavLink to="/evidence"><FileCheck2 size={16} strokeWidth={1.5} />Evidence ledger</NavLink>
          <NavLink to="/contradictions"><AlertTriangle size={16} strokeWidth={1.5} />Contradictions</NavLink>
          <NavLink to="/interview"><MessageSquareText size={16} strokeWidth={1.5} />Exit interview</NavLink>
          <NavLink to="/review"><ClipboardCheck size={16} strokeWidth={1.5} />Review workbench</NavLink>
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
