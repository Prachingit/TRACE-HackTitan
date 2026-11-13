import React, { useCallback, useEffect, useState } from 'react';
import api from '../api/client';
import { EmptyState, Loading, StatusBadge, VerificationBadge } from '../components/ui';
import { AskKnowledgePanel } from '../components/AskKnowledgePanel';

const KNOWLEDGE_TABS = [
  { key: 'decisions_rationale', label: 'Decisions & rationale' },
  { key: 'completed_work', label: 'Completed work' },
  { key: 'work_in_progress', label: 'Work in progress' },
  { key: 'pending_tasks', label: 'Pending tasks' },
  { key: 'bugs_blockers', label: 'Blockers' },
  { key: 'dependencies_ownership', label: 'Ownership & dependencies' },
  { key: 'responsibilities_contributions', label: 'Contributions' },
];

export function IncomingPortalPage() {
  const [handovers, setHandovers] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState(null);
  const [onboarding, setOnboarding] = useState({});
  const [activeTab, setActiveTab] = useState('decisions_rationale');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const loadDetail = useCallback(async (hid) => {
    const [d, ob] = await Promise.all([
      api.handoverDetail(hid),
      api.getOnboarding(hid).catch(() => []),
    ]);
    setDetail(d);
    const map = {};
    for (const row of ob || []) {
      map[row.item_key] = Boolean(row.completed);
    }
    setOnboarding(map);
  }, []);

  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const list = await api.handovers();
        if (cancel) return;
        setHandovers(list);
        if (list.length > 0) {
          setSelectedId(list[0].id);
          await loadDetail(list[0].id);
        }
      } catch (err) {
        if (!cancel) setError(err.message || 'Failed to load shared handovers.');
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => { cancel = true; };
  }, [loadDetail]);

  async function onToggleStep(itemKey) {
    if (!detail) return;
    const next = !onboarding[itemKey];
    setOnboarding((prev) => ({ ...prev, [itemKey]: next }));
    try {
      await api.updateOnboarding(detail.id, itemKey, next);
    } catch (err) {
      setOnboarding((prev) => ({ ...prev, [itemKey]: !next }));
      setError(err.message || 'Could not save checklist progress.');
    }
  }

  async function onAcknowledge() {
    if (!detail) return;
    setBusy(true);
    setError('');
    try {
      await api.acknowledgeHandover(detail.id);
      await loadDetail(detail.id);
    } catch (err) {
      setError(err.message || 'Could not acknowledge handover.');
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading label="Loading Incoming Member Portal" />;

  if (handovers.length === 0 || !detail) {
    return (
      <div>
        <div className="page-head">
          <div>
            <h1>Incoming Member Portal</h1>
            <p className="muted">Your approved project handover and ranked onboarding plan.</p>
          </div>
        </div>
        <EmptyState title="No handover shared with you yet">
          Once your team lead approves and shares a project handover with you, your continuation plan, key decisions, and source-verified guidance will appear here.
        </EmptyState>
      </div>
    );
  }

  const sectionsByKey = {};
  for (const s of detail.sections || []) {
    sectionsByKey[s.section_key] = s;
  }
  const overviewSec = sectionsByKey.overview;
  const planSec = sectionsByKey.recommended_next_steps;
  const planItems = (planSec?.body_json?.items || planSec?.content?.items || []);
  const tabSec = sectionsByKey[activeTab];
  const tabBody = tabSec?.body_json || tabSec?.content || {};
  const tabItems = tabBody.items || [];
  const completedCount = planItems.filter((p) => onboarding[p.id]).length;

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="page-head">
        <div>
          <h1>{detail.title}</h1>
          <p className="muted">
            Approved handover · Readiness {Math.round(detail.readiness_score || 0)}/100
            {detail.departing_user_name ? ` · From ${detail.departing_user_name}` : ''}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {handovers.length > 1 && (
            <select
              className="input"
              value={selectedId}
              onChange={(e) => {
                setSelectedId(e.target.value);
                loadDetail(e.target.value);
              }}
            >
              {handovers.map((h) => (
                <option key={h.id} value={h.id}>{h.title}</option>
              ))}
            </select>
          )}
          <StatusBadge status={detail.status} />
          <a className="btn sm" href={api.handoverPdfUrl(detail.id)} target="_blank" rel="noreferrer">
            Export PDF
          </a>
          {detail.status === 'shared' && (
            <button className="btn sm primary" onClick={onAcknowledge} disabled={busy}>
              {busy ? 'Saving...' : 'Acknowledge handover'}
            </button>
          )}
        </div>
      </div>

      {error && <div className="panel error">{error}</div>}

      {/* Hero: Where should I start? */}
      <div className="panel" style={{ borderLeft: '3px solid var(--accent)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <div>
            <h2 style={{ margin: 0 }}>Where should I start?</h2>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Ranked continuation plan ordered by blockers, downstream impact, and dependencies.
            </p>
          </div>
          <div className="mono" style={{ fontSize: 13 }}>
            {completedCount}/{planItems.length} completed
          </div>
        </div>

        {planItems.length === 0 ? (
          <p className="muted" style={{ marginTop: 12 }}>No pending continuation items in the approved handover.</p>
        ) : (
          <div style={{ overflowX: 'auto', marginTop: 12 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Done</th>
                  <th>Priority</th>
                  <th>Task &amp; Rationale</th>
                  <th>Relevant files</th>
                  <th>Verification</th>
                </tr>
              </thead>
              <tbody>
                {planItems.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={Boolean(onboarding[item.id])}
                        onChange={() => onToggleStep(item.id)}
                        aria-label={`Mark ${item.title} completed`}
                      />
                    </td>
                    <td className="mono">#{item.priority}</td>
                    <td>
                      <div style={{ fontWeight: 500 }}>{item.title}</div>
                      <div className="muted" style={{ fontSize: 12 }}>{item.why_it_matters}</div>
                      {Array.isArray(item.dependencies) && item.dependencies.length > 0 && (
                        <div className="muted" style={{ fontSize: 11 }}>
                          Depends on: {item.dependencies.join(', ')}
                        </div>
                      )}
                    </td>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {(item.relevant_files || []).join(', ') || '—'}
                    </td>
                    <td>
                      <VerificationBadge status={item.verification_status} />
                      <div className="mono muted" style={{ fontSize: 11, marginTop: 2 }}>
                        {(item.claim_ids || []).join(', ')}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Handover Summary */}
      {overviewSec && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Handover summary</h3>
          <p style={{ marginBottom: 0 }}>{overviewSec.content_md || overviewSec.body_json?.summary}</p>
        </div>
      )}

      {/* Knowledge Exploration Tabs */}
      <div className="panel">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          {KNOWLEDGE_TABS.map((t) => (
            <button
              key={t.key}
              className={`btn sm ${activeTab === t.key ? 'primary' : ''}`}
              onClick={() => setActiveTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tabSec ? (
          <div>
            <p className="muted" style={{ marginTop: 0 }}>{tabSec.content_md || tabBody.summary}</p>
            {tabItems.length === 0 ? (
              <p className="muted">No approved items recorded in this category.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Module</th>
                    <th>Verification</th>
                    <th>Claims &amp; Sources</th>
                  </tr>
                </thead>
                <tbody>
                  {tabItems.map((it, idx) => (
                    <tr key={it.claim_id || idx}>
                      <td>
                        <div style={{ fontWeight: 500 }}>{it.title || it.statement}</div>
                        {it.rationale && <div className="muted" style={{ fontSize: 12 }}>Rationale: {it.rationale}</div>}
                      </td>
                      <td>{it.module || '—'}</td>
                      <td><VerificationBadge status={it.verification_status} /></td>
                      <td className="mono" style={{ fontSize: 12 }}>
                        {(it.claim_ids || [it.claim_id]).filter(Boolean).join(', ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ) : (
          <p className="muted">This section is not included in your approved handover.</p>
        )}
      </div>

      {/* Secondary: Ask project knowledge */}
      <AskKnowledgePanel projectId={detail.project_id} compact />
    </div>
  );
}
