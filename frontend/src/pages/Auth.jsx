import React, { useEffect, useState } from 'react';
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
  const { login, loginDemo } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [f, setF] = useState({ email: '', password: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState(null);

  useEffect(() => {
    api.demoInfo().then(setDemo).catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try { await login(f.email, f.password); nav(loc.state?.from || '/', { replace: true }); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  };

  const enterDemo = async (role) => {
    setBusy(true); setErr('');
    try {
      await loginDemo(role);
      nav(role === 'incoming' ? '/portal' : '/', { replace: true });
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap" style={{ alignItems: 'start', paddingTop: 32 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20, width: '100%', maxWidth: 880 }}>
        <div className="card">
          <h1 className="auth-title">TRACE</h1>
          <p className="muted">When people leave, knowledge shouldn&apos;t. Sign in to your workspace.</p>
          <form onSubmit={submit}>
            {err && <div className="alert error">{err}</div>}
            <div className="field"><label htmlFor="email">Email</label><input id="email" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
            <div className="field"><label htmlFor="pw">Password</label><input id="pw" type="password" required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
            <button className="btn primary" disabled={busy}>{busy ? 'Signing in' : 'Sign in'}</button>
            <p style={{ marginTop: 12, marginBottom: 0 }} className="muted">
              <Link to="/forgot-password">Forgot password?</Link> &middot; <Link to="/signup" state={loc.state}>Create account</Link>
            </p>
          </form>
        </div>

        <div className="card" style={{ borderLeft: '3px solid var(--accent)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h2 style={{ margin: 0, fontSize: 18 }}>Try the demo</h2>
            <span className="badge warn">SYNTHETIC</span>
          </div>
          <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
            Explore the pre-loaded Atlas Workspace across all three roles. No developer setup required.
          </p>
          <div style={{ display: 'grid', gap: 8, marginBottom: 14 }}>
            {(demo?.accounts || [
              { role: 'admin', label: 'Team Lead / Admin (Alex)', email: 'alex.lead@demo.example.com', summary: 'Full access + Handover Center + restricted items.' },
              { role: 'incoming', label: 'Incoming Member (Priya)', email: 'priya.incoming@demo.example.com', summary: 'Incoming Portal + plan; restricted items hidden.' },
              { role: 'departing', label: 'Departing Member (Rahul)', email: 'rahul.departing@demo.example.com', summary: 'Own contributions & exit interview only.' },
            ]).map((acc) => (
              <div key={acc.role} style={{ border: '1px solid var(--border)', borderRadius: 4, padding: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <div>
                    <strong style={{ fontSize: 13 }}>{acc.label}</strong>
                    <div className="mono muted" style={{ fontSize: 11 }}>{acc.email} / DemoTrace2026!</div>
                  </div>
                  <button className="btn sm primary" type="button" disabled={busy} onClick={() => enterDemo(acc.role)}>
                    Enter as {acc.role}
                  </button>
                </div>
                <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{acc.summary}</div>
              </div>
            ))}
          </div>
          <div>
            <strong style={{ fontSize: 13 }}>How to try this</strong>
            <ol style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12, lineHeight: 1.5 }} className="muted">
              {(demo?.steps || [
                'Sign in as Team Lead (Alex) to inspect Continuity Overview, Handover Center, and Contradiction Radar.',
                'Open Evidence Ledger to verify source excerpts and test Preview as: Incoming.',
                'Switch to Incoming Member (Priya) to see the Incoming Portal with zero restricted data.',
                'Switch to Departing Member (Rahul) to see Exit Interview and own contributions.',
                'Or click Create account to test with your own non-Atlas project files.',
              ]).map((st, idx) => (
                <li key={idx}>{st.replace(/^\d+\.\s*/, '')}</li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </div>
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
