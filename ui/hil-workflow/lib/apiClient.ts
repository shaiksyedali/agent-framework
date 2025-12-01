import type { EventEnvelope, RunRecord, WorkflowDefinition } from './types';
import type { RunHandle } from './runClient';

const baseUrl = process.env.NEXT_PUBLIC_HIL_API_BASE;

export const apiAvailable = Boolean(baseUrl);

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  if (!baseUrl) {
    throw new Error('API base URL not configured');
  }
  const res = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    throw new Error(`API request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export async function startApiRun(definition: WorkflowDefinition): Promise<RunHandle> {
  if (!baseUrl) {
    throw new Error('API base URL not configured');
  }

  const workflowRes = await postJSON<{ id: string }>(`/workflows`, definition);
  const run = await postJSON<RunRecord>(`/runs`, { workflowId: workflowRes.id });

  let eventSource: EventSource | null = null;

  const subscribe = (onEvent: (event: EventEnvelope) => void) => {
    eventSource = new EventSource(`${baseUrl}/runs/${run.id}/events`);
    eventSource.onmessage = evt => {
      try {
        const parsed = JSON.parse(evt.data) as EventEnvelope;
        onEvent(parsed);
      } catch (err) {
        console.error('Failed to parse event', err);
      }
    };
    eventSource.onerror = err => {
      console.error('EventSource error', err);
    };

    return () => {
      eventSource?.close();
    };
  };

  const approve = async (reason?: string) => {
    await postJSON(`/runs/${run.id}/approve`, { reason });
  };

  const reject = async (reason?: string) => {
    await postJSON(`/runs/${run.id}/reject`, { reason });
  };

  return {
    run,
    subscribe,
    approve,
    reject,
    stop: () => eventSource?.close()
  };
}

export async function fetchApiRuns(): Promise<RunRecord[]> {
  if (!baseUrl) {
    return [];
  }
  const res = await fetch(`${baseUrl}/runs`);
  if (!res.ok) {
    throw new Error(`Failed to fetch runs (${res.status})`);
  }
  const body = (await res.json()) as { items: RunRecord[] };
  return body.items;
}

export async function fetchApiArtifacts(runId: string) {
  if (!baseUrl) return { items: [] };
  const res = await fetch(`${baseUrl}/runs/${runId}/artifacts`);
  if (!res.ok) {
    throw new Error(`Failed to fetch artifacts (${res.status})`);
  }
  return (await res.json()) as { items: unknown[] };
}

export async function ingestKnowledge(workflowId: string, documents: Array<{ id?: string; text: string; metadata?: object }>) {
  if (!baseUrl) return { ingested: 0 };
  return postJSON<{ ingested: number }>(`/knowledge`, { workflowId, documents });
}
