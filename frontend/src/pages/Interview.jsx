import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw, Send, SkipForward } from 'lucide-react';
import api from '../api/client';
import { EmptyState, Loading, ProjectSubnav, StatusBadge } from '../components/ui';
import { useAuth } from '../hooks/useAuth';
import { ProjectHeaderBar, useActiveProjectId } from './Reconstruction';

const PRIORITY_CLS = { high: 'bad', medium: 'warn', low: 'info' };

function QuestionCard({ q, onAnswered, onSkipped }) {
  const [answer, setAnswer] = useState(q.answer || '');
  const [skipping, setSkipping] = useState(false);
  const [skipReason, setSkipReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const saveAnswer = async (e) => {
    e.preventDefault();
    if (!answer.trim()) return;
    setBusy(true);
    setErr('');
    try {
      const updated = await api.answerQuestion(q.id, answer.trim());
      onAnswered(updated);
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  const submitSkip = async (e) => {
    e.preventDefault();
    if (!skipReason.trim()) return;
    setBusy(true);
    setErr('');
    try {
      const updated = await api.skipQuestion(q.id, skipReason.trim());
      setSkipping(false);
      setSkipReason('');
      onSkipped(updated);
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <span className={`badge ${PRIORITY_CLS[q.priority] || ''}`}>
            <span className="badge-dot" />
            {q.priority}
          </span>
          <span className="badge mono">{q.module}</span>
          <span className="badge">For: {q.target_label || 'unassigned'}</span>
          <StatusBadge status={q.status} />
          {q.claim_id && (
            <Link className="badge mono" to={`/projects/${q.project_id}/review?claim=${q.claim_id}`}>
              {q.claim_id}
            </Link>
          )}
          {q.contradiction_id && (
            <Link className="badge mono" to={`/projects/${q.project_id}/contradictions`}>
              {q.contradiction_id}
            </Link>
          )}
        </div>
        <span className="muted mono" style={{ fontSize: 11 }}>{q.text_source === 'llm' ? 'clarified' : 'template'}</span>
      </div>

      <p style={{ fontWeight: 500, marginBottom: 10 }}>{q.question}</p>

      {q.context && q.context.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Source context</div>
          {q.context.map((ctx, idx) => (
            <div key={`${ctx.claim_id}-${idx}`} className="chunk-box" style={{ marginTop: 4 }}>
              <div className="muted" style={{ fontSize: 11, marginBottom: 2 }}>
                <span className="mono">{ctx.source_id || 'source'}</span>
                {ctx.source_filename ? ` · ${ctx.source_filename}` : ''}
                {ctx.locator ? ` (${ctx.locator})` : ''}
              </div>
              {ctx.excerpt}
            </div>
          ))}
        </div>
      )}

      {err && <div className="alert error">{err}</div>}

      {q.status === 'answered' ? (
        <div className="evidence-answer">
          <div style={{ fontSize: 12, marginBottom: 4 }} className="muted">
            Interview answer, by {q.answered_by_name || 'team member'},{' '}
            {q.answered_at ? new Date(q.answered_at).toLocaleDateString() : ''}
          </div>
          <div>{q.answer}</div>
        </div>
      ) : q.status === 'skipped' ? (
        <div className="alert info" style={{ marginBottom: 0 }}>
          Skipped: {q.skip_reason}
        </div>
      ) : !q.can_answer ? (
        <p className="muted" style={{ marginBottom: 0, fontSize: 12 }}>
          Assigned to {q.target_label || 'unassigned'}. Only the team lead or the assigned person can answer this question.
        </p>
      ) : (
        <>
          <form onSubmit={saveAnswer}>
            <label htmlFor={`ans-${q.id}`}>Your answer (saved as new human-authored evidence)</label>
            <textarea
              id={`ans-${q.id}`}
              rows={2}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Record factual context, decision rationale, or actual status..."
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              <button className="btn sm primary" type="submit" disabled={busy || !answer.trim()}>
                <Send size={12} strokeWidth={1.5} />Save answer
              </button>
              <button
                className="btn sm"
                type="button"
                disabled={busy}
                onClick={() => setSkipping((v) => !v)}
              >
                <SkipForward size={12} strokeWidth={1.5} />Skip
              </button>
            </div>
          </form>

          {skipping && (
            <form onSubmit={submitSkip} style={{ marginTop: 10 }}>
              <label htmlFor={`skip-${q.id}`}>Reason for skipping (required)</label>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <input
                  id={`skip-${q.id}`}
                  value={skipReason}
                  onChange={(e) => setSkipReason(e.target.value)}
                  placeholder="Why is this question not applicable?"
                />
                <button className="btn sm" type="submit" disabled={busy || !skipReason.trim()}>
                  Confirm skip
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </div>
  );
}

export function ExitInterviewPage() {
  const { workspace } = useAuth();
  const isAdmin = workspace?.role === 'admin';
  const { projectId, projects, setSelectedId, hasRouteId } = useActiveProjectId();
  const [data, setData] = useState(null);
  const [groupBy, setGroupBy] = useState('module');
  const [selectedModule, setSelectedModule] = useState('');
  const [selectedPerson, setSelectedPerson] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [busyGen, setBusyGen] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(() => {
    if (!projectId) return;
    setErr('');
    api.interview(projectId, {
      module: selectedModule || undefined,
      person: selectedPerson || undefined,
      status: statusFilter || undefined,
    }).then(setData).catch((x) => {
      setData(null);
      setErr(x.message);
    });
  }, [projectId, selectedModule, selectedPerson, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const handleGenerate = async () => {
    if (!projectId) return;
    setBusyGen(true);
    setErr('');
    try {
      await api.generateInterview(projectId);
      load();
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusyGen(false);
    }
  };

  const progress = data?.progress || { total: 0, answered: 0, skipped: 0, open: 0 };
  const groups = groupBy === 'module' ? (data?.by_module || []) : (data?.by_person || []);

  return (
    <>
      <ProjectHeaderBar
        title="Exit interview"
        subtitle="Targeted questions generated from real knowledge gaps and contradictions. Answers become attributed evidence pending review."
        projectId={projectId}
        projects={projects}
        setSelectedId={setSelectedId}
        hasRouteId={hasRouteId}
        actions={isAdmin && projectId && (
          <button className="btn primary" type="button" disabled={busyGen} onClick={handleGenerate}>
            <RefreshCw size={14} strokeWidth={1.5} />
            {busyGen ? 'Generating...' : 'Generate questions'}
          </button>
        )}
      />
      <ProjectSubnav projectId={projectId} />

      {err && <div className="alert error">{err}</div>}

      {!projectId ? (
        <EmptyState title="No project selected">Create or select a project to run an exit interview.</EmptyState>
      ) : !data && !err ? (
        <Loading label="Loading exit interview" />
      ) : data && (
        <>
          <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <strong>Progress:</strong>{' '}
              <span className="mono">{progress.answered} / {progress.total}</span> answered
              {' · '}
              <span className="mono">{progress.open}</span> open
              {' · '}
              <span className="mono">{progress.skipped}</span> skipped
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <label htmlFor="flt-iv-status" style={{ marginBottom: 0 }}>Status</label>
              <select
                id="flt-iv-status"
                style={{ width: 'auto', minWidth: 140 }}
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="">All ({progress.total})</option>
                <option value="unanswered">Unanswered ({progress.open + progress.skipped})</option>
                <option value="answered">Answered ({progress.answered})</option>
                <option value="skipped">Skipped ({progress.skipped})</option>
              </select>
            </div>
          </div>

          {progress.total === 0 ? (
            <EmptyState title="No interview questions yet">
              Run reconstruction analysis on the project first, then click <strong>Generate questions</strong> to identify gaps.
            </EmptyState>
          ) : (
            <div className="split-rail">
              <aside className="rail-card" aria-label="Interview groups">
                <div className="tabs" style={{ marginBottom: 8 }}>
                  <button
                    type="button"
                    className={`tab ${groupBy === 'module' ? 'active' : ''}`}
                    onClick={() => { setGroupBy('module'); setSelectedPerson(''); }}
                  >
                    By module
                  </button>
                  <button
                    type="button"
                    className={`tab ${groupBy === 'person' ? 'active' : ''}`}
                    onClick={() => { setGroupBy('person'); setSelectedModule(''); }}
                  >
                    By person
                  </button>
                </div>

                <button
                  type="button"
                  className={`rail-item ${!selectedModule && !selectedPerson ? 'active' : ''}`}
                  onClick={() => { setSelectedModule(''); setSelectedPerson(''); }}
                >
                  <span>All</span>
                  <span className="mono">{progress.answered}/{progress.total}</span>
                </button>

                {groups.map((g) => {
                  const isActive = groupBy === 'module' ? selectedModule === g.name : selectedPerson === g.name;
                  return (
                    <button
                      key={g.name}
                      type="button"
                      className={`rail-item ${isActive ? 'active' : ''}`}
                      onClick={() => {
                        if (groupBy === 'module') {
                          setSelectedModule(g.name);
                          setSelectedPerson('');
                        } else {
                          setSelectedPerson(g.name);
                          setSelectedModule('');
                        }
                      }}
                    >
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{g.name}</span>
                      <span className="mono">{g.answered}/{g.total}</span>
                    </button>
                  );
                })}
              </aside>

              <div>
                {data.questions.length === 0 ? (
                  <EmptyState title="No questions match these filters">
                    Try clearing the module, person, or status filter.
                  </EmptyState>
                ) : (
                  data.questions.map((q) => (
                    <QuestionCard
                      key={q.id}
                      q={q}
                      onAnswered={() => load()}
                      onSkipped={() => load()}
                    />
                  ))
                )}
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}
