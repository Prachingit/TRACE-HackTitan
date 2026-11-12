import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import api from '../api/client';

function Shell({ title, children }) {
  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <h1 className="auth-title">TRACE</h1>
        <p className="muted">{title}</p>
        <div className="card">{children}</div>
      </div>
    </div>
  );
}

export function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [f, setF] = useState({ email: '', password: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try { await login(f.email, f.password); nav(loc.state?.from || '/', { replace: true }); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  };

  return (
    <Shell title="Sign in to your workspace">
      <form onSubmit={submit}>
        {err && <div className="alert error">{err}</div>}
        <div className="field"><label htmlFor="email">Email</label><input id="email" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
        <div className="field"><label htmlFor="pw">Password</label><input id="pw" type="password" required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
        <button className="btn primary" disabled={busy}>{busy ? 'Signing in' : 'Sign in'}</button>
        <p style={{ marginTop: 12, marginBottom: 0 }} className="muted">
          <Link to="/forgot-password">Forgot password?</Link> &middot; <Link to="/signup" state={loc.state}>Create account</Link>
        </p>
      </form>
    </Shell>
  );
}

export function Signup() {
  const { signup } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [f, setF] = useState({ name: '', email: '', password: '', confirm_password: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if (f.password !== f.confirm_password) { setErr('Passwords do not match.'); return; }
    setBusy(true); setErr('');
    try { await signup(f); nav(loc.state?.from || '/', { replace: true }); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  };

  return (
    <Shell title="Create your account">
      <form onSubmit={submit}>
        {err && <div className="alert error">{err}</div>}
        <div className="field"><label htmlFor="name">Name</label><input id="name" required value={f.name} onChange={set('name')} /></div>
        <div className="field"><label htmlFor="email">Email</label><input id="email" type="email" required value={f.email} onChange={set('email')} /></div>
        <div className="field"><label htmlFor="pw">Password (10 characters minimum)</label><input id="pw" type="password" required minLength={10} value={f.password} onChange={set('password')} /></div>
        <div className="field"><label htmlFor="pw2">Confirm password</label><input id="pw2" type="password" required value={f.confirm_password} onChange={set('confirm_password')} /></div>
        <button className="btn primary" disabled={busy}>{busy ? 'Creating account' : 'Create account'}</button>
        <p style={{ marginTop: 12, marginBottom: 0 }} className="muted">Already registered? <Link to="/login">Sign in</Link></p>
      </form>
    </Shell>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault(); setErr(''); setMsg('');
    try { setMsg((await api.forgot(email)).message); } catch (x) { setErr(x.message); }
  };
  return (
    <Shell title="Reset your password">
      <form onSubmit={submit}>
        {err && <div className="alert error">{err}</div>}
        {msg && <div className="alert info">{msg}</div>}
        <div className="field"><label htmlFor="email">Email</label><input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <button className="btn primary">Request reset</button>
        <p style={{ marginTop: 12, marginBottom: 0 }}><Link to="/login">Back to sign in</Link></p>
      </form>
    </Shell>
  );
}
