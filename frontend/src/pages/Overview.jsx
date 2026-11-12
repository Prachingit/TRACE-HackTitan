import React, { useState, useEffect } from 'react';
import api, { getActiveDemoUser } from '../api/client';
import StatCard from '../components/StatCard';
import StatusBadge from '../components/StatusBadge';
import Loading from '../components/Loading';

export function Overview() {
  const [projectId, setProjectId] = useState('prj-atlas-core');
  const [summary, setSummary] = useState(null);
  const [sources, setSources] = useState([]);
  const [userProfile, setUserProfile] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSeeding, setIsSeeding] = useState(false);
  const [error, setError] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // 1. Get current profile to know active role
      const me = await api.getMe();
      setUserProfile(me);

      // 2. Fetch summary & sources for active demo project
      const [summaryData, sourcesData] = await Promise.all([
        api.getProjectSummary(projectId),
        api.getProjectSources(projectId),
      ]);
      setSummary(summaryData);
      setSources(sourcesData);
    } catch (err) {
      setError(err.message || 'Failed to load project details.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();

    // Re-fetch automatically when role switcher toggles identity
    const handleRoleChange = () => {
      fetchData();
    };
    window.addEventListener('trace-role-change', handleRoleChange);
    return () => window.removeEventListener('trace-role-change', handleRoleChange);
  }, [projectId]);

  const handleLoadDemo = async () => {
    setIsSeeding(true);
    setError(null);
    setActionMessage(null);
    try {
      const res = await api.loadDemo();
      setActionMessage(`Atlas Workspace re-seeded successfully (${res.sources_registered} sources registered).`);
      await fetchData();
    } catch (err) {
      setError(err.message || 'Failed to seed demo project.');
    } finally {
      setIsSeeding(false);
    }
  };

  const isRestrictedHidden = userProfile && ['incoming', 'departing'].includes(userProfile.role);

  return (
    <div className="overview-page">
      <div className="page-header">
        <div className="header-meta">
          <div className="title-row">
            <h1 className="project-title">{summary?.project_name || 'Atlas Core Platform'}</h1>
            <StatusBadge type="synthetic" status="Synthetic" />
            <span className="category-tag">Infrastructure</span>
          </div>
          <p className="project-subtitle">
            Enterprise context and activity management engine — Team HackTitan Synthetic Demo.
          </p>
        </div>

        <div className="header-controls">
          <button
            id="load-demo-btn"
            className="btn btn-primary"
            onClick={handleLoadDemo}
            disabled={isSeeding}
          >
            {isSeeding ? 'Seeding Atlas Workspace...' : '↻ Load Demo Project'}
          </button>
        </div>
      </div>

      {actionMessage && <div className="alert alert-success">{actionMessage}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {isRestrictedHidden && (
        <div className="clearance-notice">
          <strong>Clearance Filter Active:</strong> Confidential internal files (e.g. <code>restricted_internal.md</code>) are redacted by the backend for your role (<code>{userProfile?.role}</code>). Switch to <strong>Admin</strong> in the header to view restricted sources.
        </div>
      )}

      {isLoading ? (
        <Loading message="Fetching live workspace metrics from backend..." />
      ) : (
        <>
          {/* Stat Cards Grid */}
          <section className="stats-grid">
            <StatCard
              title="Registered Sources"
              value={summary?.source_count ?? 0}
              subtext="Tracked activity streams"
            />
            <StatCard
              title="Team Members"
              value={summary?.member_count ?? 0}
              subtext="4 Core Workspace Roles"
            />
            <StatCard
              title="Verified Claims"
              value={summary?.claim_count ?? 0}
              subtext="0 extracted (Phase 3)"
            />
            <StatCard
              title="Open Contradictions"
              value={summary?.open_contradiction_count ?? 0}
              subtext="0 flagged (Phase 4)"
            />
          </section>

          {/* Sources Breakdown Section */}
          <section className="breakdown-card">
            <h2 className="section-title">Sources by Activity Stream</h2>
            <div className="type-pills">
              {summary?.sources_by_type &&
                Object.entries(summary.sources_by_type).map(([type, count]) => (
                  <div key={type} className="type-pill">
                    <span className="type-name">{type}</span>
                    <span className="type-count">{count}</span>
                  </div>
                ))}
            </div>
          </section>

          {/* Registered Sources Table */}
          <section className="sources-section">
            <div className="section-header">
              <h2 className="section-title">Registered Sources Ledger</h2>
              <span className="source-count-label">
                Displaying {sources.length} sources visible to role <strong>{userProfile?.role}</strong>
              </span>
            </div>

            <div className="table-wrapper">
              <table className="sources-table">
                <thead>
                  <tr>
                    <th>Source ID</th>
                    <th>Artifact Name</th>
                    <th>Stream Type</th>
                    <th>Clearance</th>
                    <th>Pipeline Status</th>
                    <th>Last Activity</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.length === 0 ? (
                    <tr>
                      <td colSpan="6" className="empty-cell">
                        No sources registered. Click "Load Demo Project" above.
                      </td>
                    </tr>
                  ) : (
                    sources.map((s) => (
                      <tr key={s.id} className={s.clearance_level === 'restricted' ? 'row-restricted' : ''}>
                        <td className="font-mono text-muted">{s.id}</td>
                        <td className="font-medium text-main">
                          {s.filename}
                          {s.clearance_level === 'restricted' && (
                            <span className="confidential-tag">RESTRICTED RECORD</span>
                          )}
                        </td>
                        <td>
                          <span className="type-badge">{s.type}</span>
                        </td>
                        <td>
                          <StatusBadge type="clearance" status={s.clearance_level} />
                        </td>
                        <td>
                          <StatusBadge type="status" status={s.status} />
                        </td>
                        <td className="text-muted text-sm">
                          {s.source_timestamp
                            ? new Date(s.source_timestamp).toLocaleDateString()
                            : 'N/A'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <style>{`
        .overview-page {
          display: flex;
          flex-direction: column;
          gap: var(--space-6);
        }
        .page-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: var(--space-4);
          background-color: var(--color-bg-surface);
          border: 1px solid var(--color-border);
          border-radius: var(--radius-md);
          padding: var(--space-5) var(--space-6);
          box-shadow: var(--shadow-sm);
        }
        .title-row {
          display: flex;
          align-items: center;
          gap: var(--space-3);
          margin-bottom: var(--space-1);
        }
        .project-title {
          font-size: var(--font-size-2xl);
          font-weight: var(--font-weight-bold);
          color: var(--color-text-main);
        }
        .category-tag {
          font-size: var(--font-size-xs);
          color: var(--color-text-muted);
          background-color: var(--color-bg-app);
          padding: 2px 8px;
          border-radius: var(--radius-sm);
          border: 1px solid var(--color-border);
        }
        .project-subtitle {
          font-size: var(--font-size-sm);
          color: var(--color-text-muted);
        }
        .btn {
          display: inline-flex;
          align-items: center;
          gap: var(--space-2);
          padding: 8px 16px;
          border-radius: var(--radius-md);
          font-size: var(--font-size-sm);
          font-weight: var(--font-weight-medium);
          border: none;
          transition: background-color 0.15s ease;
        }
        .btn-primary {
          background-color: var(--color-primary);
          color: #ffffff;
        }
        .btn-primary:hover:not(:disabled) {
          background-color: var(--color-primary-hover);
        }
        .btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .alert {
          padding: var(--space-3) var(--space-4);
          border-radius: var(--radius-md);
          font-size: var(--font-size-sm);
        }
        .alert-success {
          background-color: var(--status-verified-bg);
          color: var(--status-verified-text);
          border: 1px solid var(--status-verified-border);
        }
        .alert-error {
          background-color: var(--status-conflicting-bg);
          color: var(--status-conflicting-text);
          border: 1px solid var(--status-conflicting-border);
        }
        .clearance-notice {
          background-color: var(--color-primary-subtle);
          color: var(--color-primary-text);
          border: 1px solid #bfdbfe;
          border-radius: var(--radius-md);
          padding: var(--space-3) var(--space-4);
          font-size: var(--font-size-sm);
        }
        .clearance-notice code {
          background: #ffffff;
          padding: 1px 4px;
          border-radius: var(--radius-sm);
          font-family: var(--font-mono);
          font-size: 0.85em;
        }
        .stats-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: var(--space-4);
        }
        .breakdown-card {
          background-color: var(--color-bg-surface);
          border: 1px solid var(--color-border);
          border-radius: var(--radius-md);
          padding: var(--space-4);
          box-shadow: var(--shadow-sm);
        }
        .section-title {
          font-size: var(--font-size-base);
          font-weight: var(--font-weight-semibold);
          color: var(--color-text-main);
          margin-bottom: var(--space-3);
        }
        .type-pills {
          display: flex;
          flex-wrap: wrap;
          gap: var(--space-2);
        }
        .type-pill {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          background-color: var(--color-bg-app);
          border: 1px solid var(--color-border);
          padding: 4px 10px;
          border-radius: var(--radius-full);
          font-size: var(--font-size-xs);
        }
        .type-name {
          color: var(--color-text-muted);
          text-transform: capitalize;
        }
        .type-count {
          font-weight: var(--font-weight-bold);
          color: var(--color-primary);
        }
        .sources-section {
          background-color: var(--color-bg-surface);
          border: 1px solid var(--color-border);
          border-radius: var(--radius-md);
          padding: var(--space-5);
          box-shadow: var(--shadow-sm);
        }
        .section-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: var(--space-4);
        }
        .source-count-label {
          font-size: var(--font-size-xs);
          color: var(--color-text-muted);
        }
        .table-wrapper {
          overflow-x: auto;
        }
        .sources-table {
          width: 100%;
          border-collapse: collapse;
          text-align: left;
        }
        .sources-table th {
          font-size: var(--font-size-xs);
          font-weight: var(--font-weight-semibold);
          color: var(--color-text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          padding: var(--space-3) var(--space-4);
          border-bottom: 1px solid var(--color-border);
          background-color: var(--color-bg-app);
        }
        .sources-table td {
          padding: var(--space-3) var(--space-4);
          border-bottom: 1px solid var(--color-border);
          font-size: var(--font-size-sm);
        }
        .sources-table tr:last-child td {
          border-bottom: none;
        }
        .sources-table tr:hover td {
          background-color: var(--color-bg-surface-hover);
        }
        .row-restricted td {
          background-color: #fdf2f8;
        }
        .confidential-tag {
          display: inline-block;
          margin-left: var(--space-2);
          font-size: 9px;
          font-weight: var(--font-weight-bold);
          color: var(--clearance-restricted-text);
          background: #fce7f3;
          padding: 1px 5px;
          border-radius: var(--radius-sm);
        }
        .type-badge {
          font-size: var(--font-size-xs);
          color: var(--color-text-muted);
          background-color: var(--color-bg-app);
          padding: 2px 6px;
          border-radius: var(--radius-sm);
          border: 1px solid var(--color-border);
        }
        .font-mono { font-family: var(--font-mono); }
        .font-medium { font-weight: var(--font-weight-medium); }
        .text-main { color: var(--color-text-main); }
        .text-muted { color: var(--color-text-muted); }
        .text-sm { font-size: var(--font-size-xs); }
        .empty-cell {
          text-align: center;
          padding: var(--space-8);
          color: var(--color-text-muted);
        }
      `}</style>
    </div>
  );
}

export default Overview;
