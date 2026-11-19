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

  // Readiness Verification ("Check my understanding")
  const [assessment, setAssessment] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [activeAttempt, setActiveAttempt] = useState(null);
  const [qIdx, setQIdx] = useState(0);
  const [answersMap, setAnswersMap] = useState({});
  const [submittedAttempt, setSubmittedAttempt] = useState(null);

  const loadDetail = useCallback(async (hid) => {
    const [d, ob, ass, rdy] = await Promise.all([
      api.handoverDetail(hid),
      api.getOnboarding(hid).catch(() => []),
      api.getAssessment(hid).catch(() => null),
      api.handoverReadiness(hid).catch(() => null),
    ]);
    setDetail(d);
    setAssessment(ass);
    setReadiness(rdy);
    setActiveAttempt(null);
    setSubmittedAttempt(null);
    setAnswersMap({});
    setQIdx(0);
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

  async function onStartAssessment() {
    if (!detail) return;
    setBusy(true);
    setError('');
    try {
      const att = await api.startAssessmentAttempt(detail.id);
      setActiveAttempt(att);
      setSubmittedAttempt(null);
      setAnswersMap({});
      setQIdx(0);
    } catch (err) {
      setError(err.message || 'Could not start assessment.');
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitAssessment() {
    if (!activeAttempt) return;
    setBusy(true);
    setError('');
    try {
      const payload = (activeAttempt.questions || []).map((q) => ({
        question_id: q.id,
        answer_text: answersMap[q.id] || '',
      }));
      const res = await api.submitAssessmentAttempt(activeAttempt.id, payload);
      setSubmittedAttempt(res);
      setActiveAttempt(null);
      setReadiness(await api.handoverReadiness(detail.id).catch(() => null));
    } catch (err) {
      setError(err.message || 'Could not submit assessment.');
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

      {detail.newer_approved_version && (
        <div className="alert info" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <div>
            <strong>Newer approved handover available (v{detail.newer_approved_version.version_number})</strong>
            <span className="muted"> — You are viewing v{detail.version_number || 1}.</span>
          </div>
          <button
            className="btn sm primary"
            type="button"
            onClick={() => {
              const nid = detail.newer_approved_version.id;
              setSelectedId(nid);
              loadDetail(nid);
            }}
          >
            Open v{detail.newer_approved_version.version_number}
          </button>
        </div>
      )}

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

      {/* Check my understanding (Readiness Verification) */}
      <div className="panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <div>
            <h2 style={{ margin: 0 }}>Check my understanding</h2>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Scenario questions from approved handover claims to verify readiness across modules.
            </p>
          </div>
          {!activeAttempt && (assessment?.question_count || 0) > 0 && (
            <button className="btn sm primary" type="button" onClick={onStartAssessment} disabled={busy}>
              {(readiness?.participants?.[0]?.attempt_count || 0) > 0 ? 'Retake assessment' : 'Start baseline check'}
            </button>
          )}
        </div>

        {(assessment?.question_count || 0) === 0 ? (
          <p className="muted" style={{ marginTop: 10, marginBottom: 0 }}>
            No assessment has been published for this handover yet. Ask your team lead to generate it in Handover Center.
          </p>
        ) : activeAttempt ? (
          (() => {
            const qs = activeAttempt.questions || [];
            const cur = qs[qIdx];
            if (!cur) return null;
            return (
              <div style={{ marginTop: 14, display: 'grid', gap: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                  <span className="mono" style={{ fontSize: 12 }}>
                    Question {qIdx + 1} of {qs.length} · Module: {cur.module} ({activeAttempt.attempt_kind})
                  </span>
                  <span className="badge">{cur.question_type === 'mcq' ? 'Multiple choice' : 'Short answer (heuristic)'}</span>
                </div>
                <div style={{ height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.round(((qIdx + 1) / qs.length) * 100)}%`, height: '100%', background: 'var(--accent)' }} />
                </div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>{cur.prompt}</div>

                {cur.question_type === 'mcq' && Array.isArray(cur.options) ? (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {cur.options.map((opt) => (
                      <label
                        key={opt}
                        style={{
                          display: 'flex', gap: 8, alignItems: 'center', padding: 10,
                          border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer',
                        }}
                      >
                        <input
                          type="radio"
                          name={`q-${cur.id}`}
                          checked={answersMap[cur.id] === opt}
                          onChange={() => setAnswersMap((p) => ({ ...p, [cur.id]: opt }))}
                          style={{ width: 'auto' }}
                        />
                        <span>{opt}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div>
                    <textarea
                      className="input"
                      rows={3}
                      placeholder="Write what you would check first..."
                      value={answersMap[cur.id] || ''}
                      onChange={(e) => setAnswersMap((p) => ({ ...p, [cur.id]: e.target.value }))}
                    />
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      Note: Short-answer scores are heuristic based on key-term coverage and may be flagged for reviewer check.
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                  <button className="btn sm" type="button" disabled={qIdx === 0} onClick={() => setQIdx((i) => Math.max(0, i - 1))}>
                    Previous
                  </button>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {qIdx < qs.length - 1 ? (
                      <button className="btn sm primary" type="button" onClick={() => setQIdx((i) => Math.min(qs.length - 1, i + 1))}>
                        Next
                      </button>
                    ) : (
                      <button className="btn sm primary" type="button" disabled={busy} onClick={onSubmitAssessment}>
                        {busy ? 'Scoring...' : 'Submit assessment'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })()
        ) : (
          (() => {
            const p = readiness?.participants?.[0];
            const shown = submittedAttempt || p?.attempts?.[p.attempts.length - 1];
            if (!shown) {
              return (
                <p className="muted" style={{ marginTop: 10, marginBottom: 0 }}>
                  {assessment.question_count} scenario question(s) ready. Click "Start baseline check" to test your readiness.
                </p>
              );
            }
            return (
              <div style={{ marginTop: 14, display: 'grid', gap: 12 }}>
                <div className="grid4">
                  <div className="stat">
                    <div className="muted">Latest score</div>
                    <div className="stat-num">{Math.round(shown.overall_score || 0)}%</div>
                  </div>
                  <div className="stat">
                    <div className="muted">Correct</div>
                    <div className="stat-num">{shown.correct_count}/{shown.total_questions}</div>
                  </div>
                  {p && (
                    <>
                      <div className="stat">
                        <div className="muted">Baseline</div>
                        <div className="stat-num">{Math.round(p.baseline_score || 0)}%</div>
                      </div>
                      <div className="stat">
                        <div className="muted">Before / after delta</div>
                        <div className="stat-num">{p.delta_overall >= 0 ? `+${p.delta_overall}` : p.delta_overall}%</div>
                      </div>
                    </>
                  )}
                </div>

                {(shown.area_scores || []).length > 0 && (
                  <div style={{ overflowX: 'auto' }}>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Area / Module</th>
                          <th>Score</th>
                          <th>Correct</th>
                          <th>Weight</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shown.area_scores.map((ar) => (
                          <tr key={ar.id}>
                            <td className="mono">{ar.module}</td>
                            <td>{ar.score}%</td>
                            <td className="mono">{ar.correct_count}/{ar.question_count}</td>
                            <td className="mono">{ar.weight}x</td>
                            <td>
                              <span className={`badge ${ar.status === 'ready' ? 'ok' : 'warn'}`}>
                                {ar.status === 'ready' ? 'Ready' : 'Needs more handover'}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {(shown.answers || []).length > 0 && (
                  <div style={{ display: 'grid', gap: 8 }}>
                    <h3 style={{ margin: '4px 0' }}>Explanations &amp; cited claims</h3>
                    {shown.answers.map((ans) => (
                      <div key={ans.question_id} style={{ border: '1px solid var(--border)', padding: 10, borderRadius: 4 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                          <strong>{ans.prompt}</strong>
                          <span className={`badge ${ans.is_correct ? 'ok' : 'bad'}`}>
                            {ans.is_correct ? 'Correct' : `Score ${Math.round((ans.score || 0) * 100)}%`}
                          </span>
                        </div>
                        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                          Your answer: {ans.answer_text || '(blank)'}
                        </div>
                        <div style={{ fontSize: 13, marginTop: 6 }}>{ans.explanation}</div>
                        <div className="mono muted" style={{ fontSize: 11, marginTop: 4 }}>
                          Claims: {(ans.source_claim_ids || []).join(', ')}
                          {ans.needs_reviewer_check ? ' · Heuristic score flagged for reviewer check' : ''}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })()
        )}
      </div>

      {/* Secondary: Ask project knowledge */}
      <AskKnowledgePanel projectId={detail.project_id} compact />
    </div>
  );
}
