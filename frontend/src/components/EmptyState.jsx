import React from 'react';

export function EmptyState({ title, phase = 'Phase 2+', description }) {
  return (
    <div className="empty-state-container">
      <div className="empty-state-badge">{phase} Roadmap</div>
      <h3 className="empty-state-title">{title}</h3>
      <p className="empty-state-desc">
        {description || 'This feature is scheduled for implementation in a later phase. Phase 1 provides the underlying database models and API architecture.'}
      </p>

      <style>{`
        .empty-state-container {
          background-color: var(--color-bg-surface);
          border: 1px dashed var(--color-border-dark);
          border-radius: var(--radius-lg);
          padding: var(--space-12) var(--space-6);
          text-align: center;
          margin: var(--space-6) 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
        }
        .empty-state-badge {
          display: inline-block;
          background-color: var(--color-primary-subtle);
          color: var(--color-primary);
          padding: var(--space-1) var(--space-3);
          border-radius: var(--radius-full);
          font-size: var(--font-size-xs);
          font-weight: var(--font-weight-semibold);
          margin-bottom: var(--space-3);
          text-transform: uppercase;
        }
        .empty-state-title {
          font-size: var(--font-size-xl);
          font-weight: var(--font-weight-semibold);
          color: var(--color-text-main);
          margin-bottom: var(--space-2);
        }
        .empty-state-desc {
          font-size: var(--font-size-sm);
          color: var(--color-text-muted);
          max-width: 480px;
          line-height: 1.6;
        }
      `}</style>
    </div>
  );
}

export default EmptyState;
