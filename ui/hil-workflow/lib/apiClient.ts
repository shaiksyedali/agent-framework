import type {
  WorkflowConfig,
  AgentConfig,
  JobStatus,
  ExecuteRequest,
  ResumeRequest,
  ChatRequest,
  PlanRequest,
  DataSourceConfig
} from './types';

const baseUrl = process.env.NEXT_PUBLIC_HIL_API_BASE || 'http://127.0.0.1:8000';

export const apiAvailable = Boolean(baseUrl);

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers
    }
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (payload as { detail?: string }).detail;
    throw new Error(detail ? `${res.status}: ${detail}` : `API request failed (${res.status})`);
  }
  return payload as T;
}

// ===== AGENTS =====

export async function listAgents(): Promise<AgentConfig[]> {
  return fetchJSON<AgentConfig[]>('/agents');
}

// ===== WORKFLOWS =====

export async function listWorkflows(): Promise<WorkflowConfig[]> {
  return fetchJSON<WorkflowConfig[]>('/workflows');
}

export async function getWorkflow(workflowId: string): Promise<WorkflowConfig> {
  return fetchJSON<WorkflowConfig>(`/workflows/${workflowId}`);
}

export async function createWorkflow(workflow: WorkflowConfig): Promise<WorkflowConfig> {
  return fetchJSON<WorkflowConfig>('/workflows', {
    method: 'POST',
    body: JSON.stringify(workflow)
  });
}

export async function deleteWorkflow(workflowId: string): Promise<{ message: string }> {
  return fetchJSON<{ message: string }>(`/workflows/${workflowId}`, {
    method: 'DELETE'
  });
}

// ===== EXECUTION =====

export async function executeWorkflow(request: ExecuteRequest): Promise<JobStatus> {
  return fetchJSON<JobStatus>('/execute', {
    method: 'POST',
    body: JSON.stringify(request)
  });
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  return fetchJSON<JobStatus>(`/jobs/${jobId}`);
}

export async function resumeJob(request: ResumeRequest): Promise<JobStatus> {
  return fetchJSON<JobStatus>('/resume', {
    method: 'POST',
    body: JSON.stringify(request)
  });
}

// ===== PLANNING =====

export async function createPlan(request: PlanRequest): Promise<WorkflowConfig> {
  return fetchJSON<WorkflowConfig>('/plan', {
    method: 'POST',
    body: JSON.stringify(request)
  });
}

// ===== CHAT =====

export async function chatWithJob(request: ChatRequest): Promise<{ response: string; context: any }> {
  return fetchJSON<{ response: string; context: any }>('/chat', {
    method: 'POST',
    body: JSON.stringify(request)
  });
}

// ===== FILE OPERATIONS =====

export async function listFiles(path: string = '.'): Promise<Array<{
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
}>> {
  return fetchJSON<Array<{
    name: string;
    path: string;
    is_dir: boolean;
    size: number;
  }>>(`/files?path=${encodeURIComponent(path)}`);
}

export async function uploadFile(file: File, path: string = '.'): Promise<{ message: string; path: string }> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${baseUrl}/upload?path=${encodeURIComponent(path)}`, {
    method: 'POST',
    body: formData
  });

  if (!res.ok) {
    throw new Error(`Upload failed (${res.status})`);
  }

  return res.json();
}

// ===== HEALTH =====

export async function healthCheck(): Promise<{ status: string; service: string }> {
  return fetchJSON<{ status: string; service: string }>('/health');
}
