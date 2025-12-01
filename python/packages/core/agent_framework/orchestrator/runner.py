"""Runtime orchestration for step graphs with approval gating."""

from __future__ import annotations

import asyncio
import inspect
from typing import AsyncIterator

from .approvals import (
    ApprovalCallback,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalType,
    default_auto_approve,
)
from .context import OrchestrationContext
from .events import (
    ApprovalRequiredEvent,
    OrchestrationCompletedEvent,
    OrchestrationEvent,
    OrchestrationStartedEvent,
    OrchestrationStepCompletedEvent,
    OrchestrationStepFailedEvent,
    OrchestrationStepStartedEvent,
    PlanProposedEvent,
)
from .graph import StepDefinition, StepGraph


class OrchestrationError(Exception):
    """Base orchestration error."""


class ApprovalDeniedError(OrchestrationError):
    """Raised when an approval callback rejects a step."""

    def __init__(self, request: ApprovalRequest, decision: ApprovalDecision) -> None:
        super().__init__(f"Approval denied for step {request.step_id}: {decision.reason}")
        self.request = request
        self.decision = decision


async def _resolve_action(step: StepDefinition, context: OrchestrationContext):
    result = step.action(context)
    if inspect.isawaitable(result):
        return await result
    return result


def _snapshot_context(context: OrchestrationContext) -> dict:
    return {
        "workflow_id": context.workflow_id,
        "workflow_metadata": dict(context.workflow_metadata),
        "persona": dict(context.persona) if isinstance(context.persona, dict) else context.persona,
        "connectors": dict(context.connectors),
        "transient_artifacts": dict(context.transient_artifacts),
    }


class Orchestrator:
    """Executes a :class:`~agent_framework.orchestrator.graph.StepGraph` and streams events."""

    def __init__(self, approval_callback: ApprovalCallback | None = None) -> None:
        self._approval_callback = approval_callback or default_auto_approve

    async def run(
        self, graph: StepGraph, context: OrchestrationContext
    ) -> AsyncIterator[OrchestrationEvent]:
        graph.validate_acyclic()
        completed: set[str] = set()

        yield OrchestrationStartedEvent(context_snapshot=_snapshot_context(context))

        while len(completed) < len(graph):
            ready = graph.ready_steps(completed)
            if not ready:
                raise OrchestrationError(
                    "No executable steps found; the graph may contain unresolved dependencies"
                )
            for step in ready:
                async for event in self._run_step(step, context):
                    yield event
                completed.add(step.step_id)

        yield OrchestrationCompletedEvent(context_snapshot=_snapshot_context(context))

    async def _run_step(
        self, step: StepDefinition, context: OrchestrationContext
    ) -> AsyncIterator[OrchestrationEvent]:
        yield OrchestrationStepStartedEvent(
            step_id=step.step_id,
            step_name=step.name,
            context_snapshot=_snapshot_context(context),
        )

        plan_artifact = step.metadata.get("plan_artifact")
        if plan_artifact is not None:
            yield PlanProposedEvent(plan=plan_artifact, context_snapshot=_snapshot_context(context))

        if step.approval_type is not None:
            request = ApprovalRequest(
                step_id=step.step_id,
                step_name=step.name,
                approval_type=step.approval_type,
                summary=step.summary,
            )
            yield ApprovalRequiredEvent(
                request=request,
                context_snapshot=_snapshot_context(context),
            )
            decision = self._approval_callback(request)
            if inspect.isawaitable(decision):
                decision = await decision
            if not isinstance(decision, ApprovalDecision):
                raise OrchestrationError("Approval callback must return ApprovalDecision")
            if not decision.approved:
                raise ApprovalDeniedError(request, decision)

        try:
            result = await _resolve_action(step, context)
        except Exception as exc:  # pragma: no cover - exception path validated via events
            yield OrchestrationStepFailedEvent(
                step_id=step.step_id,
                step_name=step.name,
                error=str(exc),
                context_snapshot=_snapshot_context(context),
            )
            raise

        context.transient_artifacts[step.step_id] = result

        yield OrchestrationStepCompletedEvent(
            step_id=step.step_id,
            step_name=step.name,
            result=result,
            context_snapshot=_snapshot_context(context),
        )
