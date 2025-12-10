import axios from 'axios';

const api = axios.create({
    baseURL: 'http://127.0.0.1:8000', // Adjust if backend port differs
});

export interface MCPServerConfig {
    name: string;
    command: string;
    args?: string[];
    env?: Record<string, string>;
    url?: string;
}

export interface TeamConfig {
    id?: string;
    name: string;
    leader_agent_id?: string | null;
    member_agent_ids: string[];
    instructions?: string;
    model_provider?: string;
    model_name?: string;
}

// NOTE: API payloads are loosely typed from the backend; keep broad typing to avoid runtime failures.
export interface WorkflowConfig {
    id?: string;
    name: string;
    description: string;
    user_intent: string;
    agents: unknown[];
    teams?: TeamConfig[];
    data_sources: unknown[];
    steps: unknown[];
}

export interface Visualization {
    title: string;
    type: "bar" | "pie" | "line" | "area";
    data: any[];
    x_key?: string;
    y_key?: string;
}

export interface StepOutput {
    thought_process: string;
    content: string;
    metrics: Record<string, string | number>;
    insights: string[];
    visualizations: Visualization[];
    next_step_suggestion?: string;
}

export interface JobStatus {
    id: string;
    workflow_id: string;
    status: string;
    current_step_index: number;
    context: any;
    logs: string[];
    step_outputs?: Record<string, StepOutput>; // Keyed by step name
}

export const getWorkflows = async () => {
    const response = await api.get<WorkflowConfig[]>('/workflows');
    return response.data;
};

export const getWorkflow = async (id: string) => {
    const response = await api.get<WorkflowConfig>(`/workflows/${id}`);
    return response.data;
};

export const createWorkflow = async (workflow: WorkflowConfig) => {
    const response = await api.post<WorkflowConfig>('/workflows', workflow);
    return response.data;
};

export const createPlan = async (userRequest: string) => {
    const response = await api.post<WorkflowConfig>('/plan', { user_request: userRequest });
    return response.data;
};

export const executeWorkflow = async (workflowId: string, inputData: any) => {
    const response = await api.post<JobStatus>('/execute', { workflow_id: workflowId, input_data: inputData });
    return response.data;
};

export const getJob = async (jobId: string) => {
    const response = await api.get<JobStatus>(`/jobs/${jobId}`);
    return response.data;
};

export const resumeJob = async (jobId: string, userInput: string) => {
    const response = await api.post<JobStatus>('/resume', { job_id: jobId, user_input: userInput });
    return response.data;
};

export const chatWithJob = async (jobId: string, message: string) => {
    const response = await api.post("/chat", { job_id: jobId, message });
    return response.data;
};

export const deleteWorkflow = async (id: string) => {
    const response = await api.delete(`/workflows/${id}`);
    return response.data;
};

export const listFiles = async (path: string = ".") => {
    const response = await api.get(`/files`, { params: { path } });
    return response.data;
};

export const uploadFile = async (file: File, path: string = ".") => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post("/upload", formData, {
        params: { path },
        headers: {
            "Content-Type": "multipart/form-data",
        },
    });
    return response.data;
};
