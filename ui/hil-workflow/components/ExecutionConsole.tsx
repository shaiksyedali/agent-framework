'use client';

import { useMemo } from 'react';
import type { EventEnvelope } from '../lib/types';

interface Props {
  events: EventEnvelope[];
}

export default function ExecutionConsole({ events }: Props) {
  const latestStatus = useMemo(() => {
    const statusEvents = events.filter(event => event.type === 'status');
    return statusEvents[statusEvents.length - 1];
  }, [events]);

  const approvals = events.filter(event => event.type === 'approval-decision');

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
                {event.message} · {event.detail?.message ?? ''}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div style={{ marginTop: '0.75rem' }}>
        <div className="section-title">Artifacts (mocked)</div>
        <div className="code" style={{ marginTop: '0.35rem' }}>
          {JSON.stringify(
            {
              sql: 'SELECT vin, fault_code, COUNT(*) FROM events GROUP BY vin, fault_code',
              citations: ['doc://battery/soh', 'doc://warranty/policy'],
              plan: 'Planner → SQL → RAG → Reasoning → Response'
            },
            null,
            2
          )}
        </div>
      </div>
    </div>
  );
}
