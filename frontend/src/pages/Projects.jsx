import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Upload, Trash2, RefreshCw } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import api from '../api/client';
import { EmptyState, Loading, StatusBadge } from '../components/ui';

const fmt = (d) => (d ? new Date(d).toLocaleString() : '-');

export function ProjectList() {
  const { isAdmin } = useAuth();
  const [projects, setProjects] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => { api.projects().then(setProjects).catch((x) => setErr(x.message)); }, []);

  return (
    <>
      <div className="page-head">
        <div><h1>Projects</h1><p className="muted">Projects in your workspace.</p></div>
        {isAdmin && <Link className="btn primary" to="/projects/new">New project</Link>}
      </div>
      {err && <div className="alert error">{err}</div>}
      {!projects ? <Loading /> : projects.length === 0 ? (
        <EmptyState title="No projects yet">{isAdmin ? 'Create a project, then add sources to it.' : 'An admin needs to create a project.'}</EmptyState>
      ) : (
        <table>
          <thead><tr><th>Name</th><th>Category</th><th>Team size</th><th>Technologies</th><th>Created</th></tr></thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td><Link to={`/projects/${p.id}`}>{p.name}</Link> {p.is_synthetic && <span className="badge warn">sample data</span>}</td>
                <td>{p.category || '-'}</td><td>{p.team_size}</td><td>{p.technologies || '-'}</td><td>{fmt(p.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

export function CreateProject() {
  const { workspace } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ name: '', description: '', category: '', team_size: 1, technologies: '', start_date: '' });
  const [err, setErr] = useState('');
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault(); setErr('');
    try {
      const body = { ...f, workspace_id: workspace.id, team_size: Number(f.team_size) || 1, start_date: f.start_date ? new Date(f.start_date).toISOString() : null };
      const p = await api.createProject(body);
      nav(`/projects/${p.id}`);
    } catch (x) { setErr(x.message); }
  };

  return (
    <>
      <h1>New project</h1>
      <form className="card" style={{ maxWidth: 560, marginTop: 16 }} onSubmit={submit}>
        {err && <div className="alert error">{err}</div>}
        <div className="field"><label htmlFor="n">Name</label><input id="n" required value={f.name} onChange={set('name')} /></div>
        <div className="field"><label htmlFor="d">Description</label><textarea id="d" rows={3} value={f.description} onChange={set('description')} /></div>
        <div className="row">
          <div className="field"><label htmlFor="c">Category</label><input id="c" value={f.category} onChange={set('category')} /></div>
          <div className="field"><label htmlFor="t">Team size</label><input id="t" type="number" min={1} value={f.team_size} onChange={set('team_size')} /></div>
        </div>
        <div className="row">
          <div className="field"><label htmlFor="te">Technologies</label><input id="te" value={f.technologies} onChange={set('technologies')} /></div>
          <div className="field"><label htmlFor="s">Start date</label><input id="s" type="date" value={f.start_date} onChange={set('start_date')} /></div>
        </div>
        <button className="btn primary">Create project</button>
      </form>
    </>
  );
}

function UploadTab({ pid, isAdmin, onDone }) {
  const [clearance, setClearance] = useState('team');
  const [over, setOver] = useState(false);
  const [msgs, setMsgs] = useState([]);
  const input = useRef();

  const send = async (files) => {
    const out = [];
    for (const file of files) {
      try { await api.upload(pid, file, clearance); out.push({ ok: true, text: `${file.name}: queued for parsing.` }); }
      catch (x) { out.push({ ok: false, text: `${file.name}: ${x.message}` }); }
    }
    setMsgs(out); onDone();
  };

  return (
    <div className="card">
      <div className="field" style={{ maxWidth: 260 }}>
        <label htmlFor="cl">Clearance level</label>
        <select id="cl" value={clearance} onChange={(e) => setClearance(e.target.value)}>
          <option value="public">Public</option><option value="team">Team</option>
          {isAdmin && <option value="restricted">Restricted (admin only)</option>}
        </select>
      </div>
      <div className={`dropzone ${over ? 'over' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); send([...e.dataTransfer.files]); }}>
        <Upload size={20} strokeWidth={1.5} />
        <p>Drag files here, or choose files. PDF, DOCX, TXT, MD, CSV, JSON. Up to 15 MB each.</p>
        <button className="btn" onClick={() => input.current.click()} type="button">Choose files</button>
        <input ref={input} type="file" multiple hidden accept=".pdf,.docx,.txt,.md,.csv,.json" onChange={(e) => { send([...e.target.files]); e.target.value = ''; }} />
      </div>
      {msgs.map((m, i) => <div key={i} className={`alert ${m.ok ? 'info' : 'error'}`} style={{ marginTop: 8, marginBottom: 0 }}>{m.text}</div>)}
    </div>
  );
}

function GithubTab({ pid, isAdmin, onDone }) {
  const [url, setUrl] = useState('');
  const [clearance, setClearance] = useState('team');
  const [msg, setMsg] = useState(null);
  const submit = async (e) => {
    e.preventDefault(); setMsg(null);
    try { await api.importGithub(pid, { repo_url: url, clearance_level: clearance }); setMsg({ ok: true, text: 'Import started. Progress shows in the table below.' }); setUrl(''); onDone(); }
    catch (x) { setMsg({ ok: false, text: x.message }); }
  };
  return (
    <form className="card" onSubmit={submit}>
      <p className="muted">Imports commits, pull requests and issues from a public repository.</p>
      <div className="row">
        <div className="field" style={{ flex: 3 }}><label htmlFor="u">Repository URL</label><input id="u" required placeholder="https://github.com/owner/repo" value={url} onChange={(e) => setUrl(e.target.value)} /></div>
        <div className="field"><label htmlFor="g">Clearance</label>
          <select id="g" value={clearance} onChange={(e) => setClearance(e.target.value)}>
            <option value="public">Public</option><option value="team">Team</option>{isAdmin && <option value="restricted">Restricted</option>}
          </select></div>
      </div>
      <button className="btn primary">Import repository</button>
      {msg && <div className={`alert ${msg.ok ? 'info' : 'error'}`} style={{ marginTop: 8, marginBottom: 0 }}>{msg.text}</div>}
    </form>
  );
}

function ManualTab({ pid, isAdmin, onDone }) {
  const [f, setF] = useState({ title: '', content: '', clearance_level: 'team' });
  const [msg, setMsg] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault(); setMsg(null);
    try { await api.addManual(pid, f); setMsg({ ok: true, text: 'Entry added.' }); setF({ ...f, title: '', content: '' }); onDone(); }
    catch (x) { setMsg({ ok: false, text: x.message }); }
  };
  return (
    <form className="card" onSubmit={submit}>
      <div className="field"><label htmlFor="mt">Title</label><input id="mt" required value={f.title} onChange={set('title')} /></div>
      <div className="field"><label htmlFor="mc">Content</label><textarea id="mc" rows={5} required value={f.content} onChange={set('content')} /></div>
      <div className="field" style={{ maxWidth: 260 }}><label htmlFor="ml">Clearance</label>
        <select id="ml" value={f.clearance_level} onChange={set('clearance_level')}>
          <option value="public">Public</option><option value="team">Team</option>{isAdmin && <option value="restricted">Restricted</option>}
        </select></div>
      <button className="btn primary">Add entry</button>
      {msg && <div className={`alert ${msg.ok ? 'info' : 'error'}`} style={{ marginTop: 8, marginBottom: 0 }}>{msg.text}</div>}
    </form>
  );
}

export function ProjectSources() {
  const { id } = useParams();
  const { isAdmin } = useAuth();
  const nav = useNavigate();
  const [project, setProject] = useState(null);
  const [sources, setSources] = useState(null);
  const [tab, setTab] = useState('upload');
  const [err, setErr] = useState('');

  const load = () => api.sources(id).then(setSources).catch((x) => setErr(x.message));
  useEffect(() => { api.project(id).then(setProject).catch((x) => setErr(x.message)); load(); }, [id]);

  // Poll while anything is in flight
  const active = sources?.some((s) => s.status === 'queued' || s.status === 'parsing');
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [active, id]);

  const act = async (fn) => { try { await fn(); await load(); } catch (x) { setErr(x.message); } };
  const del = (s) => window.confirm(`Delete ${s.filename} and its parsed content?`) && act(() => api.deleteSource(id, s.id));
  const sample = () => act(() => api.loadSample(id));
  const delProject = async () => {
    if (!window.confirm('Delete this project and all of its sources? This cannot be undone.')) return;
    try { await api.deleteProject(id); nav('/projects'); } catch (x) { setErr(x.message); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{project?.name || 'Project'}</h1>
          <p className="muted">{project?.description}</p>
          {project?.is_synthetic && <span className="badge warn">Contains synthetic sample data</span>}
        </div>
        {isAdmin && <button className="btn danger" onClick={delProject}><Trash2 size={14} strokeWidth={1.5} />Delete project</button>}
      </div>
      {err && <div className="alert error">{err}</div>}

      <h2>Add data</h2>
      <div className="tabs">
        {[['upload', 'Upload files'], ['github', 'GitHub'], ['manual', 'Manual entry']].map(([k, l]) => (
          <button key={k} className={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {tab === 'upload' && <UploadTab pid={id} isAdmin={isAdmin} onDone={load} />}
      {tab === 'github' && <GithubTab pid={id} isAdmin={isAdmin} onDone={load} />}
      {tab === 'manual' && <ManualTab pid={id} isAdmin={isAdmin} onDone={load} />}

      <div className="page-head" style={{ marginTop: 24, marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Sources</h2>
        {isAdmin && <button className="btn" onClick={sample}>Load sample project data</button>}
      </div>
      {!sources ? <Loading /> : sources.length === 0 ? (
        <EmptyState title="No sources yet">Upload files, import a GitHub repository, or add a manual entry.</EmptyState>
      ) : (
        <table>
          <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Clearance</th><th>Status</th><th>Chunks</th><th>Added</th><th /></tr></thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id}>
                <td className="mono">{s.id}</td>
                <td><Link to={`/projects/${id}/sources/${s.id}`}>{s.filename}</Link>
                  {s.status === 'failed' && <div className="muted" style={{ color: 'var(--danger)' }}>{s.error_message}</div>}</td>
                <td>{s.type}</td>
                <td><span className={`badge ${s.clearance_level === 'restricted' ? 'bad' : ''}`}>{s.clearance_level}</span></td>
                <td><StatusBadge status={s.status} /></td>
                <td>{s.chunk_count}</td>
                <td>{fmt(s.uploaded_at)}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {s.status === 'failed' && <button className="btn sm" onClick={() => act(() => api.retrySource(id, s.id))}><RefreshCw size={12} strokeWidth={1.5} />Retry</button>}{' '}
                  {isAdmin && <button className="btn sm danger" onClick={() => del(s)}>Delete</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

export function SourceDetail() {
  const { id, sid } = useParams();
  const [source, setSource] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [more, setMore] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    api.source(id, sid).then(setSource).catch((x) => setErr(x.message));
    api.chunks(id, sid).then((c) => { setChunks(c); setMore(c.length === 50); }).catch((x) => setErr(x.message));
  }, [id, sid]);

  const loadMore = async () => { const c = await api.chunks(id, sid, chunks.length); setChunks([...chunks, ...c]); setMore(c.length === 50); };

  if (err) return <div className="alert error">{err}</div>;
  if (!source) return <Loading />;
  return (
    <>
      <p><Link to={`/projects/${id}`}>Back to project</Link></p>
      <h1>{source.filename}</h1>
      <table style={{ maxWidth: 560, margin: '16px 0' }}>
        <tbody>
          <tr><th>ID</th><td className="mono">{source.id}</td></tr>
          <tr><th>Type</th><td>{source.type}</td></tr>
          <tr><th>Clearance</th><td>{source.clearance_level}</td></tr>
          <tr><th>Status</th><td><StatusBadge status={source.status} /></td></tr>
          <tr><th>Content hash</th><td className="mono" style={{ wordBreak: 'break-all' }}>{source.content_hash || '-'}</td></tr>
          <tr><th>Added</th><td>{fmt(source.uploaded_at)}</td></tr>
        </tbody>
      </table>
      {source.error_message && <div className="alert error">{source.error_message}</div>}
      <h2>Chunks ({source.chunk_count})</h2>
      {chunks.length === 0 ? <EmptyState title="No chunks">This source has no parsed content.</EmptyState> : (
        <table>
          <thead><tr><th>#</th><th>Locator</th><th>Author</th><th>Text</th></tr></thead>
          <tbody>{chunks.map((c) => (
            <tr key={c.id}><td>{c.ordinal}</td><td className="mono">{c.locator || '-'}</td><td>{c.author || '-'}</td>
              <td style={{ whiteSpace: 'pre-wrap' }}>{c.text.length > 400 ? `${c.text.slice(0, 400)}...` : c.text}</td></tr>
          ))}</tbody>
        </table>
      )}
      {more && <button className="btn" style={{ marginTop: 12 }} onClick={loadMore}>Load more</button>}
    </>
  );
}
