'use client';

import type { RunRecord } from '../lib/types';

interface Props {
  runs: RunRecord[];
}

export default function RunHistory({ runs }: Props) {
  return (
    <div className="card">
      <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Recent runs</h2>
        <div className="tag">History</div>
      </div>
      <table className="table">
        <caption>Latest executions (mocked)</caption>
        <thead>
          <tr>
            <th>Workflow</th>
            <th>Engine</th>
            <th>Status</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(run => (
            <tr key={run.id}>
              <td>{run.workflowName}</td>
              <td>{run.engine}</td>
              <td>
                <span className={
                  run.status === 'succeeded'
                    ? 'badge-success'
                    : run.status === 'awaiting-approval'
                      ? 'badge-warning'
                      : 'badge-danger'
                }>
                  {run.status}
                </span>
              </td>
              <td>{new Date(run.startedAt).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
