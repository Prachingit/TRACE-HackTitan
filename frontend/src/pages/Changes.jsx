import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { EmptyState, Loading, ProjectSubnav, StaleBadge, StatusBadge, VerificationBadge } from '../components/ui';
import { ProjectHeaderBar, useActiveProjectId } from './Reconstruction';

const fmtDate = (d) => (d ? new Date(d).toLocaleString() : '-');

const CHANGE_BADGE = {
  added: 'ok',
  modified: 'warn',
  removed: 'bad',
};

export function ChangesPage() {
  const { projectId, projects, setSelectedId, hasRouteId } = useActiveProjectId();
  const [data, setData] = useState(null);
  const [sourceFilter, setSourceFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    api.projectChanges(projectId, sourceFilter ? { source_id: sourceFilter } : {})
      .then((res) => setData(res))
      .catch((err) => setError(err.message || 'Failed to load source changes.'))
      .finally(() => setLoading(false));
  }, [projectId, sourceFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const versions = data?.versions || [];
  const changes = data?.changes || [];
  const affected = data?.affected_claims || [];

  const uniqueSources = [];
  const seenSrc = new Set();
  for (const v of versions) {
    if (!seenSrc.has(v.source_id)) {
      seenSrc.add(v.source_id);
      uniqueSources.push({ id: v.source_id, name: v.source_filename || v.source_id });
    }
  }

  return (
    <div>
      {hasRouteId && <ProjectSubnav projectId={projectId} />}
      <ProjectHeaderBar
        title="Source Changes & Stale Claims"
        subtitle="Track source versions, chunk-level additions/removals/edits, and claims affected by updates."
        projects={projects}
        projectId={projectId}
        onSelect={setSelectedId}
        hasRouteId={hasRouteId}
      />

      {error && <div className="alert error">{error}</div>}
      {loading && <Loading label="Loading source changes" />}

      {!loading && data && (
        <div style={{ display: 'grid', gap: 16 }}>
          <div className="card" style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Source versions</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{versions.length}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Chunk changes</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{changes.length}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Stale claims</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{data.stale_claims_count || 0}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Possibly affected</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{data.possibly_affected_count || 0}</div>
              </div>
            </div>
            {uniqueSources.length > 0 && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <select
                  className="input"
                  aria-label="Filter by source"
                  value={sourceFilter}
                  onChange={(e) => setSourceFilter(e.target.value)}
                >
                  <option value="">All sources</option>
                  {uniqueSources.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
                <button className="btn sm" type="button" onClick={load}>Refresh</button>
              </div>
            )}
          </div>

          <div className="card">
            <h2 style={{ marginTop: 0 }}>Affected claims ({affected.length})</h2>
            {affected.length === 0 ? (
              <EmptyState title="No stale or affected claims">
                When a source is re-uploaded, re-synced, or edited with different content, any claim citing a changed chunk will appear here as stale.
              </EmptyState>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Claim</th>
                      <th>Module</th>
                      <th>Status</th>
                      <th>State</th>
                      <th>Reason</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {affected.map((c) => (
                      <tr key={c.id}>
                        <td>
                          <div className="mono" style={{ fontSize: 12 }}>{c.id}</div>
                          <div style={{ fontWeight: 500 }}>{c.title}</div>
                        </td>
                        <td>{c.module}</td>
                        <td><VerificationBadge status={c.verification_status} /></td>
                        <td><StaleBadge isStale={c.is_stale} possiblyAffected={c.possibly_affected} /></td>
                        <td style={{ fontSize: 13 }}>{c.stale_reason || c.affected_reason || '-'}</td>
                        <td>
                          <Link className="btn sm" to={`/projects/${projectId}/review?claim=${c.id}`}>
                            Review
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <h2 style={{ marginTop: 0 }}>Chunk-level changes ({changes.length})</h2>
            {changes.length === 0 ? (
              <EmptyState title="No chunk changes recorded yet">
                Re-upload an updated file with the same filename, re-sync a GitHub repository, or edit a manual entry to see chunk-level diffs here.
              </EmptyState>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Versions</th>
                      <th>Type</th>
                      <th>Old vs New Chunk</th>
                      <th>Recorded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {changes.map((ch) => (
                      <tr key={ch.id}>
                        <td>
                          <div style={{ fontWeight: 500 }}>{ch.source_filename}</div>
                          <div className="mono muted" style={{ fontSize: 12 }}>{ch.source_id}</div>
                        </td>
                        <td className="mono">
                          v{ch.from_version || '?'} &rarr; v{ch.to_version || '?'}
                          {ch.similarity !== null && ch.similarity !== undefined && (
                            <div className="muted" style={{ fontSize: 11 }}>sim {Math.round(ch.similarity * 100)}%</div>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${CHANGE_BADGE[ch.change_type] || ''}`}>
                            <span className="badge-dot" />
                            {ch.change_type}
                          </span>
                        </td>
                        <td style={{ minWidth: 260 }}>
                          {ch.old_text && (
                            <div className="diff-del" style={{ padding: 6, marginBottom: 4, fontSize: 12 }}>
                              <span className="mono muted">[{ch.old_locator || 'old'}] </span>
                              {ch.old_text}
                            </div>
                          )}
                          {ch.new_text && (
                            <div className="diff-ins" style={{ padding: 6, fontSize: 12 }}>
                              <span className="mono muted">[{ch.new_locator || 'new'}] </span>
                              {ch.new_text}
                            </div>
                          )}
                        </td>
                        <td style={{ fontSize: 12 }}>{fmtDate(ch.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <h2 style={{ marginTop: 0 }}>Source version history ({versions.length})</h2>
            {versions.length === 0 ? (
              <EmptyState title="No source versions recorded yet" />
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Version</th>
                      <th>Origin</th>
                      <th>Chunks</th>
                      <th>Diff Summary</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {versions.map((v) => (
                      <tr key={v.id}>
                        <td>
                          <Link to={`/projects/${projectId}/sources/${v.source_id}`} style={{ fontWeight: 500 }}>
                            {v.source_filename}
                          </Link>
                          <div className="mono muted" style={{ fontSize: 12 }}>{v.source_id}</div>
                        </td>
                        <td className="mono">v{v.version_number}</td>
                        <td>{v.origin || 'initial'}</td>
                        <td>{v.chunk_count}</td>
                        <td className="mono" style={{ fontSize: 12 }}>
                          +{v.added_count} / -{v.removed_count} / ~{v.modified_count}
                        </td>
                        <td><StatusBadge status={v.status} /></td>
                        <td style={{ fontSize: 12 }}>{fmtDate(v.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
