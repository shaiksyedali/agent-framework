"""Event definitions for orchestrator streaming."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .approvals import ApprovalRequest, ApprovalDecision


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
