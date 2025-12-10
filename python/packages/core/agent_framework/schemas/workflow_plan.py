"""
Data models for workflow planning and execution.

This module defines the core data structures used throughout the multiagent
workflow system, including workflow inputs, plans, execution events, and feedback.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class WorkflowInput:
    """User inputs for workflow planning.

    Attributes:
        name: Workflow name
        description: Workflow description
        user_prompt: The user's natural language request
        workflow_steps: High-level step descriptions provided by user
        data_sources: Dictionary mapping source names to connection objects
            (e.g., {"database": SQLConnector, "vector_store": VectorStore})
    """
    name: str
    description: str
    user_prompt: str
    workflow_steps: List[str]
    data_sources: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowStep:
    """Planned workflow step with execution metadata.

    Attributes:
        step_id: Unique identifier for this step
        step_name: Human-readable step name
        agent_type: Type of agent to execute this step
            (e.g., "structured_data", "rag", "custom")
        description: Detailed description of what this step does
        inputs: List of step_ids this step depends on
        requires_approval: Whether this step requires user approval before execution
        estimated_outputs: Description of expected outputs from this step
    """
    step_id: str
    step_name: str
    agent_type: str
    description: str
    inputs: List[str] = field(default_factory=list)
    requires_approval: bool = False
    estimated_outputs: str = ""


@dataclass
class WorkflowPlan:
    """Complete workflow plan with both human and machine-readable representations.

    Attributes:
        workflow_id: Unique identifier for this workflow instance
        name: Workflow name
        description: Workflow description
        steps: List of WorkflowStep objects defining the execution plan
        data_flow: Dictionary mapping step_ids to their dependent step_ids
        human_readable_plan: Markdown-formatted plan for user review
        metadata: Additional metadata (timestamps, version, etc.)
    """
    workflow_id: str
    name: str
    description: str
    steps: List[WorkflowStep]
    data_flow: Dict[str, List[str]] = field(default_factory=dict)
    human_readable_plan: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Generate workflow_id if not provided."""
        if not self.workflow_id:
            self.workflow_id = f"wf-{uuid4().hex[:8]}"


@dataclass
class SupervisorEvent:
    """Event emitted by the Supervisor Agent during workflow orchestration.

    Attributes:
        type: Event type (e.g., "started", "analysis", "planning", "executing", "completed")
        message: Human-readable event message
        data: Optional structured data associated with this event
        timestamp: ISO 8601 timestamp of when event occurred
    """
    type: str
    message: str = ""
    data: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ExecutionEvent:
    """Event emitted during workflow execution.

    Attributes:
        type: Event type (e.g., "step_started", "step_completed", "step_failed",
            "approval_required")
        step_id: ID of the step that triggered this event
        step_name: Name of the step that triggered this event
        output: Formatted output data from the step
        approval_request: Optional approval request if type is "approval_required"
        error: Optional error message if type is "step_failed"
        timestamp: ISO 8601 timestamp of when event occurred
    """
    type: str
    step_id: Optional[str] = None
    step_name: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    approval_request: Optional[Any] = None  # ApprovalRequest from orchestrator.approvals
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UserFeedback:
    """User feedback after step execution.

    Attributes:
        action: Action to take ("proceed", "rerun", "abort")
        message: Optional feedback message from user (used for "rerun" with instructions)
    """
    action: str  # "proceed", "rerun", "abort"
    message: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate action is one of the allowed values."""
        allowed_actions = {"proceed", "rerun", "abort"}
        if self.action not in allowed_actions:
            raise ValueError(
                f"Invalid action '{self.action}'. Must be one of: {allowed_actions}"
            )


@dataclass
class StepExecutionResult:
    """Result of executing a workflow step.

    Attributes:
        step_id: ID of the executed step
        step_name: Name of the executed step
        success: Whether the step executed successfully
        output: Output data from the step
        error: Error message if execution failed
        execution_time_ms: Time taken to execute the step in milliseconds
        metadata: Additional metadata about the execution
    """
    step_id: str
    step_name: str
    success: bool
    output: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowExecutionSummary:
    """Summary of a complete workflow execution.

    Attributes:
        workflow_id: ID of the executed workflow
        workflow_name: Name of the workflow
        status: Final status ("completed", "failed", "aborted")
        step_results: List of results from each executed step
        total_execution_time_ms: Total time for workflow execution
        start_time: ISO 8601 timestamp when workflow started
        end_time: ISO 8601 timestamp when workflow ended
        metadata: Additional execution metadata
    """
    workflow_id: str
    workflow_name: str
    status: str  # "completed", "failed", "aborted"
    step_results: List[StepExecutionResult] = field(default_factory=list)
    total_execution_time_ms: Optional[float] = None
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
