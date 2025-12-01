import { v4 as uuidv4 } from 'uuid';
import type { EventEnvelope, RunRecord, WorkflowDefinition } from './types';

export interface MockRunHandle {
  run: RunRecord;
  subscribe: (listener: (event: EventEnvelope) => void) => () => void;
  approve: (message?: string) => void;
  reject: (message?: string) => void;
}

const steps: Array<Pick<EventEnvelope, 'type' | 'message'>> = [
  { type: 'plan', message: 'Planner drafted a step graph based on persona and data access.' },
  { type: 'sql', message: 'SQL agent generated query with schema-aware prompt and few-shot examples.' },
  { type: 'rag', message: 'RAG agent retrieved 3 cited passages from knowledge base.' },
  { type: 'reasoning', message: 'Reasoning agent fused SQL rows + RAG snippets and validated math.' },
  { type: 'response', message: 'Responder formatted answer with citations and suggested follow-ups.' }
];

export function startMockRun(definition: WorkflowDefinition): MockRunHandle {
  const runId = uuidv4();
  const run: RunRecord = {
    id: runId,
    workflowName: definition.name,
    startedAt: new Date().toISOString(),
    status: 'running',
    engine: definition.sqlEngine
  };

  let approvalPending = false;
  const listeners = new Set<(event: EventEnvelope) => void>();

  const emit = (event: EventEnvelope) => {
    listeners.forEach(listener => listener(event));
  };

  const sendApprovalRequest = () => {
    approvalPending = true;
    emit({
      id: uuidv4(),
      type: 'approval-request',
      message: 'Approve plan and SQL execution?',
      timestamp: new Date().toISOString(),
      detail: {
        steps: definition.steps,
        engine: definition.sqlEngine
      }
    });
  };

  const advance = (index: number) => {
    if (index === 1) {
      sendApprovalRequest();
      return;
    }

    if (index < steps.length) {
      const step = steps[index];
      emit({
        id: uuidv4(),
        type: step.type,
        message: step.message,
        timestamp: new Date().toISOString()
      });
      setTimeout(() => advance(index + 1), 900);
    } else {
      emit({
        id: uuidv4(),
        type: 'status',
        message: 'Run completed successfully.',
        timestamp: new Date().toISOString(),
        detail: { status: 'succeeded' }
      });
    }
  };

  setTimeout(() => advance(0), 500);

  const subscribe = (listener: (event: EventEnvelope) => void) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  };

  const approvalDecision = (approved: boolean, message?: string) => {
    approvalPending = false;
    emit({
      id: uuidv4(),
      type: 'approval-decision',
      message: approved ? 'Approved' : 'Rejected',
      timestamp: new Date().toISOString(),
      detail: { message }
    });
    if (approved) {
      setTimeout(() => advance(2), 500);
    } else {
      emit({
        id: uuidv4(),
        type: 'status',
        message: 'Run stopped after rejection.',
        timestamp: new Date().toISOString(),
        detail: { status: 'failed' }
      });
    }
  };

  return {
    run,
    subscribe,
    approve: (message?: string) => {
      if (approvalPending) {
        approvalDecision(true, message);
      }
    },
    reject: (message?: string) => {
      if (approvalPending) {
        approvalDecision(false, message);
      }
    }
  };
}
