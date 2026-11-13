import React, { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Check, Edit3, Flag, XCircle } from 'lucide-react';
import api from '../api/client';
import {
  EmptyState,
  Loading,
  OriginBadge,
  ProjectSubnav,
  VerificationBadge,
} from '../components/ui';
import { useAuth } from '../hooks/useAuth';
import { HighlightedChunkText } from './Ledger';
import { ProjectHeaderBar, useActiveProjectId } from './Reconstruction';

const fmtDate = (d) => (d ? new Date(d).toLocaleString() : '-');

function DiffView({ diff, oldText, newText }) {
  if (!diff || diff.length === 0) {
    return (
      <div className="diff-box">
        {oldText && <div className="diff-del">{oldText}</div>}
        {newText && <div className="diff-ins">{newText}</div>}
      </div>
    );
  }
  return (
    <div className="diff-box">
      {diff.map((seg, i) => {
        if (seg.op === 'insert') return <ins key={i} className="diff-ins">{seg.text}</ins>;
        if (seg.op === 'delete') return <del key={i} className="diff-del">{seg.text}</del>;
        return <span key={i}>{seg.text}</span>;
      })}
    </div>
  );
}

export function ReviewWorkbenchPage() {
  const { workspace } = useAuth();
  const isAdmin = workspace?.role === 'admin';
  const { projectId, projects, setSelectedId, hasRouteId } = useActiveProjectId();
  const [searchParams] = useSearchParams();

  const [queue, setQueue] = useState(null);
  const [scope, setScope] = useState('open');
  const [moduleFilter, setModuleFilter] = useState('');
  const [selectedId, setSelectedClaimId] = useState(searchParams.get('claim') || '');
  const [detail, setDetail] = useState(null);
  const [history, setHistory] = useState([]);
  const [checkedIds, setCheckedIds] = useState([]);
  const [bulkResult, setBulkResult] = useState(null);

  const [mode, setMode] = useState(''); // '' | 'edit' | 'reject' | 'flag' | 'resolve_accept'
  const [editText, setEditText] = useState('');
  const [actionNote, setActionNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const loadQueue = useCallback(() => {
    if (!projectId) return;
    setErr('');
    api.reviewQueue(projectId, { scope, module: moduleFilter || undefined })
      .then((res) => {
        setQueue(res);
        setCheckedIds((prev) => prev.filter((id) => res.items.some((i) => i.id === id)));
        setSelectedClaimId((prev) => {
          if (prev && res.items.some((i) => i.id === prev)) return prev;
          return res.items[0]?.id || '';
        });
      })
      .catch((x) => {
        setQueue(null);
        setErr(x.message);
      });
  }, [projectId, scope, moduleFilter]);

  useEffect(() => { loadQueue(); }, [loadQueue]);

  const loadSelected = useCallback((cid) => {
    if (!cid) {
      setDetail(null);
      setHistory([]);
      return;
    }
    setMode('');
    setActionNote('');
    Promise.all([api.claimDetail(cid), api.claimHistory(cid)])
      .then(([d, h]) => {
        setDetail(d);
        setEditText(d.text);
        setHistory(h);
      })
      .catch((x) => setErr(x.message));
  }, []);

  useEffect(() => { loadSelected(selectedId); }, [selectedId, loadSelected]);

  const selectedQueueItem = queue?.items?.find((i) => i.id === selectedId) || null;
  const openCtrs = selectedQueueItem?.open_contradiction_ids || [];
  const blockers = selectedQueueItem?.accept_blockers || [];

  const submitAction = useCallback(async (action, extra = {}) => {
    if (!selectedId) return;
    setBusy(true);
    setErr('');
    try {
      const updated = await api.reviewClaim(selectedId, { action, ...extra });
      setDetail(updated);
      setEditText(updated.text);
      setMode('');
      setActionNote('');
      const h = await api.claimHistory(selectedId);
      setHistory(h);
      loadQueue();
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  }, [selectedId, loadQueue]);

  // Keyboard shortcuts: J/K to move row, A/E/R to act on selected claim
  useEffect(() => {
    const onKeyDown = (e) => {
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.metaKey || e.ctrlKey || e.altKey) {
        return;
      }
      const items = queue?.items || [];
      if (items.length === 0) return;
      const idx = items.findIndex((i) => i.id === selectedId);
      const k = e.key.toLowerCase();

      if (k === 'j') {
        e.preventDefault();
        const next = items[Math.min(items.length - 1, idx < 0 ? 0 : idx + 1)];
        if (next) setSelectedClaimId(next.id);
      } else if (k === 'k') {
        e.preventDefault();
        const prev = items[Math.max(0, idx <= 0 ? 0 : idx - 1)];
        if (prev) setSelectedClaimId(prev.id);
      } else if (k === 'a' && isAdmin && selectedQueueItem?.can_accept && !busy) {
        e.preventDefault();
        submitAction('accept');
      } else if (k === 'e' && isAdmin && selectedId) {
        e.preventDefault();
        setMode('edit');
      } else if (k === 'r' && isAdmin && selectedId) {
        e.preventDefault();
        setMode('reject');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [queue, selectedId, isAdmin, selectedQueueItem, busy, submitAction]);

  const toggleCheck = (id) => {
    setCheckedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const runBulkAccept = async () => {
    if (!projectId || checkedIds.length === 0) return;
    setBusy(true);
    setErr('');
    setBulkResult(null);
    try {
      const res = await api.bulkReview(projectId, checkedIds, 'Bulk review accept');
      setBulkResult(res);
      setCheckedIds([]);
      loadQueue();
      if (selectedId) loadSelected(selectedId);
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  const modules = Array.from(new Set((queue?.items || []).map((i) => i.module))).sort();
  const acceptDisabledReason = !isAdmin
    ? 'Accept disabled: Only the team lead (admin) can accept claims.'
    : detail?.review_status === 'approved'
      ? 'Already accepted.'
      : blockers.length > 0
        ? `Accept disabled: ${blockers.join(' ')}`
        : '';

  return (
    <>
      <ProjectHeaderBar
        title="Review workbench"
        subtitle="Final human authority on every claim. Conflicts and missing claims are prioritised first."
        projectId={projectId}
        projects={projects}
        setSelectedId={setSelectedId}
        hasRouteId={hasRouteId}
      />
      <ProjectSubnav projectId={projectId} />

      {err && <div className="alert error">{err}</div>}

      {!projectId ? (
        <EmptyState title="No project selected">Select a project to review claims.</EmptyState>
      ) : !queue && !err ? (
        <Loading label="Loading review queue" />
      ) : queue && (
        <>
          <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <label htmlFor="rw-scope" style={{ marginBottom: 0 }}>Queue</label>
              <select
                id="rw-scope"
                style={{ width: 'auto' }}
                value={scope}
                onChange={(e) => setScope(e.target.value)}
              >
                <option value="open">Needs attention ({queue.total})</option>
                <option value="all">All claims</option>
              </select>

              <label htmlFor="rw-mod" style={{ marginBottom: 0 }}>Module</label>
              <select
                id="rw-mod"
                style={{ width: 'auto' }}
                value={moduleFilter}
                onChange={(e) => setModuleFilter(e.target.value)}
              >
                <option value="">All modules</option>
                {modules.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>

              {isAdmin && checkedIds.length > 0 && (
                <button className="btn sm primary" type="button" disabled={busy} onClick={runBulkAccept}>
                  Accept selected ({checkedIds.length})
                </button>
              )}
            </div>

            <div className="muted" style={{ fontSize: 12 }}>
              Shortcuts: <span className="kbd">J</span> / <span className="kbd">K</span> move
              {isAdmin && <> · <span className="kbd">A</span> accept · <span className="kbd">E</span> edit · <span className="kbd">R</span> reject</>}
            </div>
          </div>

          {bulkResult && (
            <div className="alert info">
              <strong>Bulk accept complete:</strong> {bulkResult.accepted.length} accepted, {bulkResult.skipped.length} skipped.
              {bulkResult.skipped.length > 0 && (
                <ul style={{ margin: '6px 0 0 18px', padding: 0 }}>
                  {bulkResult.skipped.map((s) => (
                    <li key={s.claim_id}><span className="mono">{s.claim_id}</span>: {s.reason}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {queue.items.length === 0 ? (
            <EmptyState title="Review queue is empty">
              {scope === 'open'
                ? 'No unreviewed or flagged claims remain in this project.'
                : 'Run reconstruction analysis to extract claims into the review queue.'}
            </EmptyState>
          ) : (
            <div className="workbench">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {isAdmin && <th style={{ width: 28 }} />}
                      <th>Claim ID</th>
                      <th>Text</th>
                      <th>Module</th>
                      <th>Status</th>
                      <th>Reviewer</th>
                      <th>Evidence</th>
                      <th>Open conflicts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {queue.items.map((item) => {
                      const isSel = item.id === selectedId;
                      return (
                        <tr
                          key={item.id}
                          tabIndex={0}
                          className={`clickable ${isSel ? 'row-selected' : ''}`}
                          onClick={() => setSelectedClaimId(item.id)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              setSelectedClaimId(item.id);
                            }
                          }}
                        >
                          {isAdmin && (
                            <td onClick={(e) => e.stopPropagation()}>
                              <input
                                type="checkbox"
                                aria-label={`Select ${item.id}`}
                                checked={checkedIds.includes(item.id)}
                                onChange={() => toggleCheck(item.id)}
                                style={{ width: 'auto' }}
                              />
                            </td>
                          )}
                          <td className="mono" style={{ whiteSpace: 'nowrap' }}>{item.id}</td>
                          <td style={{ maxWidth: 260 }}>
                            <div style={{ fontWeight: 500 }}>{item.title}</div>
                            <div className="muted" style={{ fontSize: 12 }}>{item.text.slice(0, 90)}{item.text.length > 90 ? '...' : ''}</div>
                          </td>
                          <td className="mono">{item.module}</td>
                          <td><VerificationBadge status={item.verification_status} /></td>
                          <td><span className="badge">{item.review_status}</span></td>
                          <td className="mono">{item.evidence_count}</td>
                          <td className="mono">
                            {item.open_contradiction_ids.length > 0 ? (
                              <span className="badge bad"><span className="badge-dot" />{item.open_contradiction_ids.length}</span>
                            ) : '0'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <aside className="workbench-panel" aria-label="Claim review detail">
                {!detail ? (
                  <Loading label="Loading claim detail" />
                ) : (
                  <>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
                      <span className="mono"><strong>{detail.id}</strong> · v{detail.version}</span>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <VerificationBadge status={detail.verification_status} />
                        <OriginBadge origin={detail.origin_label} />
                        <span className="badge">Review: {detail.review_status}</span>
                      </div>
                    </div>

                    <h2 style={{ marginBottom: 8 }}>{detail.title}</h2>
                    <p style={{ marginBottom: 8 }}>{detail.text}</p>
                    {detail.original_text && detail.original_text !== detail.text && (
                      <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                        <strong>Original text:</strong> {detail.original_text}
                      </div>
                    )}
                    <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
                      Module: <span className="mono">{detail.module}</span>
                      {' · '}Owner: {detail.owner_name || 'Unassigned'}
                      {detail.reviewed_by_name && <> · Last reviewed by {detail.reviewed_by_name} ({fmtDate(detail.reviewed_at)})</>}
                    </div>

                    {acceptDisabledReason && (
                      <div className="alert info" style={{ fontSize: 12 }}>{acceptDisabledReason}</div>
                    )}

                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                      <button
                        className="btn sm primary"
                        type="button"
                        disabled={busy || Boolean(acceptDisabledReason)}
                        title={acceptDisabledReason || 'Accept and verify claim'}
                        onClick={() => submitAction('accept')}
                      >
                        <Check size={12} strokeWidth={1.5} />Accept
                      </button>

                      {isAdmin && openCtrs.length > 0 && blockers.length === openCtrs.length || (isAdmin && openCtrs.length > 0 && !blockers.some((b) => b.startsWith('No valid evidence'))) ? (
                        <button
                          className="btn sm"
                          type="button"
                          disabled={busy}
                          onClick={() => setMode(mode === 'resolve_accept' ? '' : 'resolve_accept')}
                        >
                          Resolve {openCtrs.length} conflict &amp; accept
                        </button>
                      ) : null}

                      <button
                        className="btn sm"
                        type="button"
                        disabled={busy || !isAdmin}
                        title={isAdmin ? 'Edit claim wording' : 'Admin only'}
                        onClick={() => setMode(mode === 'edit' ? '' : 'edit')}
                      >
                        <Edit3 size={12} strokeWidth={1.5} />Edit
                      </button>

                      <button
                        className="btn sm danger"
                        type="button"
                        disabled={busy || !isAdmin}
                        title={isAdmin ? 'Reject claim' : 'Admin only'}
                        onClick={() => setMode(mode === 'reject' ? '' : 'reject')}
                      >
                        <XCircle size={12} strokeWidth={1.5} />Reject
                      </button>

                      <button
                        className="btn sm"
                        type="button"
                        disabled={busy}
                        onClick={() => setMode(mode === 'flag' ? '' : 'flag')}
                      >
                        <Flag size={12} strokeWidth={1.5} />Flag for review
                      </button>
                    </div>

                    {mode === 'edit' && (
                      <div className="card">
                        <label htmlFor="wb-edit-text">Edited wording (original text is preserved)</label>
                        <textarea
                          id="wb-edit-text"
                          rows={3}
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                        />
                        <label htmlFor="wb-edit-note" style={{ marginTop: 8 }}>Note (optional)</label>
                        <input
                          id="wb-edit-note"
                          value={actionNote}
                          onChange={(e) => setActionNote(e.target.value)}
                          placeholder="Why was the wording updated?"
                        />
                        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                          <button
                            className="btn sm primary"
                            type="button"
                            disabled={busy || !editText.trim()}
                            onClick={() => submitAction('edit', { text: editText, note: actionNote })}
                          >
                            Save edit
                          </button>
                          <button className="btn sm" type="button" onClick={() => setMode('')}>Cancel</button>
                        </div>
                      </div>
                    )}

                    {(mode === 'reject' || mode === 'flag' || mode === 'resolve_accept') && (
                      <div className="card">
                        <label htmlFor="wb-note">
                          {mode === 'reject'
                            ? 'Rejection reason (required)'
                            : mode === 'resolve_accept'
                              ? `Resolution note for ${openCtrs.join(', ')} (required)`
                              : 'Review flag note (required)'}
                        </label>
                        <input
                          id="wb-note"
                          value={actionNote}
                          onChange={(e) => setActionNote(e.target.value)}
                          placeholder="Enter required explanation..."
                        />
                        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                          <button
                            className={`btn sm ${mode === 'reject' ? 'danger' : 'primary'}`}
                            type="button"
                            disabled={busy || !actionNote.trim()}
                            onClick={() => {
                              if (mode === 'resolve_accept') {
                                submitAction('accept', { resolve_contradictions: true, note: actionNote });
                              } else {
                                submitAction(mode, { note: actionNote });
                              }
                            }}
                          >
                            Confirm
                          </button>
                          <button className="btn sm" type="button" onClick={() => setMode('')}>Cancel</button>
                        </div>
                      </div>
                    )}

                    {openCtrs.length > 0 && (
                      <div style={{ marginBottom: 12 }}>
                        <h3>Open contradictions ({openCtrs.length})</h3>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          {openCtrs.map((cid) => (
                            <Link key={cid} className="badge bad mono" to={`/projects/${projectId}/contradictions`}>
                              <span className="badge-dot" />{cid}
                            </Link>
                          ))}
                        </div>
                      </div>
                    )}

                    <h3>Evidence ({detail.evidence?.length || 0})</h3>
                    {(!detail.evidence || detail.evidence.length === 0) ? (
                      <p className="muted" style={{ fontSize: 12 }}>No evidence attached yet.</p>
                    ) : (
                      detail.evidence.map((ev) => {
                        if (ev.evidence_type === 'interview_answer') {
                          const label = ev.label || `Interview answer, by ${ev.author || 'Unknown'}, ${ev.timestamp ? new Date(ev.timestamp).toISOString().slice(0, 10) : 'unknown date'}`;
                          return (
                            <div key={ev.id} style={{ marginBottom: 10 }}>
                              <span className="badge info"><span className="badge-dot" />{label}</span>
                              <div className="evidence-answer">{ev.excerpt}</div>
                            </div>
                          );
                        }
                        return (
                          <div key={ev.id} style={{ marginBottom: 10 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                              <Link to={`/projects/${projectId}/sources/${ev.source_id}`}>
                                <strong className="mono">{ev.source_id}</strong> · {ev.source_filename}
                              </Link>
                              <span className="badge mono">{ev.locator || 'chunk'}</span>
                            </div>
                            <HighlightedChunkText
                              chunkText={ev.chunk_text}
                              excerpt={ev.excerpt}
                              highlightStart={ev.highlight_start}
                              highlightEnd={ev.highlight_end}
                            />
                          </div>
                        );
                      })
                    )}

                    <h3 style={{ marginTop: 14 }}>Version history ({history.length})</h3>
                    {history.length === 0 ? (
                      <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>No review events yet.</p>
                    ) : (
                      history.map((ev) => (
                        <div key={ev.id} className="card" style={{ padding: 10, marginBottom: 8 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', fontSize: 12 }}>
                            <span>
                              <strong className="mono">v{ev.version}</strong> · <strong>{ev.action}</strong> by {ev.reviewer_name}
                            </span>
                            <span className="muted">{fmtDate(ev.timestamp)}</span>
                          </div>
                          {ev.note && <div style={{ fontSize: 12, marginTop: 4 }}>Note: {ev.note}</div>}
                          {ev.action === 'edit' && (
                            <div style={{ marginTop: 6 }}>
                              <DiffView diff={ev.diff} oldText={ev.old_text} newText={ev.new_text} />
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </>
                )}
              </aside>
            </div>
          )}
        </>
      )}
    </>
  );
}
