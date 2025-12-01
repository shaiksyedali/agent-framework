'use client';

import { useMemo } from 'react';
import type { ArtifactRecord, EventEnvelope, WorkflowDefinition } from '../lib/types';

interface Props {
  events: EventEnvelope[];
  artifacts: ArtifactRecord[];
  definition: WorkflowDefinition;
}

type StepSummary = { title?: string; description?: string };

function normalizeSteps(raw: unknown): StepSummary[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(item =>
    typeof item === 'object' && item
      ? { title: (item as { title?: string }).title, description: (item as { description?: string }).description }
      : { title: String(item) }
  );
}

export default function ExecutionConsole({ events, artifacts, definition }: Props) {
  const latestStatus = useMemo(() => {
    const statusEvents = events.filter(event => event.type === 'status');
    return statusEvents[statusEvents.length - 1];
  }, [events]);

  const approvals = events.filter(event => event.type === 'approval-decision');
  const approvalRequests = events.filter(event => event.type === 'approval-request');

  const planEvents = events.filter(event => event.type === 'plan');
  const latestPlan = planEvents[planEvents.length - 1];
  const previousPlan = planEvents[planEvents.length - 2];
  const latestSteps = normalizeSteps(latestPlan?.detail?.steps);
  const baselineSteps = normalizeSteps(definition.steps);
  const previousSteps = normalizeSteps(previousPlan?.detail?.steps);

  const planDiff = useMemo(() => {
    const added = latestSteps.filter(step => step.title && !baselineSteps.some(base => base.title === step.title));
    const removed = baselineSteps.filter(step => step.title && !latestSteps.some(plan => plan.title === step.title));
    const changed = previousSteps.filter(prev => prev.title && !latestSteps.some(plan => plan.title === prev.title));
    return { added, removed, changed };
  }, [baselineSteps, latestSteps, previousSteps]);

  const latestSql = artifacts.filter(a => a.kind === 'sql-preview').slice(-1)[0];
  const latestRag = artifacts.filter(a => a.kind === 'rag-snippets').slice(-1)[0];

  const sqlPayload = (latestSql?.payload ?? {}) as {
    sql?: string;
    rows?: unknown[];
    raw_rows?: unknown[];
  };
  const sqlRows = Array.isArray(sqlPayload.rows)
    ? (sqlPayload.rows as Array<Record<string, unknown>>)
    : Array.isArray(sqlPayload.raw_rows)
      ? (sqlPayload.raw_rows as Array<Record<string, unknown>>)
      : [];
  const sqlColumns = sqlRows.length > 0 ? Object.keys(sqlRows[0]) : [];

  const ragPayload = (latestRag?.payload ?? {}) as { snippets?: unknown; question?: string };
  const ragSnippets = Array.isArray(ragPayload.snippets)
    ? ragPayload.snippets
    : ragPayload.snippets && typeof ragPayload.snippets === 'object'
      ? Object.values(ragPayload.snippets as Record<string, unknown>)
      : ragPayload.snippets
        ? [ragPayload.snippets]
        : [];

  const stageStatus = [
    { label: 'Plan', done: planEvents.length > 0 },
    { label: 'SQL', done: events.some(event => event.type === 'sql') },
    { label: 'RAG', done: events.some(event => event.type === 'rag') },
    { label: 'Reasoning', done: events.some(event => event.type === 'reasoning') },
    { label: 'Response', done: events.some(event => event.type === 'response') }
  ];

  return (
    <div className="card">
      <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Execution console</h2>
        <div className="tag">SQL • RAG • Reasoning</div>
      </div>
      <div className="split" style={{ marginTop: '0.5rem' }}>
        <div>
          <div className="section-title">Latest status</div>
          <div style={{ marginTop: '0.35rem' }}>
            {latestStatus ? latestStatus.message : 'Waiting to start...'}
          </div>
        </div>
        <div>
          <div className="section-title">Approvals</div>
          <ul style={{ paddingLeft: '1rem', marginTop: '0.35rem', color: 'var(--muted)' }}>
            {approvals.length === 0 && <li>No approvals yet</li>}
            {approvals.map(event => (
              <li key={event.id}>
                {event.message} · {event.detail?.reason ?? ''}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="split" style={{ marginTop: '0.75rem' }}>
        <div>
          <div className="section-title">Stage progress</div>
          <ul style={{ paddingLeft: '1rem', marginTop: '0.35rem', color: 'var(--muted)' }}>
            {stageStatus.map(stage => (
              <li key={stage.label} style={{ color: stage.done ? 'var(--accent)' : 'var(--muted)' }}>
                {stage.done ? '✓' : '…'} {stage.label}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="section-title">Clarification prompts</div>
          <div style={{ marginTop: '0.35rem', color: 'var(--muted)' }}>
            {approvalRequests.length === 0 && 'No clarifications requested yet.'}
            {approvalRequests.length > 0 && (
              <div>
                <strong>{approvalRequests[approvalRequests.length - 1].message}</strong>
                {approvalRequests[approvalRequests.length - 1].detail ? (
                  <pre className="code" style={{ marginTop: '0.35rem' }}>
                    {JSON.stringify(approvalRequests[approvalRequests.length - 1].detail, null, 2)}
                  </pre>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{ marginTop: '0.75rem' }}>
        <div className="section-title">Planner insights</div>
        {planEvents.length === 0 && <p style={{ color: 'var(--muted)' }}>Waiting for planner to emit steps…</p>}
        {planEvents.length > 0 && (
          <div style={{ marginTop: '0.35rem' }}>
            <div className="tag">{latestSteps.length} steps proposed</div>
            {(planDiff.added.length > 0 || planDiff.removed.length > 0 || planDiff.changed.length > 0) && (
              <div className="code" style={{ marginTop: '0.35rem' }}>
                {planDiff.added.length > 0 && <div>Added: {planDiff.added.map(step => step.title).join(', ')}</div>}
                {planDiff.removed.length > 0 && <div>Removed: {planDiff.removed.map(step => step.title).join(', ')}</div>}
                {planDiff.changed.length > 0 && <div>Changed: {planDiff.changed.map(step => step.title).join(', ')}</div>}
              </div>
            )}
            <pre className="code" style={{ marginTop: '0.35rem' }}>
              {JSON.stringify(latestSteps, null, 2)}
            </pre>
          </div>
        )}
      </div>

      <div className="split" style={{ marginTop: '0.75rem' }}>
        <div>
          <div className="section-title">SQL preview</div>
          {!latestSql && <p style={{ color: 'var(--muted)' }}>Awaiting SQL execution…</p>}
          {latestSql && (
            <div className="code" style={{ marginTop: '0.35rem' }}>
              <div style={{ marginBottom: '0.35rem' }}>{sqlPayload.sql ?? 'SQL emitted from agent'}</div>
              {sqlColumns.length > 0 ? (
                <table className="table">
                  <thead>
                    <tr>
                      {sqlColumns.map(col => (
                        <th key={col}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sqlRows.slice(0, 5).map((row, idx) => (
                      <tr key={idx}>
                        {sqlColumns.map(col => (
                          <td key={col}>{String(row[col] ?? '')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ color: 'var(--muted)' }}>No rows returned yet.</div>
              )}
            </div>
          )}
        </div>
        <div>
          <div className="section-title">RAG evidence</div>
          {!latestRag && <p style={{ color: 'var(--muted)' }}>No retrievals yet.</p>}
          {latestRag && (
            <div className="code" style={{ marginTop: '0.35rem' }}>
              <div style={{ marginBottom: '0.35rem' }}>
                {ragPayload.question ? <strong>Q: {ragPayload.question}</strong> : 'Retrieved snippets'}
              </div>
              {ragSnippets.length === 0 && <div style={{ color: 'var(--muted)' }}>No snippets provided.</div>}
              {ragSnippets.length > 0 && (
                <ul style={{ paddingLeft: '1rem', margin: 0 }}>
                  {ragSnippets.slice(0, 4).map((snippet, idx) => (
                    <li key={idx}>{typeof snippet === 'string' ? snippet : JSON.stringify(snippet)}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
