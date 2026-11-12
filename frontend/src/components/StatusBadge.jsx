import React from 'react';

export function StatusBadge({ status, type = 'status' }) {
  if (!status) return null;

  const normalized = String(status).toLowerCase();

  let className = 'badge';
  let label = status;

  if (type === 'clearance') {
    className += ` badge-clearance-${normalized}`;
    label = normalized.toUpperCase();
  } else if (type === 'synthetic') {
    className += ' badge-synthetic';
    label = 'SYNTHETIC';
  } else {
    className += ` badge-status-${normalized}`;
  }

  return (
    <span className={className}>
      {label}
      <style>{`
        .badge {
          display: inline-flex;
          align-items: center;
          padding: 2px 8px;
          border-radius: var(--radius-sm);
          font-size: var(--font-size-xs);
          font-weight: var(--font-weight-medium);
          text-transform: capitalize;
          border: 1px solid transparent;
        }

        .badge-synthetic {
          background-color: #f1f5f9;
          color: #475569;
          border-color: #cbd5e1;
          font-weight: var(--font-weight-bold);
          letter-spacing: 0.5px;
        }

        /* Clearance */
        .badge-clearance-public {
          background-color: var(--clearance-public-bg);
          color: var(--clearance-public-text);
          border-color: #bbf7d0;
        }
        .badge-clearance-team {
          background-color: var(--clearance-team-bg);
          color: var(--clearance-team-text);
          border-color: #bae6fd;
        }
        .badge-clearance-restricted {
          background-color: var(--clearance-restricted-bg);
          color: var(--clearance-restricted-text);
          border-color: #fbcfe8;
          font-weight: var(--font-weight-bold);
        }

        /* Verification Status */
        .badge-status-verified {
          background-color: var(--status-verified-bg);
          color: var(--status-verified-text);
          border-color: var(--status-verified-border);
        }
        .badge-status-inferred {
          background-color: var(--status-inferred-bg);
          color: var(--status-inferred-text);
          border-color: var(--status-inferred-border);
        }
        .badge-status-conflicting {
          background-color: var(--status-conflicting-bg);
          color: var(--status-conflicting-text);
          border-color: var(--status-conflicting-border);
        }
        .badge-status-missing, .badge-status-registered {
          background-color: var(--status-missing-bg);
          color: var(--status-missing-text);
          border-color: var(--status-missing-border);
        }
      `}</style>
    </span>
  );
}

export default StatusBadge;
