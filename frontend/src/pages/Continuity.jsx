import React, { useCallback, useEffect, useState } from 'react';
import api from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { EmptyState, Loading, ProjectSubnav } from '../components/ui';
import { SourceDrawer } from './Ledger';
import { ProjectHeaderBar, useActiveProjectId } from './Reconstruction';

const NODE_TYPES = ['', 'person', 'module', 'task', 'document', 'service'];
const CUSTODY_KINDS = [
  'repository', 'hosting', 'database', 'domain', 'CI/CD',
  'cloud account', 'third-party API', 'email/SaaS', 'other',
];
const CUSTODY_BADGE = {
  confirmed: 'ok',
  transferred: 'ok',
  unconfirmed: 'warn',
  unknown: 'bad',
};

const COL_X = { person: 30, module: 230, task: 430, document: 630, service: 630 };

function ContinuitySvgGraph({ nodes = [], edges = [], onSelectClaim }) {
  if (nodes.length === 0) return null;
  const cols = { person: [], module: [], task: [], document: [], service: [] };
  for (const n of nodes) {
    (cols[n.node_type] || cols.module).push(n);
  }
  const rightCol = [...cols.document, ...cols.service];
  const maxRows = Math.max(cols.person.length, cols.module.length, cols.task.length, rightCol.length, 1);
  const height = Math.max(220, maxRows * 52 + 40);
  const pos = {};

  const place = (list, x) => {
    list.forEach((n, idx) => {
      pos[n.id] = { x, y: 24 + idx * 50 };
    });
  };
  place(cols.person, COL_X.person);
  place(cols.module, COL_X.module);
  place(cols.task, COL_X.task);
  place(rightCol, COL_X.document);

  const edgeClaim = (e) => (e.claim_ids && e.claim_ids[0]) || '';
  const nodeClaim = (nid) => {
    const e = edges.find((x) => (x.source_node_id === nid || x.target_node_id === nid) && x.claim_ids?.length);
    return e ? e.claim_ids[0] : '';
  };

  return (
    <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)' }}>
      <svg width={820} height={height} role="img" aria-label="Continuity dependency graph">
        <defs>
          <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="var(--muted)" />
          </marker>
        </defs>
        <text x={30} y={14} fontSize="11" fill="var(--muted)">PEOPLE</text>
        <text x={230} y={14} fontSize="11" fill="var(--muted)">MODULES</text>
        <text x={430} y={14} fontSize="11" fill="var(--muted)">TASKS</text>
        <text x={630} y={14} fontSize="11" fill="var(--muted)">DOCS &amp; SERVICES</text>

        {edges.map((e) => {
          const p1 = pos[e.source_node_id];
          const p2 = pos[e.target_node_id];
          if (!p1 || !p2) return null;
          const x1 = p1.x + 150;
          const y1 = p1.y + 16;
          const x2 = p2.x;
          const y2 = p2.y + 16;
          const cid = edgeClaim(e);
          return (
            <g
              key={e.id}
              style={{ cursor: cid ? 'pointer' : 'default' }}
              onClick={() => cid && onSelectClaim(cid)}
            >
              <line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke="var(--muted)"
                strokeWidth="1.25"
                strokeDasharray={e.inferred ? '4 3' : undefined}
                markerEnd="url(#arrow)"
              />
              <title>{`${e.source_label} --${e.edge_type}${e.inferred ? ' (inferred)' : ''}--> ${e.target_label} (${cid})`}</title>
            </g>
          );
        })}

        {nodes.map((n) => {
          const p = pos[n.id];
          if (!p) return null;
          const cid = nodeClaim(n.id);
          return (
            <g
              key={n.id}
              transform={`translate(${p.x},${p.y})`}
              style={{ cursor: cid ? 'pointer' : 'default' }}
              onClick={() => cid && onSelectClaim(cid)}
            >
              <rect
                width={150}
                height={32}
                rx={4}
                fill="var(--surface, #fff)"
                stroke="var(--border)"
                strokeWidth="1.25"
              />
              <text x={8} y={13} fontSize="10" fill="var(--muted)">
                {n.node_type.toUpperCase()}
              </text>
              <text x={8} y={25} fontSize="12" fill="var(--text, #111)">
                {(n.label || '').slice(0, 19)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function ContinuityPage() {
  const { workspace } = useAuth();
  const isAdmin = workspace?.role === 'admin';
  const { projectId, projects, setSelectedId, hasRouteId } = useActiveProjectId();

  const [nodeType, setNodeType] = useState('');
  const [viewMode, setViewMode] = useState('graph'); // graph | table
  const [graph, setGraph] = useState(null);
  const [risks, setRisks] = useState(null);
  const [custody, setCustody] = useState([]);
  const [selectedPerson, setSelectedPerson] = useState('');
  const [impact, setImpact] = useState(null);
  const [drawerClaimId, setDrawerClaimId] = useState('');

  // Custody form
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    kind: 'repository',
    name: '',
    owner_person: '',
    backup_owner: '',
    where_to_request_access: '',
    notes: '',
  });
  const [historyFor, setHistoryFor] = useState(null);
  const [historyRows, setHistoryRows] = useState([]);

  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const loadAll = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const [g, r, c] = await Promise.all([
        api.projectGraph(projectId, nodeType ? { node_type: nodeType } : {}),
        api.graphRisks(projectId),
        api.listCustody(projectId),
      ]);
      setGraph(g);
      setRisks(r);
      setCustody(c || []);
      const firstPerson = (g.nodes || []).find((n) => n.node_type === 'person');
      if (firstPerson && !selectedPerson) {
        setSelectedPerson(firstPerson.id);
      }
    } catch (err) {
      setError(err.message || 'Failed to load continuity graph.');
    } finally {
      setLoading(false);
    }
  }, [projectId, nodeType]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (!projectId || !selectedPerson) {
      setImpact(null);
      return;
    }
    api.graphImpact(projectId, selectedPerson)
      .then((res) => setImpact(res))
      .catch(() => setImpact(null));
  }, [projectId, selectedPerson]);

  async function onRebuild() {
    if (!projectId) return;
    setBusy(true);
    setError('');
    try {
      await api.rebuildGraph(projectId);
      await loadAll();
    } catch (err) {
      setError(err.message || 'Failed to rebuild continuity graph.');
    } finally {
      setBusy(false);
    }
  }

  async function onCreateCustody(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api.createCustody(projectId, form);
      setForm({ kind: 'repository', name: '', owner_person: '', backup_owner: '', where_to_request_access: '', notes: '' });
      setShowAdd(false);
      setCustody(await api.listCustody(projectId));
    } catch (err) {
      setError(err.message || 'Could not save custody item.');
    } finally {
      setBusy(false);
    }
  }

  async function onConfirmCustody(cid, status) {
    setBusy(true);
    setError('');
    try {
      await api.confirmCustody(cid, status);
      setCustody(await api.listCustody(projectId));
    } catch (err) {
      setError(err.message || 'Could not update custody status.');
    } finally {
      setBusy(false);
    }
  }

  async function onToggleHistory(cid) {
    if (historyFor === cid) {
      setHistoryFor(null);
      setHistoryRows([]);
      return;
    }
    try {
      setHistoryRows(await api.custodyHistory(cid));
      setHistoryFor(cid);
    } catch (err) {
      setError(err.message || 'Could not load custody history.');
    }
  }

  const people = (graph?.nodes || []).filter((n) => n.node_type === 'person');
  const nodes = graph?.nodes || [];
  const edges = graph?.edges || [];

  return (
    <div>
      {hasRouteId && <ProjectSubnav projectId={projectId} />}
      <ProjectHeaderBar
        title="Continuity Graph & Custody Checklist"
        subtitle="Evidence-backed dependencies, single points of failure, departure impact, and secret-free access custody."
        projects={projects}
        projectId={projectId}
        onSelect={setSelectedId}
        hasRouteId={hasRouteId}
      />

      {error && <div className="alert error">{error}</div>}
      {loading && <Loading label="Loading continuity graph" />}

      {!loading && graph && (
        <div style={{ display: 'grid', gap: 16 }}>
          {/* Controls */}
          <div className="card" style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {NODE_TYPES.map((nt) => (
                <button
                  key={nt || 'all'}
                  type="button"
                  className={`btn sm ${nodeType === nt ? 'primary' : ''}`}
                  onClick={() => setNodeType(nt)}
                >
                  {nt ? nt : 'All nodes'}
                </button>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn sm"
                onClick={() => setViewMode((m) => (m === 'graph' ? 'table' : 'graph'))}
              >
                {viewMode === 'graph' ? 'Table view' : 'Graph view'}
              </button>
              <button type="button" className="btn sm primary" onClick={onRebuild} disabled={busy}>
                {busy ? 'Rebuilding...' : 'Rebuild graph'}
              </button>
            </div>
          </div>

          {/* Graph or Table View */}
          <div className="card">
            <h2 style={{ marginTop: 0 }}>Evidence-backed graph ({nodes.length} nodes, {edges.length} edges)</h2>
            {nodes.length === 0 || edges.length === 0 ? (
              <EmptyState title="No continuity edges yet">
                Run project analysis or rebuild the graph once claims with supporting evidence exist. Every edge traces to real claims.
              </EmptyState>
            ) : (
              <>
                {viewMode === 'graph' && (
                  <div style={{ marginBottom: 12 }}>
                    <ContinuitySvgGraph nodes={nodes} edges={edges} onSelectClaim={setDrawerClaimId} />
                    <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                      Click any node or edge to open the Evidence Ledger source drawer. Dashed lines mark inferred edges.
                    </div>
                  </div>
                )}
                <div style={{ overflowX: 'auto' }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th>Relation</th>
                        <th>Target</th>
                        <th>Claims</th>
                      </tr>
                    </thead>
                    <tbody>
                      {edges.map((e) => (
                        <tr
                          key={e.id}
                          className="clickable"
                          onClick={() => e.claim_ids?.[0] && setDrawerClaimId(e.claim_ids[0])}
                        >
                          <td>{e.source_label}</td>
                          <td className="mono">
                            {e.edge_type}
                            {e.inferred && <span className="badge" style={{ marginLeft: 6 }}>inferred</span>}
                          </td>
                          <td>{e.target_label}</td>
                          <td className="mono" style={{ fontSize: 12 }}>{(e.claim_ids || []).join(', ')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>

          {/* Risks & What-If Impact */}
          <div className="grid2">
            <div className="card">
              <h2 style={{ marginTop: 0 }}>Single points of failure &amp; risks</h2>
              {risks && (
                <div style={{ display: 'grid', gap: 10 }}>
                  <div>
                    <strong>Single points of failure ({risks.single_points_of_failure.length})</strong>
                    {risks.single_points_of_failure.length === 0 ? (
                      <div className="muted" style={{ fontSize: 13 }}>None detected.</div>
                    ) : (
                      <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
                        {risks.single_points_of_failure.map((s) => (
                          <li key={s.module_id}>
                            <span className="mono">{s.module}</span> — sole owner/contributor: {s.sole_owner}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div>
                    <strong>Unowned modules ({risks.unowned_modules.length})</strong>
                    <div className="muted" style={{ fontSize: 13 }}>
                      {risks.unowned_modules.map((m) => m.module).join(', ') || 'None'}
                    </div>
                  </div>
                  <div>
                    <strong>Undocumented modules ({risks.undocumented_modules.length})</strong>
                    <div className="muted" style={{ fontSize: 13 }}>
                      {risks.undocumented_modules.map((m) => m.module).join(', ') || 'None'}
                    </div>
                  </div>
                  {risks.circular_dependencies.length > 0 && (
                    <div className="alert error">
                      <strong>Circular dependencies ({risks.circular_dependencies.length})</strong>
                      <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
                        {risks.circular_dependencies.map((cyc, idx) => (
                          <li key={idx} className="mono">{cyc.join(' -> ')}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                <h2 style={{ margin: 0 }}>What breaks if X leaves?</h2>
                <select
                  className="input"
                  aria-label="Select person to simulate departure"
                  value={selectedPerson}
                  onChange={(e) => setSelectedPerson(e.target.value)}
                >
                  <option value="">Select person</option>
                  {people.map((p) => (
                    <option key={p.id} value={p.id}>{p.label}</option>
                  ))}
                </select>
              </div>
              {!impact?.person ? (
                <p className="muted" style={{ marginTop: 10 }}>Select a team member to view affected modules and tasks ranked by downstream dependents.</p>
              ) : impact.impacted.length === 0 ? (
                <p className="muted" style={{ marginTop: 10 }}>No owned or contributed items recorded for {impact.person.label}.</p>
              ) : (
                <div style={{ overflowX: 'auto', marginTop: 10 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Affected item</th>
                        <th>Role</th>
                        <th>Downstream</th>
                      </tr>
                    </thead>
                    <tbody>
                      {impact.impacted.map((it) => (
                        <tr key={it.node_id}>
                          <td>
                            <span className="mono">{it.node_type}</span>: <strong>{it.label}</strong>
                          </td>
                          <td className="mono">{it.relationship}</td>
                          <td className="mono">{it.downstream_dependents}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {/* Custody Checklist */}
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <div>
                <h2 style={{ margin: 0 }}>Account &amp; service custody checklist</h2>
                <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                  Never enter passwords, tokens, private keys, or credentialed URLs here; record who holds access instead.
                </div>
              </div>
              {isAdmin && (
                <button type="button" className="btn sm primary" onClick={() => setShowAdd((s) => !s)}>
                  {showAdd ? 'Cancel' : 'Add custody item'}
                </button>
              )}
            </div>

            {showAdd && isAdmin && (
              <form onSubmit={onCreateCustody} style={{ display: 'grid', gap: 8, marginTop: 12, padding: 12, border: '1px solid var(--border)', borderRadius: 4 }}>
                <div className="grid2">
                  <div>
                    <label className="label">Kind</label>
                    <select className="input" value={form.kind} onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value }))}>
                      {CUSTODY_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="label">Service / Account Name</label>
                    <input className="input" required placeholder="e.g. Render Production" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
                  </div>
                  <div>
                    <label className="label">Current Owner</label>
                    <input className="input" placeholder="e.g. Rahul Verma" value={form.owner_person} onChange={(e) => setForm((f) => ({ ...f, owner_person: e.target.value }))} />
                  </div>
                  <div>
                    <label className="label">Backup Owner</label>
                    <input className="input" placeholder="e.g. Alex Chen" value={form.backup_owner} onChange={(e) => setForm((f) => ({ ...f, backup_owner: e.target.value }))} />
                  </div>
                </div>
                <div>
                  <label className="label">Where to request access (plain instructions, no secrets)</label>
                  <input className="input" placeholder="e.g. Request org admin invite in #infra-access" value={form.where_to_request_access} onChange={(e) => setForm((f) => ({ ...f, where_to_request_access: e.target.value }))} />
                </div>
                <div>
                  <label className="label">Notes</label>
                  <input className="input" placeholder="Optional handover context" value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
                </div>
                <div>
                  <button className="btn sm primary" type="submit" disabled={busy}>Save item</button>
                </div>
              </form>
            )}

            {custody.length === 0 ? (
              <EmptyState title="No custody items recorded yet">
                Add repositories, hosting, databases, domains, or API accounts above, or rebuild the graph to suggest services from project sources.
              </EmptyState>
            ) : (
              <div style={{ overflowX: 'auto', marginTop: 12 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Service</th>
                      <th>Kind</th>
                      <th>Owner / Backup</th>
                      <th>Where to request access</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {custody.map((ci) => (
                      <React.Fragment key={ci.id}>
                        <tr>
                          <td>
                            <strong>{ci.name}</strong>
                            {ci.suggested && <span className="badge" style={{ marginLeft: 6 }}>suggested</span>}
                          </td>
                          <td className="mono">{ci.kind}</td>
                          <td>
                            {ci.owner_person || <span className="muted">Unassigned</span>}
                            {ci.backup_owner && <div className="muted" style={{ fontSize: 12 }}>Backup: {ci.backup_owner}</div>}
                          </td>
                          <td style={{ fontSize: 13 }}>{ci.where_to_request_access || '-'}</td>
                          <td>
                            <span className={`badge ${CUSTODY_BADGE[ci.status] || ''}`}>
                              <span className="badge-dot" />
                              {ci.status}
                            </span>
                          </td>
                          <td style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            {isAdmin && ci.status !== 'confirmed' && ci.status !== 'transferred' && (
                              <button className="btn sm primary" type="button" onClick={() => onConfirmCustody(ci.id, 'confirmed')} disabled={busy}>
                                Confirm
                              </button>
                            )}
                            {isAdmin && ci.status !== 'transferred' && (
                              <button className="btn sm" type="button" onClick={() => onConfirmCustody(ci.id, 'transferred')} disabled={busy}>
                                Mark transferred
                              </button>
                            )}
                            <button className="btn sm" type="button" onClick={() => onToggleHistory(ci.id)}>
                              {historyFor === ci.id ? 'Hide log' : 'Audit log'}
                            </button>
                          </td>
                        </tr>
                        {historyFor === ci.id && (
                          <tr>
                            <td colSpan={6} style={{ background: 'var(--bg)' }}>
                              <div style={{ fontSize: 12 }}>
                                <strong>Append-only audit history:</strong>
                                {historyRows.length === 0 ? ' None.' : (
                                  <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
                                    {historyRows.map((ev) => (
                                      <li key={ev.id}>
                                        <span className="mono">{ev.action}</span> by {ev.actor_name} ({new Date(ev.timestamp).toLocaleString()})
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {drawerClaimId && (
        <SourceDrawer
          claimId={drawerClaimId}
          projectId={projectId}
          onClose={() => setDrawerClaimId('')}
        />
      )}
    </div>
  );
}
