// Azure Foundry Backend API Types

export interface DataSourceConfig {
  id?: string;
  name: string;
  type: 'file' | 'database' | 'mcp_server';
  path?: string;
  connection_string?: string;
  url?: string;
}

export interface AgentConfig {
  id?: string;
  name: string;
  role: string;
  instructions: string;
  model_name?: string;
  model_provider?: string;
  tools?: string[];
  data_sources?: string[];
  is_azure?: boolean;
  is_editable?: boolean;
}

export interface WorkflowStep {
  name: string;
  type: string;
  agent_id: string;
  input_template: string;
  output_key: string;
  requires_approval?: boolean;
  description?: string;
}

export interface StepOutput {
  step_name: string;
  result: any;
  metadata: Record<string, any>;
}

export interface WorkflowConfig {
  id?: string;
  name: string;
  description: string;
  user_intent: string;
  agents: AgentConfig[];
  data_sources: DataSourceConfig[];
  steps: WorkflowStep[];
  is_azure_workflow?: boolean;
}

export interface JobStatus {
  id: string;
  workflow_id: string;
  thread_id?: string;
  status: 'running' | 'completed' | 'failed' | 'waiting_for_user';
  current_step_index: number;
  logs: string[];
  context: Record<string, any>;
  step_outputs: Record<string, StepOutput>;
  error?: string;
  pending_tool_call?: any;
}

export interface ExecuteRequest {
  workflow_id: string;
  input_data: Record<string, any>;
}

export interface ResumeRequest {
  job_id: string;
  user_input: string;
  approved?: boolean;
}

export interface ChatRequest {
  job_id: string;
  message: string;
}

export interface PlanRequest {
  user_request: string;
  data_sources?: DataSourceConfig[];
}
