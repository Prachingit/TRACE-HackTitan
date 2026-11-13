import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { X, CheckCircle2 } from 'lucide-react';
import api from '../api/client';
import {
  EmptyState,
  Loading,
  OriginBadge,
  StatusBadge,
  VerificationBadge,
} from '../components/ui';
import { HighlightedChunkText, SourceDrawer } from './Ledger';
import { ProjectHeaderBar, useActiveProjectId } from './Reconstruction';

const fmtDate = (d) => (d ? new Date(d).toLocaleString() : '-');

const RULE_CODES = [
  'STATUS_WITHOUT_EVIDENCE',
  'CONFLICTING_STATUS',
  'CONFLICTING_OWNERSHIP',
  'UNRESOLVED_DEPENDENCY',
  'STALE_ACTIVITY',
  'UNDOCUMENTED_WORK',
  'UNASSIGNED_RESPONSIBILITY',
  'MISSING_TEST_EVIDENCE',
];

const SEVERITY_CLASS = {
  high: 'bad',
  medium: 'warn',
  low: 'info',
};

export function SeverityBadge({ severity }) {
  return (
    <span className={`badge ${SEVERITY_CLASS[severity] || ''}`}>
      <span className="badge-dot" />
      {severity}
    </span>
  );
}

export function ContradictionRadarPage() {
  const { projectId, projects, setSelectedId, hasRouteId } = useActiveProjectId();
  const [items, setItems] = useState(null);
  const [filters, setFilters] = useState({ rule_code: '', status: '', severity: '' });
  const [selectedId, setSelectedContradictionId] = useState('');
  const [detail, setDetail] = useState(null);
  const [drawerClaimId, setDrawerClaimId] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const loadList = useCallback(async () => {
    if (!projectId) return;
    setErr('');
    try {
      const list = await api.contradictions(projectId, filters);
      setItems(list);
    } catch (x) {
      setErr(x.message);
    }
  }, [projectId, filters]);

  useEffect(() => { loadList(); }, [loadList]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    setDetail(null);
    setNote('');
    api.contradictionDetail(selectedId).then(setDetail).catch((x) => setErr(x.message));
  }, [selectedId]);

  const setFilter = (k) => (e) => setFilters((prev) => ({ ...prev, [k]: e.target.value }));

  const handleResolve = async (e) => {
    e.preventDefault();
    if (!note.trim()) {
      setErr('A resolution note is required.');
      return;
    }
    setBusy(true);
    setErr('');
    try {
      const updated = await api.resolveContradiction(selectedId, note.trim());
      setDetail(updated);
      setNote('');
      await loadList();
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
        title="Contradiction radar"
        subtitle="Deterministic conflict, gap, and risk rules evaluated across your project's claims and sources."
        projectId={projectId}
        projects={projects}
        setSelectedId={setSelectedId}
        hasRouteId={hasRouteId}
      />

      {err && <div className="alert error">{err}</div>}

      <div className="card">
        <div className="row">
          <div>
            <label htmlFor="flt-rule">Rule</label>
            <select id="flt-rule" value={filters.rule_code} onChange={setFilter('rule_code')}>
              <option value="">All 8 rules</option>
              {RULE_CODES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="flt-status">Status</label>
            <select id="flt-status" value={filters.status} onChange={setFilter('status')}>
              <option value="">All statuses</option>
              <option value="open">Open</option>
              <option value="resolved">Resolved</option>
            </select>
          </div>
          <div>
            <label htmlFor="flt-sev">Severity</label>
            <select id="flt-sev" value={filters.severity} onChange={setFilter('severity')}>
              <option value="">All severities</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
        </div>
      </div>

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <EmptyState title="No contradictions found">
          Run project analysis or clear filters to view detected contradictions and risks.
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Severity</th>
                <th>Rule</th>
                <th>Reason</th>
                <th>Sources</th>
                <th>Claims</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => setSelectedContradictionId(c.id)}>
                  <td className="mono">{c.id}</td>
                  <td><SeverityBadge severity={c.severity} /></td>
                  <td className="mono">{c.rule_code}</td>
                  <td>
                    <div>{c.reason}</div>
                    <div className="muted" style={{ fontSize: 12 }}>Suggested action: {c.suggested_action}</div>
                  </td>
                  <td className="mono">{c.conflicting_source_ids.join(', ') || '-'}</td>
                  <td className="mono">{c.claim_ids.length}</td>
                  <td><StatusBadge status={c.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedId && (
        <div className="drawer-backdrop" onClick={() => setSelectedContradictionId('')}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()} aria-label="Contradiction detail panel">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <span className="mono"><strong>{selectedId}</strong></span>
              </div>
              <button className="btn sm" type="button" onClick={() => setSelectedContradictionId('')}>
                <X size={14} strokeWidth={1.5} />Close
              </button>
            </div>

            {!detail ? (
              <Loading label="Loading contradiction details" />
            ) : (
              <>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                  <SeverityBadge severity={detail.severity} />
                  <span className="badge mono">{detail.rule_code}</span>
                  <StatusBadge status={detail.status} />
                </div>

                <div className="card">
                  <h3>Reason</h3>
                  <p>{detail.reason}</p>
                  <h3>Suggested human action</h3>
                  <p style={{ marginBottom: 0 }}>{detail.suggested_action}</p>
                </div>

                {detail.status === 'resolved' ? (
                  <div className="card">
                    <h3>Resolution record</h3>
                    <p style={{ marginBottom: 4 }}>{detail.resolution_note}</p>
                    <div className="muted" style={{ fontSize: 12 }}>
                      Resolved by {detail.resolved_by_name || detail.resolved_by} on {fmtDate(detail.resolved_at)}
                    </div>
                  </div>
                ) : (
                  <form className="card" onSubmit={handleResolve}>
                    <h3>Mark resolved (manual review required)</h3>
                    <p className="muted" style={{ fontSize: 12 }}>
                      Resolving records your note and timestamp. It does not automatically mark conflicting claims as verified.
                    </p>
                    <div className="field">
                      <label htmlFor="res-note">Resolution note (required)</label>
                      <textarea
                        id="res-note"
                        rows={3}
                        required
                        placeholder="Explain how this conflict was resolved or verified with the team..."
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                      />
                    </div>
                    <button className="btn primary" disabled={busy} type="submit">
                      <CheckCircle2 size={14} strokeWidth={1.5} />
                      {busy ? 'Saving...' : 'Mark resolved'}
                    </button>
                  </form>
                )}

                <h3>Conflicting sources ({detail.conflicting_sources?.length || 0})</h3>
                {detail.conflicting_sources?.length > 0 && (
                  <div className="card" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {detail.conflicting_sources.map((s) => (
                      <Link
                        key={s.id}
                        className="btn sm mono"
                        to={`/projects/${detail.project_id}/sources/${s.id}`}
                      >
                        {s.id} ({s.filename})
                      </Link>
                    ))}
                  </div>
                )}

                <h3>Involved claims &amp; source excerpts ({detail.claims?.length || 0})</h3>
                {detail.claims?.map((clm) => (
                  <div key={clm.id} className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                      <div>
                        <span className="mono"><strong>{clm.id}</strong></span> — <strong>{clm.title}</strong>
                      </div>
                      <button
                        className="btn sm"
                        type="button"
                        onClick={() => setDrawerClaimId(clm.id)}
                      >
                        Inspect in source drawer
                      </button>
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '6px 0' }}>
                      <VerificationBadge status={clm.verification_status} />
                      <OriginBadge origin={clm.origin_label} />
                      <span className="badge mono">{clm.module}</span>
                    </div>
                    <p style={{ marginBottom: 8 }}>{clm.text}</p>
                    {clm.evidence?.map((ev) => (
                      <div key={ev.id} style={{ marginTop: 8 }}>
                        <div className="muted" style={{ fontSize: 12 }}>
                          Source: <span className="mono">{ev.source_id}</span> ({ev.source_filename}) · Locator: <span className="mono">{ev.locator || '-'}</span>
                        </div>
                        <HighlightedChunkText
                          chunkText={ev.chunk_text}
                          excerpt={ev.excerpt}
                          highlightStart={ev.highlight_start}
                          highlightEnd={ev.highlight_end}
                        />
                      </div>
                    ))}
                  </div>
                ))}
              </>
            )}
          </aside>
        </div>
      )}

      <SourceDrawer
        claimId={drawerClaimId}
        projectId={projectId}
        onClose={() => setDrawerClaimId('')}
        onUpdated={() => {
          if (selectedId) api.contradictionDetail(selectedId).then(setDetail);
        }}
      />
    </>
  );
}
