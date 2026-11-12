import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Play, RefreshCw } from 'lucide-react';
import api from '../api/client';
import {
  EmptyState,
  Loading,
  OriginBadge,
  ProjectSubnav,
  StatusBadge,
  VerificationBadge,
} from '../components/ui';

const fmtDate = (d) => (d ? new Date(d).toLocaleString() : '-');

export function useActiveProjectId() {
  const { id } = useParams();
  const [projects, setProjects] = useState(null);
  const [selectedId, setSelectedId] = useState(id || '');

  useEffect(() => {
    if (id) setSelectedId(id);
  }, [id]);

  useEffect(() => {
    api.projects().then((list) => {
      setProjects(list);
      if (!id && list.length > 0) setSelectedId(list[0].id);
    }).catch(() => setProjects([]));
  }, [id]);

  return { projectId: id || selectedId, projects, setSelectedId, hasRouteId: Boolean(id) };
}

export function ProjectHeaderBar({ title, subtitle, projectId, projects, setSelectedId, hasRouteId, actions }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          {subtitle && <p className="muted" style={{ marginBottom: 0 }}>{subtitle}</p>}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {!hasRouteId && projects && projects.length > 1 && (
            <select
              aria-label="Select project"
              value={projectId}
              onChange={(e) => setSelectedId(e.target.value)}
              style={{ width: 'auto' }}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
          {actions}
        </div>
      </div>
      {projectId && <ProjectSubnav projectId={projectId} />}
    </>
  );
}

// ── 1. Reconstructing Project Knowledge Progress Page ────────────────────────

export function ReconstructPage() {
  const { projectId, projects, setSelectedId, hasRouteId } = useActiveProjectId();
  const [run, setRun] = useState(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const loadRun = useCallback(() => {
    if (!projectId) return;
    api.latestRun(projectId).then(setRun).catch((x) => setErr(x.message));
  }, [projectId]);

  useEffect(() => { loadRun(); }, [loadRun]);

  useEffect(() => {
    if (!run || run.status !== 'running') return undefined;
    const t = setInterval(loadRun, 1500);
    return () => clearInterval(t);
  }, [run, loadRun]);

  const startAnalysis = async () => {
    if (!projectId) return;
    setBusy(true);
    setErr('');
    try {
      const started = await api.analyze(projectId);
      setRun(started);
      await loadRun();
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  if (projects && projects.length === 0) {
    return <EmptyState title="No projects yet"><Link to="/projects">Create a project</Link> first.</EmptyState>;
  }

  return (
    <>
      <ProjectHeaderBar
        title="Reconstructing project knowledge"
        subtitle="Real-time stage progress from source normalisation through claim extraction and correlation."
        projectId={projectId}
        projects={projects}
        setSelectedId={setSelectedId}
        hasRouteId={hasRouteId}
        actions={
          <button className="btn primary" disabled={busy || !projectId} onClick={startAnalysis}>
            <Play size={14} strokeWidth={1.5} />
            {run ? 'Re-run analysis' : 'Analyze project'}
          </button>
        }
      />
      {err && <div className="alert error">{err}</div>}
      {run === undefined ? (
        <Loading />
      ) : run === null ? (
        <EmptyState title="Not analysed yet">
          Click &ldquo;Analyze project&rdquo; to read parsed sources, extract evidence-backed claims, correlate modules, and validate citations.
        </EmptyState>
      ) : (
        <>
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
              <div>
                <strong>Run <span className="mono">{run.id.slice(0, 10)}</span></strong>{' '}
                <StatusBadge status={run.status} />
                <div className="muted" style={{ marginTop: 4 }}>
                  Started {fmtDate(run.started_at)}
                  {run.finished_at ? ` · Finished ${fmtDate(run.finished_at)}` : ''}
                  {' · '}Extractor mode: {run.llm_enabled ? 'LLM + rule fallback' : 'Deterministic rules'}
                </div>
              </div>
              {run.status === 'completed' && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <Link className="btn" to={`/projects/${projectId}/knowledge`}>Open knowledge base</Link>
                  <Link className="btn" to={`/projects/${projectId}/ledger`}>Open evidence ledger</Link>
                </div>
              )}
            </div>
            {run.error_message && <div className="alert error" style={{ marginTop: 12 }}>{run.error_message}</div>}
            {run.summary?.llm_fallbacks?.length > 0 && (
              <div className="alert info" style={{ marginTop: 12 }}>
                <strong>Deterministic fallback recorded:</strong>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                  {run.summary.llm_fallbacks.map((fb, idx) => <li key={idx}>{fb}</li>)}
                </ul>
              </div>
            )}
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Stage</th>
                  <th>Status</th>
                  <th>Count</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {run.stages.map((s) => (
                  <tr key={s.key}>
                    <td className="mono">{s.ordinal}</td>
                    <td><strong>{s.label}</strong></td>
                    <td><StatusBadge status={s.status} /></td>
                    <td className="mono">{s.count !== null && s.count !== undefined ? s.count : '-'}</td>
                    <td className="muted">{s.detail || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

// ── 2. Project Activity Timeline Page ────────────────────────────────────────

export function ActivityPage() {
  const { projectId, projects, setSelectedId, hasRouteId } = useActiveProjectId();
  const [events, setEvents] = useState(null);
  const [moduleFilter, setModuleFilter] = useState('');
  const [err, setErr] = useState('');

  useEffect(() => {
    if (!projectId) return;
    setEvents(null);
    api.timeline(projectId).then(setEvents).catch((x) => setErr(x.message));
  }, [projectId]);

  if (projects && projects.length === 0) {
    return <EmptyState title="No projects yet"><Link to="/projects">Create a project</Link> first.</EmptyState>;
  }

  const modules = events ? [...new Set(events.map((e) => e.module).filter(Boolean))].sort() : [];
  const filtered = events ? events.filter((e) => !moduleFilter || e.module === moduleFilter) : [];

  return (
    <>
      <ProjectHeaderBar
        title="Project activity timeline"
        subtitle="Chronological events reconstructed strictly from source timestamps and locators."
        projectId={projectId}
        projects={projects}
        setSelectedId={setSelectedId}
        hasRouteId={hasRouteId}
        actions={
          modules.length > 0 && (
            <select
              aria-label="Filter by module"
              value={moduleFilter}
              onChange={(e) => setModuleFilter(e.target.value)}
              style={{ width: 'auto' }}
            >
              <option value="">All modules</option>
              {modules.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          )
        }
      />
      {err && <div className="alert error">{err}</div>}
      {!events ? (
        <Loading />
      ) : filtered.length === 0 ? (
        <EmptyState title="No dated activity events">
          Upload dated sources (commits, chat exports, tasks CSV, or dated meeting notes) to populate the chronological timeline.
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Module</th>
                <th>Author</th>
                <th>Event summary</th>
                <th>Source</th>
                <th>Locator</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((ev) => (
                <tr key={ev.chunk_id}>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {fmtDate(ev.timestamp)}
                    {ev.timestamp_inferred && <span className="muted"> (section date)</span>}
                  </td>
                  <td><span className="badge">{ev.module}</span></td>
                  <td>{ev.author || '-'}</td>
                  <td>{ev.summary}</td>
                  <td>
                    <Link to={`/projects/${projectId}/sources/${ev.source_id}`}>
                      <span className="mono">{ev.source_id}</span> ({ev.source_filename})
                    </Link>
                  </td>
                  <td className="mono">{ev.locator || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ── 3. Knowledge Base Page ───────────────────────────────────────────────────

const KB_SECTIONS = [
  ['overview', 'Overview & modules'],
  ['contributions', 'Contributions'],
  ['decisions', 'Decisions'],
  ['tasks', 'Tasks'],
  ['dependencies', 'Dependencies'],
  ['blockers', 'Blockers'],
];

const SECTION_TO_TYPE = {
  contributions: 'contribution',
  decisions: 'decision',
  tasks: 'task_status',
  dependencies: 'dependency',
  blockers: 'blocker',
};

export function KnowledgeBasePage() {
  const { projectId, projects, setSelectedId, hasRouteId } = useActiveProjectId();
  const nav = useNavigate();
  const [section, setSection] = useState('overview');
  const [modules, setModules] = useState(null);
  const [claims, setClaims] = useState(null);
  const [latestRun, setLatestRun] = useState(undefined);
  const [moduleFilter, setModuleFilter] = useState('');
  const [fromMod, setFromMod] = useState('');
  const [toMod, setToMod] = useState('');
  const [err, setErr] = useState('');

  const loadAll = useCallback(async () => {
    if (!projectId) return;
    setErr('');
    try {
      const [r, m, c] = await Promise.all([
        api.latestRun(projectId),
        api.modules(projectId),
        api.claims(projectId),
      ]);
      setLatestRun(r);
      setModules(m);
      setClaims(c);
    } catch (x) {
      setErr(x.message);
    }
  }, [projectId]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const handleAnalyze = async () => {
    try {
      await api.analyze(projectId);
      nav(`/projects/${projectId}/reconstruct`);
    } catch (x) {
      setErr(x.message);
    }
  };

  const handleRenameModule = async (e) => {
    e.preventDefault();
    if (!fromMod || !toMod.trim()) return;
    setErr('');
    try {
      await api.renameModule(projectId, fromMod, toMod.trim());
      setFromMod('');
      setToMod('');
      await loadAll();
    } catch (x) {
      setErr(x.message);
    }
  };

  if (projects && projects.length === 0) {
    return <EmptyState title="No projects yet"><Link to="/projects">Create a project</Link> first.</EmptyState>;
  }

  const wantedType = SECTION_TO_TYPE[section];
  const filteredClaims = (claims || []).filter((c) => {
    if (wantedType && c.claim_type !== wantedType) return false;
    if (moduleFilter && c.module !== moduleFilter) return false;
    return true;
  });

  return (
    <>
      <ProjectHeaderBar
        title="Knowledge base"
        subtitle="Structured project claims correlated by module, work thread, and source evidence."
        projectId={projectId}
        projects={projects}
        setSelectedId={setSelectedId}
        hasRouteId={hasRouteId}
        actions={
          <button className="btn primary" onClick={handleAnalyze}>
            <RefreshCw size={14} strokeWidth={1.5} />
            {latestRun ? 'Re-run analysis' : 'Analyze project'}
          </button>
        }
      />
      {err && <div className="alert error">{err}</div>}

      {latestRun === undefined || !claims ? (
        <Loading />
      ) : latestRun === null && claims.length === 0 ? (
        <EmptyState title="Project has not been analysed yet">
          Run analysis on your project sources to populate modules, decisions, tasks, contributions, dependencies, and blockers.
        </EmptyState>
      ) : (
        <>
          <div className="tabs">
            {KB_SECTIONS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`tab ${section === key ? 'active' : ''}`}
                onClick={() => setSection(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {section === 'overview' ? (
            <>
              <h2>Discovered modules ({modules?.length || 0})</h2>
              {!modules || modules.length === 0 ? (
                <EmptyState title="No modules discovered yet">Add sources and run analysis.</EmptyState>
              ) : (
                <>
                  <div className="table-wrap" style={{ marginBottom: 16 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Module</th>
                          <th>Total claims</th>
                          <th>Tasks</th>
                          <th>Decisions</th>
                          <th>Contributions</th>
                          <th>Blockers</th>
                          <th>Owners</th>
                        </tr>
                      </thead>
                      <tbody>
                        {modules.map((m) => (
                          <tr
                            key={m.name}
                            className="clickable"
                            onClick={() => { setModuleFilter(m.name); setSection('tasks'); }}
                          >
                            <td className="mono"><strong>{m.name}</strong></td>
                            <td>{m.claim_count}</td>
                            <td>{m.task_count}</td>
                            <td>{m.decision_count}</td>
                            <td>{m.contribution_count}</td>
                            <td>{m.blocker_count}</td>
                            <td>{m.owners.length > 0 ? m.owners.join(', ') : <span className="muted">Unassigned</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <form className="card row" style={{ alignItems: 'flex-end' }} onSubmit={handleRenameModule}>
                    <div className="field" style={{ marginBottom: 0 }}>
                      <label htmlFor="from-mod">Rename or merge module</label>
                      <select id="from-mod" value={fromMod} onChange={(e) => setFromMod(e.target.value)} required>
                        <option value="">Select module...</option>
                        {modules.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
                      </select>
                    </div>
                    <div className="field" style={{ marginBottom: 0 }}>
                      <label htmlFor="to-mod">Into module name</label>
                      <input
                        id="to-mod"
                        placeholder="e.g. payments"
                        value={toMod}
                        onChange={(e) => setToMod(e.target.value)}
                        required
                      />
                    </div>
                    <div>
                      <button className="btn" type="submit">Apply rename / merge</button>
                    </div>
                  </form>
                </>
              )}
            </>
          ) : (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, gap: 12, flexWrap: 'wrap' }}>
                <div className="muted">Showing {filteredClaims.length} claim(s)</div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <select
                    aria-label="Filter by module"
                    value={moduleFilter}
                    onChange={(e) => setModuleFilter(e.target.value)}
                    style={{ width: 'auto' }}
                  >
                    <option value="">All modules</option>
                    {(modules || []).map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
                  </select>
                </div>
              </div>

              {filteredClaims.length === 0 ? (
                <EmptyState title="No matching claims in this section">
                  No {section} claims were found for the current filter.
                </EmptyState>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>Title</th>
                        <th>Module</th>
                        <th>Owner</th>
                        <th>Source</th>
                        <th>Date</th>
                        <th>Status</th>
                        <th>Origin</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredClaims.map((c) => (
                        <tr
                          key={c.id}
                          className="clickable"
                          onClick={() => nav(`/projects/${projectId}/ledger?claim=${c.id}`)}
                        >
                          <td className="mono">{c.id}</td>
                          <td>
                            <div><strong>{c.title}</strong></div>
                            <div className="muted">{c.text}</div>
                          </td>
                          <td className="mono">{c.module}</td>
                          <td>{c.owner_name || <span className="muted">Unassigned</span>}</td>
                          <td>
                            {c.primary_source_id ? (
                              <span className="mono">
                                {c.primary_source_name} {c.primary_locator ? `(${c.primary_locator})` : ''}
                              </span>
                            ) : '-'}
                          </td>
                          <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(c.event_time)}</td>
                          <td><VerificationBadge status={c.verification_status} /></td>
                          <td><OriginBadge origin={c.origin_label} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
