import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { EmptyState, Loading } from '../components/ui';

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
      <p className="muted">Ingestion status across your projects. Claim extraction and handovers are not built yet.</p>
      {err && <div className="alert error">{err}</div>}
      {!rows ? <Loading /> : rows.length === 0 ? (
        <EmptyState title="No projects yet"><Link to="/projects">Go to projects</Link> to create one.</EmptyState>
      ) : (
        <table style={{ marginTop: 16 }}>
          <thead><tr><th>Project</th><th>Sources</th><th>Chunks</th><th>Members</th></tr></thead>
          <tbody>{rows.map(({ p, s }) => (
            <tr key={p.id}><td><Link to={`/projects/${p.id}`}>{p.name}</Link></td><td>{s.source_count}</td><td>{s.chunk_count}</td><td>{s.member_count}</td></tr>
          ))}</tbody>
        </table>
      )}
    </>
  );
}
