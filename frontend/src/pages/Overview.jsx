import React, { useEffect, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import api from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { AskKnowledgePanel } from '../components/AskKnowledgePanel';
import { EmptyState, Loading, StatusBadge, VerificationBadge } from '../components/ui';

export function Overview() {
  const { workspace } = useAuth();
  const [rows, setRows] = useState(null);
  const [handovers, setHandovers] = useState([]);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (workspace?.role === 'incoming') return;
    (async () => {
      try {
        const [projects, hList] = await Promise.all([
          api.projects(),
          api.handovers().catch(() => []),
        ]);
        setHandovers(hList);
        setRows(await Promise.all(projects.map(async (p) => ({ p, s: await api.summary(p.id) }))));
      } catch (x) { setErr(x.message); }
    })();
  }, [workspace?.role]);

  if (workspace?.role === 'incoming') {
    return <Navigate to="/portal" replace />;
  }

  const latestHandover = handovers[0] || null;
  const firstProjectId = rows && rows.length > 0 ? rows[0].p.id : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Continuity Overview</h1>
          <p className="muted">Handover readiness, human-verified project health, and open knowledge gaps.</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Link className="btn primary" to="/handovers">Open Handover Center</Link>
          <Link className="btn" to="/handover-reports">Handover reports</Link>
        </div>
      </div>

      {latestHandover && (
        <div className="panel" style={{ borderLeft: '3px solid var(--accent)', marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <div>
              <div className="muted" style={{ fontSize: 12 }}>Latest handover</div>
              <strong>{latestHandover.title}</strong>
              <span className="muted"> · Readiness {Math.round(latestHandover.readiness_score || 0)}/100</span>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <StatusBadge status={latestHandover.status} />
              <Link className="btn sm" to={`/projects/${latestHandover.project_id}/handovers`}>Review handover</Link>
            </div>
          </div>
        </div>
      )}

      {err && <div className="alert error">{err}</div>}
      {!rows ? <Loading /> : rows.length === 0 ? (
        <EmptyState title="No projects yet"><Link to="/projects">Go to projects</Link> to create one.</EmptyState>
      ) : (
        <div className="table-wrap" style={{ marginTop: 16 }}>
          <table>
            <thead>
              <tr>
                <th>Project</th>
                <th>Sources</th>
                <th>Chunks</th>
                <th>Members</th>
                <th>Total claims</th>
                <th>Reviewed</th>
                <th>Open questions</th>
                <th>Claim status breakdown</th>
                <th>Open contradictions</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map(({ p, s }) => {
                const bySt = s.claims_by_status || {};
                return (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/projects/${p.id}`}><strong>{p.name}</strong></Link>
                      {p.is_synthetic && <> <span className="badge warn">sample</span></>}
                    </td>
                    <td className="mono">{s.source_count}</td>
                    <td className="mono">{s.chunk_count}</td>
                    <td className="mono">{s.member_count}</td>
                    <td className="mono">{s.analysed ? s.claim_count : <span className="muted">Not analysed yet</span>}</td>
                    <td className="mono">
                      {!s.analysed ? (
                        <span className="muted">Not analysed yet</span>
                      ) : (
                        <Link to={`/projects/${p.id}/review`}>
                          {s.reviewed_claim_count} / {s.claim_count}
                        </Link>
                      )}
                    </td>
                    <td className="mono">
                      {!s.analysed ? (
                        <span className="muted">Not analysed yet</span>
                      ) : s.total_question_count === 0 ? (
                        <Link to={`/projects/${p.id}/interview`} className="muted">Not generated</Link>
                      ) : (
                        <Link to={`/projects/${p.id}/interview`}>
                          {s.open_question_count} / {s.total_question_count}
                        </Link>
                      )}
                    </td>
                    <td>
                      {!s.analysed ? (
                        <span className="muted">Not analysed yet</span>
                      ) : (
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          {['verified', 'inferred', 'conflicting', 'missing'].map((st) => (
                            <span key={st} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                              <VerificationBadge status={st} />
                              <span className="mono">{bySt[st] || 0}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      {!s.analysed ? (
                        <span className="muted">Not analysed yet</span>
                      ) : (
                        <Link to={`/projects/${p.id}/contradictions`}>
                          <span className={`badge ${s.open_contradiction_count > 0 ? 'bad' : 'ok'}`}>
                            <span className="badge-dot" />
                            {s.open_contradiction_count} open
                          </span>
                        </Link>
                      )}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <Link className="btn sm" to={`/projects/${p.id}/reconstruct`}>
                        {s.analysed ? 'View analysis' : 'Analyze'}
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {firstProjectId && (
        <div style={{ marginTop: 16 }}>
          <AskKnowledgePanel projectId={firstProjectId} compact />
        </div>
      )}
    </>
  );
}
