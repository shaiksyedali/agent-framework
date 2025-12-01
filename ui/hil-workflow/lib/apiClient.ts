import type { ArtifactRecord, EventEnvelope, KnowledgeSources, RunRecord, WorkflowDefinition } from './types';
import type { RunHandle } from './runClient';

const baseUrl = process.env.NEXT_PUBLIC_HIL_API_BASE;

export const apiAvailable = Boolean(baseUrl);

type ProgressCallback = (status: string) => void;

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
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (payload as { detail?: string }).detail;
    throw new Error(detail ? `${res.status}: ${detail}` : `API request failed (${res.status})`);
  }
  return payload as T;
}

async function ingestFromForm(workflowId: string, knowledge: KnowledgeSources, onProgress?: ProgressCallback) {
  if (!knowledge.documentText?.trim()) {
    return { ingested: 0 };
  }
  onProgress?.('Ingesting attached knowledge');
  return postJSON<{ ingested: number }>(`/knowledge`, {
    workflowId,
    documents: [
      {
        text: knowledge.documentText.trim(),
        metadata: {
          source: knowledge.documentsPath || 'inline',
          ingestedAt: new Date().toISOString()
        }
      }
    ]
  });
}

export async function startApiRun(
  definition: WorkflowDefinition,
  onProgress?: ProgressCallback
): Promise<RunHandle> {
  if (!baseUrl) {
    throw new Error('API base URL not configured');
  }

  onProgress?.('Creating workflow');
  const workflowRes = await postJSON<{ id: string }>(`/workflows`, definition);
  await ingestFromForm(workflowRes.id, definition.knowledge, onProgress);
  onProgress?.('Starting run');
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
    workflowId: workflowRes.id,
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

export async function fetchApiArtifacts(runId: string): Promise<ArtifactRecord[]> {
  if (!baseUrl) return [];
  const res = await fetch(`${baseUrl}/runs/${runId}/artifacts`);
  if (!res.ok) {
    throw new Error(`Failed to fetch artifacts (${res.status})`);
  }
  const body = (await res.json()) as {
    items: Array<{ id: string; run_id?: string; runId?: string; kind: string; payload: unknown; created_at: string }>;
  };
  return body.items.map(item => ({
    id: item.id,
    runId: item.runId ?? item.run_id ?? runId,
    kind: item.kind,
    payload: (item.payload as Record<string, unknown>) ?? {},
    createdAt: item.created_at
  }));
}

export async function ingestKnowledge(workflowId: string, documents: Array<{ id?: string; text: string; metadata?: object }>) {
  if (!baseUrl) return { ingested: 0 };
  return postJSON<{ ingested: number }>(`/knowledge`, { workflowId, documents });
}
