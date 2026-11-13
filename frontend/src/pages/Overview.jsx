import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { EmptyState, Loading, VerificationBadge } from '../components/ui';

export function Overview() {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const projects = await api.projects();
        setRows(await Promise.all(projects.map(async (p) => ({ p, s: await api.summary(p.id) }))));
      } catch (x) { setErr(x.message); }
    })();
  }, []);

  return (
    <>
      <h1>Overview</h1>
      <p className="muted">Live project ingestion, claim verification breakdown, and open contradictions derived strictly from the database.</p>
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
    </>
  );
}
