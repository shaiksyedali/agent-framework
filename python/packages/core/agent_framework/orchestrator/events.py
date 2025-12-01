"""Event definitions for orchestrator streaming."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .approvals import ApprovalRequest, ApprovalDecision

if TYPE_CHECKING:
    from agent_framework.agents.planner import PlanArtifact
    from agent_framework.agents.sql import SQLExecutionResult


@dataclass
class OrchestrationEvent:
    """Base class for orchestrator events."""

    context_snapshot: dict[str, Any]


@dataclass
class OrchestrationStartedEvent(OrchestrationEvent):
    pass


@dataclass
class OrchestrationCompletedEvent(OrchestrationEvent):
    pass


@dataclass
class OrchestrationStepStartedEvent(OrchestrationEvent):
    step_id: str
    step_name: str


@dataclass
class OrchestrationStepCompletedEvent(OrchestrationEvent):
    step_id: str
    step_name: str
    result: Any


@dataclass
class OrchestrationStepFailedEvent(OrchestrationEvent):
    step_id: str
    step_name: str
    error: str


@dataclass
class ApprovalEvent(OrchestrationEvent):
    request: ApprovalRequest
    decision: ApprovalDecision | None = None


@dataclass
class ApprovalRequiredEvent(ApprovalEvent):
    pass


@dataclass
class PlanProposedEvent(OrchestrationEvent):
    """Emitted when a planner has produced a plan to review."""

    plan: "PlanArtifact"


@dataclass
class SQLExecutionEvent(OrchestrationEvent):
    """Stream details of SQL execution attempts."""

    step_id: str
    step_name: str
    sql: str | None
    rows: list[dict[str, Any]] | None = None
    raw_rows: list[dict[str, Any]] | None = None
    error: str | None = None
