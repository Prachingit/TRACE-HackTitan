import React, { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { EmptyState, Loading, ProjectSubnav, StatusBadge, VerificationBadge } from '../components/ui';

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

function DependencyVisual({ edges = [], moduleOwners = {} }) {
  const mods = Object.keys(moduleOwners);
  if (edges.length === 0 && mods.length === 0) {
    return <p className="muted" style={{ margin: 0 }}>No module ownership or dependency edges recorded yet.</p>;
  }
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {mods.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {mods.map((m) => (
            <div key={m} style={{ border: '1px solid var(--border)', padding: '6px 10px', borderRadius: 4, fontSize: 13 }}>
              <strong>{m}</strong>
              <span className="muted"> · {(moduleOwners[m] || []).join(', ') || 'Unassigned'}</span>
            </div>
          ))}
        </div>
      )}
      {edges.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Dependent task</th>
              <th>Depends on</th>
              <th>Claim</th>
            </tr>
          </thead>
          <tbody>
            {edges.map((e, i) => (
              <tr key={i}>
                <td>{e.from}</td>
                <td>{e.to}</td>
                <td className="mono">{e.claim_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function SectionItemsTable({ items = [] }) {
  if (!items || items.length === 0) {
    return <p className="muted" style={{ margin: '8px 0 0' }}>No items in this section.</p>;
  }
  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table className="table">
        <thead>
          <tr>
            <th>Item</th>
            <th>Module</th>
            <th>Verification</th>
            <th>Claims &amp; Sources</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it, idx) => (
            <tr key={it.claim_id || it.id || idx}>
              <td>
                <div style={{ fontWeight: 500 }}>{it.title || it.statement}</div>
                {it.statement && it.statement !== it.title && (
                  <div className="muted" style={{ fontSize: 12 }}>{it.statement}</div>
                )}
                {it.rationale && (
                  <div style={{ fontSize: 12, marginTop: 2 }}>
                    <span className="muted">Rationale: </span>{it.rationale}
                  </div>
                )}
                {it.why_it_matters && (
                  <div style={{ fontSize: 12, marginTop: 2 }}>
                    <span className="muted">Why: </span>{it.why_it_matters}
                  </div>
                )}
              </td>
              <td>{it.module || '—'}</td>
              <td><VerificationBadge status={it.verification_status} /></td>
              <td>
                <div className="mono" style={{ fontSize: 12 }}>
                  {(it.claim_ids || [it.claim_id]).filter(Boolean).join(', ')}
                </div>
                {(it.evidence || []).slice(0, 2).map((ev, eIdx) => (
                  <div key={eIdx} className="muted" style={{ fontSize: 11 }}>
                    {ev.source_name || 'interview'}{ev.locator ? ` (${ev.locator})` : ''}
                  </div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HandoverCenterPage() {
  const { id: routeProjectId } = useParams();
  const { workspace } = useAuth();
  const isAdmin = workspace?.role === 'admin';

  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(routeProjectId || '');
  const [members, setMembers] = useState([]);
  const [handovers, setHandovers] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState(null);
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);

  const [viewAs, setViewAs] = useState('');
  const [departingId, setDepartingId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [periodLabel, setPeriodLabel] = useState('');
  const [collapsed, setCollapsed] = useState({});
  const [editingKey, setEditingKey] = useState('');
  const [editText, setEditText] = useState('');
  const [gapNoteKey, setGapNoteKey] = useState('');
  const [gapNoteText, setGapNoteText] = useState('');

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (routeProjectId) setProjectId(routeProjectId);
  }, [routeProjectId]);

  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const list = await api.projects();
        if (cancel) return;
        setProjects(list);
        if (!routeProjectId && list.length > 0 && !projectId) {
          setProjectId(list[0].id);
        }
        if (workspace?.id) {
          const mems = await api.members(workspace.id).catch(() => []);
          if (!cancel) {
            setMembers(mems);
            const firstDep = mems.find((m) => m.role === 'departing');
            const firstInc = mems.find((m) => m.role === 'incoming');
            if (firstDep) setDepartingId(firstDep.user_id);
            if (firstInc) setTargetId(firstInc.user_id);
          }
        }
      } catch (err) {
        if (!cancel) setError(err.message || 'Failed to load workspace projects.');
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => { cancel = true; };
  }, [workspace?.id, routeProjectId]);

  const loadHandovers = useCallback(async () => {
    if (!projectId) return;
    setError('');
    try {
      const filters = viewAs ? { view_as: viewAs } : {};
      const list = await api.projectHandovers(projectId, filters);
      setHandovers(list);
      if (list.length > 0) {
        const keep = list.some((h) => h.id === selectedId) ? selectedId : list[0].id;
        setSelectedId(keep);
        const d = await api.handoverDetail(keep, filters);
        setDetail(d);
      } else {
        setSelectedId('');
        setDetail(null);
      }
    } catch (err) {
      setError(err.message || 'Failed to load handovers.');
    }
  }, [projectId, viewAs, selectedId]);

  useEffect(() => {
    loadHandovers();
  }, [projectId, viewAs]);

  async function selectHandover(hid) {
    setSelectedId(hid);
    try {
      const filters = viewAs ? { view_as: viewAs } : {};
      setDetail(await api.handoverDetail(hid, filters));
      if (showHistory) {
        setHistory(await api.handoverHistory(hid));
      }
    } catch (err) {
      setError(err.message || 'Failed to load handover detail.');
    }
  }

  async function onGenerate() {
    if (!projectId) return;
    setBusy(true);
    setError('');
    try {
      const created = await api.generateHandover(projectId, {
        departing_user_id: departingId || null,
        target_user_id: targetId || null,
        period_label: periodLabel.trim() || null,
      });
      setSelectedId(created.id);
      setDetail(created);
      await loadHandovers();
    } catch (err) {
      setError(err.message || 'Failed to generate handover.');
    } finally {
      setBusy(false);
    }
  }

  async function onSectionAction(sectionKey, reviewStatus, extra = {}) {
    if (!detail) return;
    setBusy(true);
    setError('');
    try {
      await api.patchHandoverSection(detail.id, sectionKey, {
        review_status: reviewStatus,
        ...extra,
      });
      setGapNoteKey('');
      setGapNoteText('');
      setEditingKey('');
      await selectHandover(detail.id);
    } catch (err) {
      setError(err.message || 'Failed to update section.');
    } finally {
      setBusy(false);
    }
  }

  async function onApproveHandover() {
    if (!detail) return;
    setBusy(true);
    setError('');
    try {
      const res = await api.approveHandover(detail.id);
      setDetail(res);
      await loadHandovers();
    } catch (err) {
      setError(err.message || 'Cannot approve handover yet.');
    } finally {
      setBusy(false);
    }
  }

  async function onShareHandover() {
    if (!detail || !targetId) return;
    setBusy(true);
    setError('');
    try {
      await api.shareHandover(detail.id, targetId);
      await selectHandover(detail.id);
    } catch (err) {
      setError(err.message || 'Failed to share handover.');
    } finally {
      setBusy(false);
    }
  }

  async function onRevokeShare() {
    if (!detail) return;
    setBusy(true);
    setError('');
    try {
      await api.revokeHandover(detail.id);
      await selectHandover(detail.id);
    } catch (err) {
      setError(err.message || 'Failed to revoke handover.');
    } finally {
      setBusy(false);
    }
  }

  async function toggleHistory() {
    if (!detail) return;
    const next = !showHistory;
    setShowHistory(next);
    if (next) {
      try {
        setHistory(await api.handoverHistory(detail.id));
      } catch (err) {
        setError(err.message || 'Failed to load history.');
      }
    }
  }

  if (loading) return <Loading label="Loading Handover Center" />;

  const readiness = detail?.readiness_json || {};
  const isPreview = Boolean(viewAs);

  return (
    <div>
      {routeProjectId && <ProjectSubnav projectId={routeProjectId} />}
      <div className="page-head">
        <div>
          <h1>Handover Center</h1>
          <p className="muted">Human-approved project continuity reports, readiness scoring, and controlled sharing.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {!routeProjectId && projects.length > 0 && (
            <select className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
          {isAdmin && (
            <select className="input" aria-label="View as role preview" value={viewAs} onChange={(e) => setViewAs(e.target.value)}>
              <option value="">View as: Admin (full)</option>
              <option value="incoming">Preview as: Incoming</option>
              <option value="departing">Preview as: Departing</option>
            </select>
          )}
        </div>
      </div>

      {isPreview && (
        <div className="panel" style={{ borderLeft: '3px solid var(--accent)', marginBottom: 16 }}>
          <strong>Read-only role preview: {viewAs}</strong> — showing only data visible to this role. Editing and approvals are disabled.
        </div>
      )}

      {error && <div className="panel error" style={{ marginBottom: 16 }}>{error}</div>}

      {isAdmin && !isPreview && projectId && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div>
              <label className="label">Departing member</label>
              <select className="input" value={departingId} onChange={(e) => setDepartingId(e.target.value)}>
                <option value="">Any / project-wide</option>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>{m.name} ({m.role})</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Incoming recipient</label>
              <select className="input" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                <option value="">Select incoming member</option>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>{m.name} ({m.role})</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Period label</label>
              <input
                className="input"
                placeholder="e.g. Q4 2026"
                value={periodLabel}
                onChange={(e) => setPeriodLabel(e.target.value)}
              />
            </div>
            <button className="btn primary" onClick={onGenerate} disabled={busy}>
              {busy ? 'Working...' : 'Generate handover'}
            </button>
          </div>
        </div>
      )}

      {handovers.length > 1 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
          {handovers.map((h) => (
            <button
              key={h.id}
              className={`btn sm ${h.id === detail?.id ? 'primary' : ''}`}
              onClick={() => selectHandover(h.id)}
            >
              <span className="mono">{h.id.slice(0, 8)}</span> · {h.status} · {Math.round(h.readiness_score || 0)}/100
            </button>
          ))}
        </div>
      )}

      {!detail ? (
        <EmptyState title="No handover generated yet">
          Generate a handover from your approved project claims to review sections, verify readiness, and share with an incoming team member.
        </EmptyState>
      ) : (
        <div style={{ display: 'grid', gap: 16 }}>
          {/* Continuity Overview */}
          <div className="panel">
            <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
              <div>
                <h2 style={{ margin: 0 }}>{detail.title}</h2>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  <span className="mono">{detail.id}</span>
                  {' · '}Departing: {detail.departing_user_name || 'Project-wide'}
                  {' · '}Recipient: {detail.target_user_name || 'Unassigned'}
                  {detail.period_label ? ` · Period: ${detail.period_label}` : ''}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <StatusBadge status={detail.status} />
                <a
                  className="btn sm"
                  href={api.handoverPdfUrl(detail.id, viewAs ? { view_as: viewAs } : {})}
                  target="_blank"
                  rel="noreferrer"
                >
                  Export PDF
                </a>
                {isAdmin && !isPreview && (
                  <>
                    <button className="btn sm" onClick={toggleHistory}>
                      {showHistory ? 'Hide history' : 'History'}
                    </button>
                    {detail.status === 'draft' && (
                      <button className="btn sm primary" onClick={onApproveHandover} disabled={busy}>
                        Approve handover
                      </button>
                    )}
                    {(detail.status === 'approved' || detail.status === 'shared' || detail.status === 'acknowledged') && targetId && (
                      <button className="btn sm primary" onClick={onShareHandover} disabled={busy}>
                        {detail.status === 'shared' ? 'Re-share' : 'Share with incoming'}
                      </button>
                    )}
                    {detail.status === 'shared' && (
                      <button className="btn sm" onClick={onRevokeShare} disabled={busy}>
                        Revoke share
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>

            <div className="grid4" style={{ marginTop: 14 }}>
              <div className="stat">
                <div className="muted">Readiness score</div>
                <div className="stat-num">{Math.round(detail.readiness_score || 0)}/100</div>
              </div>
              <div className="stat">
                <div className="muted">Evidence coverage</div>
                <div className="stat-num">{Math.round((readiness.evidence_coverage || 0) * 100)}%</div>
              </div>
              <div className="stat">
                <div className="muted">Verification completeness</div>
                <div className="stat-num">{Math.round((readiness.verification_completeness || 0) * 100)}%</div>
              </div>
              <div className="stat">
                <div className="muted">Unresolved gaps</div>
                <div className="stat-num">
                  {(readiness.open_contradictions_count || 0) + (readiness.unanswered_questions_count || 0)}
                </div>
              </div>
            </div>
            {readiness.formula && (
              <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                Readiness formula: <span className="mono">{readiness.formula}</span>
                {` (contradiction penalty: -${readiness.contradiction_penalty || 0}, question penalty: -${readiness.question_penalty || 0})`}
              </div>
            )}
          </div>

          {showHistory && (
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>Handover history (append-only)</h3>
              {history.length === 0 ? (
                <p className="muted">No history events recorded.</p>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Actor</th>
                      <th>Action</th>
                      <th>Section</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((ev) => (
                      <tr key={ev.id}>
                        <td>{fmtDate(ev.created_at)}</td>
                        <td>{ev.actor_name}</td>
                        <td className="mono">{ev.action}</td>
                        <td className="mono">{ev.section_key || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* 10 Structured Sections */}
          {(detail.sections || []).map((sec) => {
            const isCollapsed = Boolean(collapsed[sec.section_key]);
            const body = sec.body_json || sec.content || {};
            const isEditing = editingKey === sec.section_key;
            const isGapPrompt = gapNoteKey === sec.section_key;

            return (
              <div className="panel" key={sec.section_key}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <button
                    className="btn sm"
                    style={{ fontWeight: 600 }}
                    onClick={() => setCollapsed((p) => ({ ...p, [sec.section_key]: !p[sec.section_key] }))}
                  >
                    {isCollapsed ? '+' : '−'} {sec.title}
                  </button>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <StatusBadge status={sec.review_status} />
                    {sec.approved_with_gaps && sec.gap_note && (
                      <span className="badge warn">Gap noted: {sec.gap_note}</span>
                    )}
                    {isAdmin && !isPreview && (
                      <>
                        <button
                          className="btn sm"
                          onClick={() => {
                            setEditingKey(isEditing ? '' : sec.section_key);
                            setEditText(sec.content_md || body.summary || '');
                          }}
                        >
                          {isEditing ? 'Cancel edit' : 'Edit'}
                        </button>
                        <button
                          className="btn sm primary"
                          onClick={() => onSectionAction(sec.section_key, 'approved')}
                          disabled={busy}
                        >
                          Approve
                        </button>
                        <button
                          className="btn sm"
                          onClick={() => setGapNoteKey(isGapPrompt ? '' : sec.section_key)}
                          disabled={busy}
                        >
                          Approve w/ gap
                        </button>
                        <button
                          className="btn sm"
                          onClick={() => onSectionAction(sec.section_key, 'flagged')}
                          disabled={busy}
                        >
                          Flag
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {!isCollapsed && (
                  <div style={{ marginTop: 12 }}>
                    {isEditing ? (
                      <div style={{ display: 'grid', gap: 8, marginBottom: 10 }}>
                        <textarea
                          className="input"
                          rows={3}
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                        />
                        <div>
                          <button
                            className="btn sm primary"
                            onClick={() => onSectionAction(sec.section_key, sec.review_status, { content_md: editText })}
                            disabled={busy}
                          >
                            Save summary
                          </button>
                        </div>
                      </div>
                    ) : (
                      <p style={{ margin: '0 0 8px' }}>{sec.content_md || body.summary || ''}</p>
                    )}

                    {isGapPrompt && (
                      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
                        <input
                          className="input"
                          style={{ flex: '1 1 220px' }}
                          placeholder="Required note explaining accepted knowledge gap..."
                          value={gapNoteText}
                          onChange={(e) => setGapNoteText(e.target.value)}
                        />
                        <button
                          className="btn sm primary"
                          onClick={() =>
                            onSectionAction(sec.section_key, 'approved_with_gaps', {
                              approved_with_gaps: true,
                              gap_note: gapNoteText,
                            })
                          }
                          disabled={busy || !gapNoteText.trim()}
                        >
                          Confirm gap approval
                        </button>
                      </div>
                    )}

                    {sec.section_key === 'dependencies_ownership' && (
                      <DependencyVisual edges={body.edges || []} moduleOwners={body.module_owners || {}} />
                    )}

                    {sec.section_key === 'knowledge_gaps' ? (
                      <div style={{ display: 'grid', gap: 10 }}>
                        {Array.isArray(body.needs_review_items) && body.needs_review_items.length > 0 && (
                          <div>
                            <strong>Needs review / Unknown (Admin only)</strong>
                            <SectionItemsTable items={body.needs_review_items} />
                          </div>
                        )}
                        {Array.isArray(body.open_contradictions) && body.open_contradictions.length > 0 && (
                          <div>
                            <strong>Open contradictions ({body.open_contradictions.length})</strong>
                            <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
                              {body.open_contradictions.map((c) => (
                                <li key={c.contradiction_id}><span className="mono">{c.contradiction_id}</span> · {c.summary}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {Array.isArray(body.unanswered_questions) && body.unanswered_questions.length > 0 && (
                          <div>
                            <strong>Unanswered interview questions ({body.unanswered_questions.length})</strong>
                            <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
                              {body.unanswered_questions.map((q) => (
                                <li key={q.question_id}>{q.question_text} ({q.module})</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {Array.isArray(body.cycle_gaps) && body.cycle_gaps.length > 0 && (
                          <div>
                            <strong>Circular dependency warnings</strong>
                            <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
                              {body.cycle_gaps.map((g) => (
                                <li key={g.id}>{g.title}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    ) : (
                      Array.isArray(body.items) && <SectionItemsTable items={body.items} />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function HandoverReportsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const list = await api.handovers();
        if (!cancel) setRows(list);
      } catch (err) {
        if (!cancel) setError(err.message || 'Failed to load handover reports.');
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => { cancel = true; };
  }, []);

  if (loading) return <Loading label="Loading Handover Reports" />;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Handover Reports</h1>
          <p className="muted">Stored continuity reports, readiness scores, sharing status, and acknowledgement timestamps.</p>
        </div>
      </div>
      {error && <div className="panel error">{error}</div>}
      {rows.length === 0 ? (
        <EmptyState title="No handover reports yet">
          Open the Handover Center to generate and approve your first project handover report.
        </EmptyState>
      ) : (
        <div className="panel" style={{ overflowX: 'auto' }}>
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Project</th>
                <th>Status</th>
                <th>Readiness</th>
                <th>Recipient</th>
                <th>Approved</th>
                <th>Acknowledged</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => (
                <tr key={h.id}>
                  <td className="mono">{h.id.slice(0, 8)}</td>
                  <td>{h.project_name || h.project_id}</td>
                  <td><StatusBadge status={h.status} /></td>
                  <td>{Math.round(h.readiness_score || 0)}/100</td>
                  <td>{h.target_user_name || '—'}</td>
                  <td>{fmtDate(h.approved_at)}</td>
                  <td>{fmtDate(h.acknowledged_at)}</td>
                  <td style={{ display: 'flex', gap: 6 }}>
                    <Link className="btn sm" to={`/projects/${h.project_id}/handovers`}>Open</Link>
                    <a className="btn sm" href={api.handoverPdfUrl(h.id)} target="_blank" rel="noreferrer">PDF</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
