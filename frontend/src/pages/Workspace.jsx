import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import api from '../api/client';

export function Onboarding() {
  const { refresh } = useAuth();
  const nav = useNavigate();
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [err, setErr] = useState('');

  const create = async (e) => {
    e.preventDefault(); setErr('');
    try { await api.createWorkspace(name); await refresh(); nav('/projects'); } catch (x) { setErr(x.message); }
  };
  const join = async (e) => {
    e.preventDefault(); setErr('');
    try { await api.joinWorkspace(code.trim()); await refresh(); nav('/'); } catch (x) { setErr(x.message); }
  };

  return (
    <div className="auth-wrap">
      <div style={{ width: '100%', maxWidth: 720 }}>
        <h1>Set up your workspace</h1>
        <p className="muted">Create a workspace for your team, or join one with an invite code.</p>
        {err && <div className="alert error">{err}</div>}
        <div className="row">
          <form className="card" onSubmit={create}>
            <h2>Create a workspace</h2>
            <div className="field"><label htmlFor="ws">Workspace name</label><input id="ws" required value={name} onChange={(e) => setName(e.target.value)} /></div>
            <button className="btn primary">Create workspace</button>
          </form>
          <form className="card" onSubmit={join}>
            <h2>Join with an invite</h2>
            <div className="field"><label htmlFor="code">Invite code or link token</label><input id="code" required className="mono" value={code} onChange={(e) => setCode(e.target.value)} /></div>
            <button className="btn">Join workspace</button>
          </form>
        </div>
      </div>
    </div>
  );
}

export function InviteAccept() {
  const { token } = useParams();
  const { refresh } = useAuth();
  const nav = useNavigate();
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState('');

  useEffect(() => { api.invitePreview(token).then(setInfo).catch((x) => setErr(x.message)); }, [token]);

  const accept = async () => {
    try { await api.joinWorkspace(token); await refresh(); nav('/'); } catch (x) { setErr(x.message); }
  };

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <h1>Workspace invite</h1>
        {err && <div className="alert error">{err}</div>}
        {info && (
          <div className="card">
            <p>You have been invited to <strong>{info.workspace_name}</strong> as <strong>{info.role}</strong>.</p>
            <button className="btn primary" onClick={accept}>Accept invite</button>
          </div>
        )}
      </div>
    </div>
  );
}
