import React from 'react';

export function StatCard({ title, value, subtext, badge }) {
  return (
    <div className="stat-card">
      <div className="stat-header">
        <span className="stat-title">{title}</span>
        {badge && <span className="stat-badge">{badge}</span>}
      </div>
      <div className="stat-value">{value}</div>
      {subtext && <div className="stat-subtext">{subtext}</div>}

      <style>{`
        .stat-card {
          background-color: var(--color-bg-surface);
          border: 1px solid var(--color-border);
          border-radius: var(--radius-md);
          padding: var(--space-4);
          display: flex;
          flex-direction: column;
          gap: var(--space-1);
          box-shadow: var(--shadow-sm);
        }
        .stat-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .stat-title {
          font-size: var(--font-size-xs);
          font-weight: var(--font-weight-medium);
          color: var(--color-text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .stat-value {
          font-size: var(--font-size-2xl);
          font-weight: var(--font-weight-bold);
          color: var(--color-text-main);
        }
        .stat-subtext {
          font-size: var(--font-size-xs);
          color: var(--color-text-muted);
        }
      `}</style>
    </div>
  );
}

export default StatCard;
