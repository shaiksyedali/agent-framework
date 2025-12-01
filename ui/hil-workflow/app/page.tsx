'use client';

import { useMemo, useRef, useState } from 'react';
import ApprovalPanel from '../components/ApprovalPanel';
import EventStream from '../components/EventStream';
import ExecutionConsole from '../components/ExecutionConsole';
import RunHistory from '../components/RunHistory';
import WorkflowBuilder from '../components/WorkflowBuilder';
import { currentModeLabel, startRun, type RunHandle } from '../lib/runClient';
import type { EventEnvelope, RunRecord, WorkflowDefinition } from '../lib/types';

const defaultDefinition: WorkflowDefinition = {
  name: 'Fleet diagnostics assistant',
  persona: 'Proactive analyst that surfaces anomalies and corrective actions.',
  goals: 'Summarize fleet issues, highlight risky vehicles, propose next best actions.',
  knowledge: {},
  steps: [],
  sqlEngine: 'sqlite'
};

export default function Page() {
  const [definition, setDefinition] = useState<WorkflowDefinition>(defaultDefinition);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [pendingApproval, setPendingApproval] = useState<EventEnvelope | undefined>();
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const runHandle = useRef<MockRunHandle | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);

  const running = useMemo(() => runs.some(run => run.status === 'running' || run.status === 'awaiting-approval'), [runs]);

  const startRun = () => {
    if (unsubscribeRef.current) {
      unsubscribeRef.current();
    }

    const handle = startMockRun(definition);
    runHandle.current = handle;
    setEvents([]);
    setPendingApproval(undefined);
    setRuns(prev => [{ ...handle.run }, ...prev]);

    const unsubscribe = handle.subscribe(event => {
      setEvents(prev => [...prev, event]);

      if (event.type === 'approval-request') {
        setPendingApproval(event);
        setRuns(prevRuns =>
          prevRuns.map(run =>
            run.id === handle.run.id ? { ...run, status: 'awaiting-approval' } : run
          )
        );
      }

      if (event.type === 'approval-decision') {
        setPendingApproval(undefined);
        setRuns(prevRuns =>
          prevRuns.map(run => (run.id === handle.run.id ? { ...run, status: 'running' } : run))
        );
      }

      if (event.type === 'status' && event.detail?.status) {
        setRuns(prevRuns =>
          prevRuns.map(run =>
            run.id === handle.run.id ? { ...run, status: event.detail?.status as RunRecord['status'] } : run
          )
        );
      }
    });

    unsubscribeRef.current = unsubscribe;
  };

  const approve = () => {
    runHandle.current?.approve('Approved from UI');
  };

  const reject = () => {
    runHandle.current?.reject('Rejected from UI');
  };

  return (
    <main className="grid-shell">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <WorkflowBuilder definition={definition} onChange={setDefinition} onSubmit={startRun} busy={running} />
        <ApprovalPanel pending={pendingApproval} onApprove={approve} onReject={reject} />
        <RunHistory runs={runs} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <ExecutionConsole events={events} />
        <EventStream events={events} />
      </div>
    </main>
  );
}
