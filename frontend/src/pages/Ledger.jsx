import React, { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { X, Check, Edit3, XCircle, ShieldCheck } from 'lucide-react';
import api from '../api/client';
import {
  EmptyState,
  Loading,
  OriginBadge,
  VerificationBadge,
} from '../components/ui';
import { ProjectHeaderBar, useActiveProjectId } from './Reconstruction';

const fmtDate = (d) => (d ? new Date(d).toLocaleString() : '-');

const CLAIM_TYPES = [
  'task_status',
  'decision',
  'ownership',
  'blocker',
  'dependency',
  'contribution',
  'testing',
  'doc_gap',
];

const VERIFICATION_STATUSES = ['verified', 'inferred', 'conflicting', 'missing'];
const REVIEW_STATUSES = ['unreviewed', 'approved', 'edited', 'rejected'];

export function HighlightedChunkText({ chunkText, excerpt, highlightStart, highlightEnd }) {
  if (!chunkText) return <div className="chunk-box muted">Chunk text unavailable.</div>;

  let start = highlightStart;
  let end = highlightEnd;
  if ((start === null || start === undefined || start < 0) && excerpt) {
    const idx = chunkText.indexOf(excerpt);
    if (idx >= 0) {
      start = idx;
      end = idx + excerpt.length;
    }
  }

  if (start !== null && start !== undefined && start >= 0 && end > start) {
    const before = chunkText.slice(0, start);
    const match = chunkText.slice(start, end);
    const after = chunkText.slice(end);
    return (
      <div className="chunk-box">
        {before}
        <mark className="excerpt-mark">{match}</mark>
        {after}
      </div>
    );
  }

  return (
    <div className="chunk-box">
      <div><mark className="excerpt-mark">{excerpt}</mark></div>
      <div style={{ marginTop: 8 }}>{chunkText}</div>
    </div>
  );
}

export function SourceDrawer({ claimId, projectId, onClose, onUpdated }) {
  const [detail, setDetail] = useState(null);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (!claimId) return;
    setDetail(null);
    setEditing(false);
    setErr('');
    api.claimDetail(claimId).then((d) => {
      setDetail(d);
      setEditText(d.text);
    }).catch((x) => setErr(x.message));
  }, [claimId]);

  if (!claimId) return null;

  const submitReview = async (action) => {
    setBusy(true);
    setErr('');
    try {
      const updated = await api.reviewClaim(claimId, {
        action,
        new_text: action === 'edit' ? editText : undefined,
      });
      setDetail(updated);
      setEditing(false);
      if (onUpdated) onUpdated(updated);
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} aria-label="Evidence source drawer">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <span className="mono"><strong>{claimId}</strong></span>
          </div>
          <button className="btn sm" type="button" onClick={onClose}>
            <X size={14} strokeWidth={1.5} />Close
          </button>
        </div>

        {err && <div className="alert error">{err}</div>}
        {!detail ? (
          <Loading label="Loading evidence" />
        ) : (
          <>
            <h2 style={{ marginBottom: 8 }}>{detail.title}</h2>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
              <VerificationBadge status={detail.verification_status} />
              <OriginBadge origin={detail.origin_label} />
              <span className="badge">Review: {detail.review_status}</span>
              <span className="badge mono">{detail.module}</span>
              <span className="badge">{detail.claim_type}</span>
              {detail.confidence !== null && detail.confidence !== undefined && (
                <span className="badge mono">Confidence: {Math.round(detail.confidence * 100)}%</span>
              )}
            </div>

            {!editing ? (
              <div className="card">
                <p style={{ marginBottom: 8 }}>{detail.text}</p>
                <div className="muted" style={{ fontSize: 12 }}>
                  Owner: {detail.owner_name || 'Unassigned'}
                  {' · '}Author: {detail.author || '-'}
                  {' · '}Event date: {fmtDate(detail.event_time)}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                  <button className="btn sm" disabled={busy} onClick={() => submitReview('approve')}>
                    <Check size={12} strokeWidth={1.5} />Approve
                  </button>
                  <button className="btn sm" disabled={busy} onClick={() => setEditing(true)}>
                    <Edit3 size={12} strokeWidth={1.5} />Edit claim
                  </button>
                  <button className="btn sm danger" disabled={busy} onClick={() => submitReview('reject')}>
                    <XCircle size={12} strokeWidth={1.5} />Reject
                  </button>
                </div>
              </div>
            ) : (
              <div className="card">
                <label htmlFor="claim-edit-box">Edit claim statement</label>
                <textarea
                  id="claim-edit-box"
                  rows={3}
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                />
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <button className="btn sm primary" disabled={busy} onClick={() => submitReview('edit')}>
                    Save &amp; mark edited
                  </button>
                  <button className="btn sm" type="button" onClick={() => setEditing(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <h3>Cited evidence ({detail.evidence?.length || 0})</h3>
            {(!detail.evidence || detail.evidence.length === 0) ? (
              <EmptyState title="No valid evidence rows">
                This claim has no linked source chunk and cannot be verified.
              </EmptyState>
            ) : (
              detail.evidence.map((ev) => (
                <div key={ev.id} className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                    <div>
                      <Link to={`/projects/${projectId || detail.project_id}/sources/${ev.source_id}`}>
                        <strong className="mono">{ev.source_id}</strong> — {ev.source_filename}
                      </Link>
                    </div>
                    <span className="badge mono">{ev.locator || 'chunk'}</span>
                  </div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    Author: {ev.author || '-'} · Date: {fmtDate(ev.timestamp)} · Type: {ev.source_type}
                  </div>
                  <div style={{ marginTop: 8, fontSize: 12 }} className="muted">
                    Exact excerpt highlighted inside surrounding source chunk:
                  </div>
                  <HighlightedChunkText
                    chunkText={ev.chunk_text}
                    excerpt={ev.excerpt}
                    highlightStart={ev.highlight_start}
                    highlightEnd={ev.highlight_end}
                  />
                </div>
              ))
            )}
          </>
        )}
      </aside>
    </div>
  );
}

export function EvidenceLedgerPage() {
  const { projectId, projects, setSelectedId, hasRouteId } = useActiveProjectId();
  const [searchParams, setSearchParams] = useSearchParams();
  const [claims, setClaims] = useState(null);
  const [modules, setModules] = useState([]);
  const [validation, setValidation] = useState(null);
  const [filters, setFilters] = useState({
    type: '',
    module: '',
    status: '',
    owner: '',
    review_status: '',
    q: '',
  });
  const [selectedClaimId, setSelectedClaimId] = useState(searchParams.get('claim') || '');
  const [err, setErr] = useState('');

  useEffect(() => {
    const fromUrl = searchParams.get('claim');
    if (fromUrl) setSelectedClaimId(fromUrl);
  }, [searchParams]);

  const loadLedger = useCallback(async () => {
    if (!projectId) return;
    setErr('');
    try {
      const [c, m, v] = await Promise.all([
        api.claims(projectId, filters),
        api.modules(projectId),
        api.ledgerValidation(projectId),
      ]);
      setClaims(c);
      setModules(m);
      setValidation(v);
    } catch (x) {
      setErr(x.message);
    }
  }, [projectId, filters]);

  useEffect(() => { loadLedger(); }, [loadLedger]);

  const setFilter = (k) => (e) => setFilters((prev) => ({ ...prev, [k]: e.target.value }));

  const openClaim = (cid) => {
    setSelectedClaimId(cid);
    setSearchParams(cid ? { claim: cid } : {});
  };

  if (projects && projects.length === 0) {
    return <EmptyState title="No projects yet"><Link to="/projects">Create a project</Link> first.</EmptyState>;
  }

  return (
    <>
      <ProjectHeaderBar
        title="Evidence ledger"
        subtitle="Every extracted claim with verified chunk citations, provenance labels, and human review state."
        projectId={projectId}
        projects={projects}
        setSelectedId={setSelectedId}
        hasRouteId={hasRouteId}
        actions={
          validation && (
            <span className={`badge ${validation.invalid_citation_count === 0 ? 'ok' : 'bad'}`}>
              <ShieldCheck size={13} strokeWidth={1.5} />
              Citations valid: {validation.valid_citations}/{validation.total_citations} (invalid: {validation.invalid_citation_count})
            </span>
          )
        }
      />

      {err && <div className="alert error">{err}</div>}

      <div className="card">
        <div className="row">
          <div>
            <label htmlFor="flt-q">Search</label>
            <input
              id="flt-q"
              placeholder="Search title, text, module..."
              value={filters.q}
              onChange={setFilter('q')}
            />
          </div>
          <div>
            <label htmlFor="flt-type">Claim type</label>
            <select id="flt-type" value={filters.type} onChange={setFilter('type')}>
              <option value="">All types</option>
              {CLAIM_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="flt-mod">Module</label>
            <select id="flt-mod" value={filters.module} onChange={setFilter('module')}>
              <option value="">All modules</option>
              {modules.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="flt-st">Verification status</label>
            <select id="flt-st" value={filters.status} onChange={setFilter('status')}>
              <option value="">All statuses</option>
              {VERIFICATION_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="flt-rev">Reviewer status</label>
            <select id="flt-rev" value={filters.review_status} onChange={setFilter('review_status')}>
              <option value="">All review states</option>
              {REVIEW_STATUSES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="flt-own">Owner</label>
            <input
              id="flt-own"
              placeholder="Filter owner..."
              value={filters.owner}
              onChange={setFilter('owner')}
            />
          </div>
        </div>
      </div>

      {!claims ? (
        <Loading />
      ) : claims.length === 0 ? (
        <EmptyState title="No claims match the current filters">
          Run project analysis first or clear filters to view extracted claims.
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Type</th>
                <th>Claim</th>
                <th>Module</th>
                <th>Owner</th>
                <th>Source locator</th>
                <th>Status</th>
                <th>Origin</th>
                <th>Review</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => openClaim(c.id)}>
                  <td className="mono">{c.id}</td>
                  <td><span className="badge">{c.claim_type}</span></td>
                  <td>
                    <div><strong>{c.title}</strong></div>
                    <div className="muted">{c.text}</div>
                  </td>
                  <td className="mono">{c.module}</td>
                  <td>{c.owner_name || <span className="muted">Unassigned</span>}</td>
                  <td className="mono">
                    {c.primary_source_name || '-'}{' '}
                    {c.primary_locator ? `(${c.primary_locator})` : ''}
                  </td>
                  <td><VerificationBadge status={c.verification_status} /></td>
                  <td><OriginBadge origin={c.origin_label} /></td>
                  <td><span className="badge">{c.review_status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SourceDrawer
        claimId={selectedClaimId}
        projectId={projectId}
        onClose={() => openClaim('')}
        onUpdated={() => loadLedger()}
      />
    </>
  );
}
