import React from 'react';

export function Loading({ message = 'Loading TRACE workspace data...' }) {
  return (
    <div className="loading-container">
      <div className="spinner"></div>
      <span className="loading-message">{message}</span>

      <style>{`
        .loading-container {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: var(--space-8);
          gap: var(--space-3);
        }
        .spinner {
          width: 24px;
          height: 24px;
          border: 2px solid var(--color-border);
          border-top-color: var(--color-primary);
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        .loading-message {
          font-size: var(--font-size-sm);
          color: var(--color-text-muted);
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

export default Loading;
