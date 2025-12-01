'use client';

import type { EventEnvelope } from '../lib/types';

interface Props {
  pending?: EventEnvelope;
  onApprove: (note?: string) => void;
  onReject: (note?: string) => void;
}

export default function ApprovalPanel({ pending, onApprove, onReject }: Props) {
  if (!pending) {
    return (
      <div className="card">
        <h2>Approvals</h2>
        <div style={{ color: 'var(--muted)' }}>No approvals required right now.</div>
      </div>
    );
  }

  let detailPreview: string | undefined;
  if (pending.detail?.steps) {
    detailPreview = JSON.stringify(pending.detail.steps, null, 2);
  }

  return (
    <div className="card">
      <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Approval needed</h2>
        <div className="tag badge-warning">Awaiting decision</div>
      </div>
      <p style={{ color: 'var(--muted)' }}>{pending.message}</p>
      {pending.detail && (
        <div className="code" style={{ marginTop: '0.35rem' }}>
          <div style={{ marginBottom: '0.35rem', color: 'var(--muted)' }}>Clarify before continuing:</div>
          <pre className="code" style={{ margin: 0 }}>{JSON.stringify(pending.detail, null, 2)}</pre>
        </div>
      )}
      {detailPreview && <pre className="code">{detailPreview}</pre>}
      <div className="flex-row" style={{ marginTop: '0.75rem' }}>
        <button className="button primary" onClick={() => onApprove('Looks good')}>
          Approve
        </button>
        <button className="button danger" onClick={() => onReject('Please revise plan')}>
          Reject
        </button>
      </div>
    </div>
  );
}
