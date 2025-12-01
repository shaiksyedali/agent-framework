'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import ApprovalPanel from '../components/ApprovalPanel';
import EventStream from '../components/EventStream';
import ExecutionConsole from '../components/ExecutionConsole';
import RunHistory from '../components/RunHistory';
import WorkflowBuilder from '../components/WorkflowBuilder';
import { fetchApiArtifacts } from '../lib/apiClient';
import { currentModeLabel, loadRuns, startRun, type RunHandle } from '../lib/runClient';
import type { ArtifactRecord, EventEnvelope, RunRecord, WorkflowDefinition } from '../lib/types';

const defaultDefinition: WorkflowDefinition = {
  name: 'Fleet diagnostics assistant',
  persona: 'Proactive analyst that surfaces anomalies and corrective actions.',
  goals: 'Summarize fleet issues, highlight risky vehicles, propose next best actions.',
  knowledge: {
    database: { engine: 'sqlite', approvalMode: 'always_require', allowWrites: false }
  },
  steps: [],
  sqlEngine: 'sqlite'
};

export default function Page() {
  const [definition, setDefinition] = useState<WorkflowDefinition>(defaultDefinition);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [pendingApproval, setPendingApproval] = useState<EventEnvelope | undefined>();
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const runHandle = useRef<RunHandle | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);

  useEffect(() => {
    loadRuns()
      .then(history => setRuns(history))
      .catch(err => {
        console.error('Failed to load run history', err);
        setError('Backend API unavailable. Configure NEXT_PUBLIC_HIL_API_BASE.');
      });
  }, []);

  const running = useMemo(
    () => runs.some(run => run.status === 'running' || run.status === 'awaiting-approval'),
    [runs]
  );

  const refreshArtifacts = async (runId: string) => {
    try {
      const records = await fetchApiArtifacts(runId);
      setArtifacts(records);
    } catch (err) {
      console.error('Failed to load artifacts', err);
    }
  };

  const startRunFromDefinition = async () => {
    if (launching) return;
    setLaunching(true);
    setError(null);
    setProgress('Validating workflow and starting backend run');

    try {
      unsubscribeRef.current?.();
      const handle = await startRun(definition, {
        onProgress: status => setProgress(status)
      });
      runHandle.current = handle;
      setEvents([]);
      setPendingApproval(undefined);
      setArtifacts([]);
      setRuns(prev => [{ ...handle.run }, ...prev]);

      const unsubscribe = handle.subscribe(event => {
        setEvents(prev => [...prev, event]);
        void refreshArtifacts(handle.run.id);

        if (event.type === 'approval-request') {
          setPendingApproval(event);
          setRuns(prevRuns =>
            prevRuns.map(run => (run.id === handle.run.id ? { ...run, status: 'awaiting-approval' } : run))
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
              run.id === handle.run.id
                ? { ...run, status: event.detail?.status as RunRecord['status'] }
                : run
            )
          );
          if (['succeeded', 'failed'].includes(String(event.detail.status))) {
            setProgress(null);
          }
        }
      });

      unsubscribeRef.current = unsubscribe;
      setProgress('Streaming live events…');
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : 'Failed to start run. Check backend availability or definition.';
      setError(message);
    } finally {
      setLaunching(false);
    }
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
        <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div className="tag">{currentModeLabel()}</div>
            <h1 style={{ margin: '0.35rem 0 0 0' }}>Human-in-the-loop workflow runner</h1>
            <p className="muted" style={{ marginTop: '0.25rem' }}>
              Configure planner/SQL/RAG/reasoning agents, then stream execution with approvals.
            </p>
          </div>
        </div>
        <WorkflowBuilder
          definition={definition}
          onChange={setDefinition}
          onSubmit={startRunFromDefinition}
          busy={running || launching}
        />
        {progress ? <div className="card">{progress}</div> : null}
        {error ? <div className="card error">{error}</div> : null}
        <ApprovalPanel pending={pendingApproval} onApprove={approve} onReject={reject} />
        <RunHistory runs={runs} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <ExecutionConsole events={events} artifacts={artifacts} definition={definition} />
        <EventStream events={events} />
      </div>
    </main>
  );
}
