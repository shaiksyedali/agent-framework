export type SqlEngine = 'sqlite' | 'duckdb' | 'postgres';

export interface WorkflowStep {
  id: string;
  title: string;
  description: string;
  agent: 'planner' | 'sql' | 'rag' | 'reasoning' | 'responder' | 'custom';
  requiresApproval?: boolean;
}

export interface WorkflowDefinition {
  name: string;
  persona: string;
  goals: string;
  knowledge: KnowledgeSources;
  steps: WorkflowStep[];
  sqlEngine: SqlEngine;
}

export interface KnowledgeSources {
  documentsPath?: string;
  database?: {
    engine: SqlEngine;
    path?: string;
    connectionString?: string;
    approvalMode?: 'always_require' | 'never_require';
    allowWrites?: boolean;
  };
  mcpServer?: string;
  documentText?: string;
}

export interface ArtifactRecord {
  id: string;
  runId: string;
  kind: string;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface EventEnvelope {
  id: string;
  type:
    | 'plan'
    | 'sql'
    | 'rag'
    | 'reasoning'
    | 'response'
    | 'approval-request'
    | 'approval-decision'
    | 'status';
  message: string;
  detail?: Record<string, unknown>;
  timestamp: string;
}

export interface RunRecord {
  id: string;
  workflowName: string;
  startedAt: string;
  status: 'running' | 'awaiting-approval' | 'succeeded' | 'failed';
  engine: SqlEngine;
}
