import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import api from '../api/client';
import { EmptyState, Loading } from '../components/ui';

const ROLES = ['admin', 'team_member', 'incoming', 'departing'];

export function TeamPage() {
  const { workspace, user, isAdmin } = useAuth();
  const [members, setMembers] = useState(null);
  const [invites, setInvites] = useState([]);
  const [role, setRole] = useState('team_member');
  const [err, setErr] = useState('');

  const load = async () => {
    try {
      setMembers(await api.members(workspace.id));
      if (isAdmin) setInvites(await api.invites(workspace.id));
    } catch (x) { setErr(x.message); }
  };
  useEffect(() => { load(); }, [workspace.id]);

  const act = async (fn) => { setErr(''); try { await fn(); await load(); } catch (x) { setErr(x.message); } };
  const link = (t) => `${window.location.origin}/invite/${t}`;
  const live = invites.filter((i) => !i.is_used && !i.is_revoked && new Date(i.expires_at) > new Date());

  return (
    <>
      <div className="page-head"><div><h1>Team</h1><p className="muted">{workspace.name}</p></div></div>
      {err && <div className="alert error">{err}</div>}
      {!members ? <Loading /> : (
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Role</th><th /></tr></thead>
          <tbody>{members.map((m) => (
            <tr key={m.user_id}>
              <td>{m.name}</td><td>{m.email}</td>
              <td>{isAdmin ? (
                <select value={m.role} onChange={(e) => act(() => api.setRole(workspace.id, m.user_id, e.target.value))} style={{ width: 'auto' }}>
                  {ROLES.map((r) => <option key={r}>{r}</option>)}
                </select>) : m.role}</td>
              <td>{isAdmin && m.user_id !== user.id && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {m.role === 'departing' ? (
                    <Link className="btn sm primary" to="/handovers">Start handover</Link>
                  ) : (
                    <button className="btn sm" onClick={() => act(() => api.setRole(workspace.id, m.user_id, 'departing'))}>Mark departing</button>
                  )}
                  <button className="btn sm danger" onClick={() => window.confirm(`Revoke access for ${m.name}?`) && act(() => api.removeMember(workspace.id, m.user_id))}>Revoke access</button>
                </div>
              )}</td>
            </tr>))}
          </tbody>
        </table>
      )}

      {isAdmin && (
        <>
          <h2 style={{ marginTop: 32 }}>Invites</h2>
          <div className="card row" style={{ alignItems: 'flex-end' }}>
            <div className="field" style={{ marginBottom: 0 }}><label htmlFor="r">Role</label>
              <select id="r" value={role} onChange={(e) => setRole(e.target.value)}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></div>
            <div><button className="btn primary" onClick={() => act(() => api.createInvite(workspace.id, role))}>Create invite link</button></div>
          </div>
          {live.length === 0 ? <EmptyState title="No active invites">Invites are single-use and expire after 48 hours.</EmptyState> : (
            <table>
              <thead><tr><th>Role</th><th>Link</th><th>Expires</th><th /></tr></thead>
              <tbody>{live.map((i) => (
                <tr key={i.id}><td>{i.role}</td><td className="mono" style={{ wordBreak: 'break-all' }}>{link(i.token)}</td>
                  <td>{new Date(i.expires_at).toLocaleString()}</td>
                  <td><button className="btn sm danger" onClick={() => act(() => api.revokeInvite(workspace.id, i.id))}>Revoke</button></td></tr>
              ))}</tbody>
            </table>
          )}
        </>
      )}
    </>
  );
}

export function IntegrationsPage() {
  const rows = [
    ['GitHub', 'Import commits, pull requests and issues from public repositories.', 'Available'],
    ['Slack', 'Import channel history.', 'Planned'],
    ['Jira', 'Import issues and sprints.', 'Planned'],
    ['Google Drive', 'Import documents.', 'Planned'],
  ];
  return (
    <>
      <h1>Integrations</h1>
      <p className="muted">GitHub import is available from any project's sources page. Other integrations are not built yet.</p>
      <table style={{ marginTop: 16 }}>
        <thead><tr><th>Integration</th><th>Description</th><th>Status</th></tr></thead>
        <tbody>{rows.map(([n, d, s]) => (
          <tr key={n} style={s === 'Planned' ? { color: 'var(--ink-2)' } : {}}><td>{n}</td><td>{d}</td>
            <td><span className={`badge ${s === 'Available' ? 'ok' : ''}`}>{s}</span></td></tr>))}
        </tbody>
      </table>
    </>
  );
}
