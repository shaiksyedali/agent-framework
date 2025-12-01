"""Approval handling utilities for orchestrated steps."""

from __future__ import annotations

import enum
import inspect
from dataclasses import dataclass, field
from typing import Awaitable, Optional, Protocol

from agent_framework._logging import get_logger
logger = get_logger(__name__)


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
    policy_tags: set[str] = field(default_factory=set)


@dataclass
class ApprovalDecision:
    """Decision returned by approval callbacks."""

    approved: bool
    reason: str | None = None
    actor_id: str = "system"

    @classmethod
    def allow(cls, reason: str | None = None, *, actor_id: str = "system") -> "ApprovalDecision":
        return cls(approved=True, reason=reason, actor_id=actor_id)

    @classmethod
    def deny(cls, reason: str | None = None, *, actor_id: str = "system") -> "ApprovalDecision":
        return cls(approved=False, reason=reason, actor_id=actor_id)


class ApprovalCallback(Protocol):
    """Protocol for callbacks that resolve approval requests."""

    def __call__(self, request: ApprovalRequest) -> Awaitable[ApprovalDecision] | ApprovalDecision:
        ...


def default_auto_approve(_: ApprovalRequest) -> ApprovalDecision:
    """Default approval callback that auto-approves all requests."""

    return ApprovalDecision.allow(reason="Auto-approved by default orchestrator policy")


@dataclass
class ApprovalAuditRecord:
    """Captured decision used for audit logging."""

    request: ApprovalRequest
    decision: ApprovalDecision


class ApprovalPolicy:
    """Policy wrapper that audits approval decisions and enforces actor attribution."""

    def __init__(
        self,
        *,
        enforced_tags: set[str] | None = None,
    ) -> None:
        self.enforced_tags = enforced_tags or {"ddl_dml", "mcp_action"}
        self._audit_log: list[ApprovalAuditRecord] = []

    @property
    def audit_log(self) -> list[ApprovalAuditRecord]:
        return list(self._audit_log)

    async def evaluate(self, request: ApprovalRequest, callback: ApprovalCallback) -> ApprovalDecision:
        decision = callback(request)
        if inspect.isawaitable(decision):
            decision = await decision
        if not isinstance(decision, ApprovalDecision):  # pragma: no cover - defensive
            raise TypeError("Approval callback must return ApprovalDecision")

        actor_id = decision.actor_id or "unknown"
        if request.policy_tags.intersection(self.enforced_tags) and actor_id == "unknown":
            actor_id = "policy-enforced"
            decision.actor_id = actor_id

        self._audit_log.append(ApprovalAuditRecord(request=request, decision=decision))
        logger.info(
            "Approval decision",
            extra={
                "step_id": request.step_id,
                "step_name": request.step_name,
                "approval_type": request.approval_type.value,
                "actor_id": actor_id,
                "approved": decision.approved,
            },
        )
        return decision
