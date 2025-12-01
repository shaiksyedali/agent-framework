'use client';

import type { EventEnvelope } from '../lib/types';

interface Props {
  events: EventEnvelope[];
}

function formatTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString(undefined, { hour12: false });
}

export default function EventStream({ events }: Props) {
  return (
    <div className="card">
      <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Streaming events</h2>
        <div className="tag">Live orchestration feed</div>
      </div>
      <div className="event-log">
        {events.length === 0 && <div style={{ color: 'var(--muted)' }}>No events yet.</div>}
        {events.map(event => (
          <div key={event.id} style={{ marginBottom: '0.35rem' }}>
            <span style={{ color: 'var(--muted)' }}>{formatTime(event.timestamp)}</span> ·{' '}
            <strong>{event.type.toUpperCase()}</strong> — {event.message}
          </div>
        ))}
      </div>
    </div>
  );
}
