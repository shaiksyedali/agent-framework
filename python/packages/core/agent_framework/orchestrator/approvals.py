"""Approval handling utilities for orchestrated steps."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Awaitable, Optional, Protocol


class ApprovalType(enum.Enum):
    """Kinds of approvals that can pause orchestration."""

    PLAN = "plan"
    SQL = "sql"
    MCP = "mcp"
    CUSTOM = "custom"


@dataclass
class ApprovalRequest:
    """Request emitted when a step needs approval."""

    step_id: str
    step_name: str
    approval_type: ApprovalType
    summary: Optional[str] = None


@dataclass
class ApprovalDecision:
    """Decision returned by approval callbacks."""

    approved: bool
    reason: str | None = None

    @classmethod
    def allow(cls, reason: str | None = None) -> "ApprovalDecision":
        return cls(approved=True, reason=reason)

    @classmethod
    def deny(cls, reason: str | None = None) -> "ApprovalDecision":
        return cls(approved=False, reason=reason)


class ApprovalCallback(Protocol):
    """Protocol for callbacks that resolve approval requests."""

    def __call__(self, request: ApprovalRequest) -> Awaitable[ApprovalDecision] | ApprovalDecision:
        ...


def default_auto_approve(_: ApprovalRequest) -> ApprovalDecision:
    """Default approval callback that auto-approves all requests."""

    return ApprovalDecision.allow(reason="Auto-approved by default orchestrator policy")
