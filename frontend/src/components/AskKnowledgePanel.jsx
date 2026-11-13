import React, { useState } from 'react';
import api from '../api/client';

export function AskKnowledgePanel({ projectId, viewAs = null, compact = true }) {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  async function onSubmit(e) {
    e.preventDefault();
    if (!projectId || !question.trim()) return;
    setLoading(true);
    setError('');
    try {
      const filters = viewAs ? { view_as: viewAs } : {};
      const res = await api.askProject(projectId, question.trim(), filters);
      setResult(res);
    } catch (err) {
      setError(err.message || 'Unable to query project knowledge.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel" style={{ padding: compact ? 16 : 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Ask project knowledge</h3>
        <span className="muted" style={{ fontSize: 12 }}>Secondary · Clearance-filtered</span>
      </div>
      <form onSubmit={onSubmit} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input
          className="input"
          style={{ flex: '1 1 220px' }}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about decisions, tasks, blockers, or modules..."
          disabled={!projectId || loading}
        />
        <button className="btn sm" type="submit" disabled={!projectId || !question.trim() || loading}>
          {loading ? 'Searching...' : 'Ask'}
        </button>
      </form>
      {error && <p className="error" style={{ marginTop: 8, marginBottom: 0 }}>{error}</p>}
      {result && (
        <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{result.answer}</div>
          {Array.isArray(result.citations) && result.citations.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {result.citations.map((c, idx) => (
                <span key={idx} className="badge" title={c.excerpt || ''}>
                  <span className="mono">{c.claim_id || c.chunk_id}</span>
                  {c.source_name ? ` · ${c.source_name}` : ''}
                  {c.locator ? ` (${c.locator})` : ''}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
