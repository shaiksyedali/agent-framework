import { startApiRun, apiAvailable } from './apiClient';
import { startMockRun } from './mockClient';
import type { EventEnvelope, RunRecord, WorkflowDefinition } from './types';

export interface RunHandle {
  run: RunRecord;
  subscribe: (cb: (event: EventEnvelope) => void) => () => void;
  approve: (reason?: string) => Promise<void> | void;
  reject: (reason?: string) => Promise<void> | void;
  stop?: () => void;
}

export async function startRun(definition: WorkflowDefinition): Promise<RunHandle> {
  if (apiAvailable) {
    try {
      return await startApiRun(definition);
    } catch (err) {
      console.error('Falling back to mock run after API error', err);
    }
  }
  return startMockRun(definition);
}

export function currentModeLabel() {
  return apiAvailable ? 'Backend API' : 'Mock in-browser run';
}
