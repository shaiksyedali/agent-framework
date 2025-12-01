import { fetchApiRuns, startApiRun, apiAvailable } from './apiClient';
import type { EventEnvelope, RunRecord, WorkflowDefinition } from './types';

export interface RunHandle {
  run: RunRecord;
  subscribe: (cb: (event: EventEnvelope) => void) => () => void;
  approve: (reason?: string) => Promise<void> | void;
  reject: (reason?: string) => Promise<void> | void;
  stop?: () => void;
  workflowId?: string;
}

export async function startRun(
  definition: WorkflowDefinition,
  opts?: { onProgress?: (status: string) => void }
): Promise<RunHandle> {
  if (!apiAvailable) {
    throw new Error('Backend API is not configured. Set NEXT_PUBLIC_HIL_API_BASE.');
  }
  return startApiRun(definition, opts?.onProgress);
}

export async function loadRuns(): Promise<RunRecord[]> {
  try {
    return await fetchApiRuns();
  } catch (err) {
    console.error('Failed to load runs from API, returning empty history', err);
    return [];
  }
}

export function currentModeLabel() {
  return apiAvailable ? 'Backend API' : 'Backend unavailable';
}
