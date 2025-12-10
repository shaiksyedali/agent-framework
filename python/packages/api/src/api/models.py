"""
Pydantic models for Azure Agentic Workflow API.
Compatible with existing frontend WorkflowConfig interface.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """MCP Server configuration (legacy, kept for compatibility)"""
    name: str
    command: str
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None


class AgentConfig(BaseModel):
    """Agent configuration"""
    id: Optional[str] = None
    name: str
    role: str
    instructions: str
    model_provider: Optional[str] = "azure"
    model_name: str = "gpt-4o"
    tools: List[str] = Field(default_factory=list)
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    data_sources: List[str] = Field(default_factory=list)
    is_azure: Optional[bool] = False  # Flag for pre-created Azure agents
    is_editable: Optional[bool] = True


class TeamConfig(BaseModel):
    """Team configuration"""
    id: Optional[str] = None
    name: str
    leader_agent_id: Optional[str] = None
    member_agent_ids: List[str]
    instructions: Optional[str] = None
    model_provider: Optional[str] = "azure"
    model_name: Optional[str] = "gpt-4o"


class DataSourceConfig(BaseModel):
    """Data source configuration"""
    id: Optional[str] = None
    name: str
    type: str  # "file", "database", "mcp_server"
    path: Optional[str] = None
    connection_string: Optional[str] = None
    url: Optional[str] = None


class StepConfig(BaseModel):
    """Workflow step configuration"""
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    type: str  # "agent_call", "team_call", "user_confirmation", "tool_call"
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    input_template: str = "{input}"
    output_key: str = "result"
    requires_approval: bool = False


class WorkflowConfig(BaseModel):
    """Complete workflow configuration"""
    id: Optional[str] = None
    name: str
    description: str
    user_intent: str
    agents: List[AgentConfig] = Field(default_factory=list)
    teams: List[TeamConfig] = Field(default_factory=list)
    data_sources: List[DataSourceConfig] = Field(default_factory=list)
    steps: List[StepConfig] = Field(default_factory=list)
    is_azure_workflow: Optional[bool] = True  # Flag for Azure Foundry workflows


class ExecuteRequest(BaseModel):
    """Request to execute a workflow"""
    workflow_id: str
    input_data: Dict[str, Any] = Field(default_factory=dict)


class ResumeRequest(BaseModel):
    """Request to resume a paused job"""
    job_id: str
    user_input: str = ""
    approved: Optional[bool] = None


class ChatRequest(BaseModel):
    """Request to chat with job results"""
    job_id: str
    message: str


class Visualization(BaseModel):
    """Visualization data"""
    title: str
    type: str  # "bar", "pie", "line", "area"
    data: List[Dict[str, Any]]
    x_key: Optional[str] = None
    y_key: Optional[str] = None


class StepOutput(BaseModel):
    """Rich output format for a step"""
    thought_process: Optional[str] = None
    content: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    insights: List[str] = Field(default_factory=list)
    visualizations: List[Visualization] = Field(default_factory=list)
    next_step_suggestion: Optional[str] = None


class JobStatus(BaseModel):
    """Job execution status"""
    id: str
    workflow_id: str
    thread_id: Optional[str] = None
    status: str  # "running", "completed", "failed", "waiting_for_user"
    current_step_index: int = 0
    logs: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    step_outputs: Dict[str, StepOutput] = Field(default_factory=dict)
    pending_tool_call: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PlanRequest(BaseModel):
    """Request to create a workflow plan from user intent"""
    user_request: str
    data_sources: List[Dict[str, Any]] = Field(default_factory=list)  # Optional data sources hint
