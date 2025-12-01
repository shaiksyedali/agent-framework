"""Runtime orchestration for step graphs with approval gating."""

from __future__ import annotations

import asyncio
import inspect
from typing import AsyncIterator

from agent_framework.agents.sql import SQLExecutionResult

from .approvals import (
    ApprovalCallback,
    ApprovalDecision,
    ApprovalPolicy,
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
    SQLExecutionEvent,
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
        "workflow_metadata": _redact_sensitive_fields(dict(context.workflow_metadata)),
        "persona": _redact_sensitive_fields(dict(context.persona))
        if isinstance(context.persona, dict)
        else context.persona,
        "connectors": {name: connector.__class__.__name__ for name, connector in context.connectors.items()},
        "transient_artifacts": _redact_sensitive_fields(dict(context.transient_artifacts)),
    }


def _redact_sensitive_fields(value: object) -> object:
    sensitive_keys = {"token", "secret", "key", "password", "connection_string"}
    if isinstance(value, dict):
        return {
            k: "<redacted>" if k.lower() in sensitive_keys else _redact_sensitive_fields(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_fields(v) for v in value]
    return value


class Orchestrator:
    """Executes a :class:`~agent_framework.orchestrator.graph.StepGraph` and streams events."""

    def __init__(
        self,
        approval_callback: ApprovalCallback | None = None,
        approval_policy: ApprovalPolicy | None = None,
    ) -> None:
        self._approval_callback = approval_callback or default_auto_approve
        self._approval_policy = approval_policy or ApprovalPolicy()

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
                policy_tags=self._derive_policy_tags(step),
            )
            yield ApprovalRequiredEvent(
                request=request,
                context_snapshot=_snapshot_context(context),
            )
            decision = await self._approval_policy.evaluate(request, self._approval_callback)
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

        if isinstance(result, SQLExecutionResult):
            for attempt in result.attempts:
                yield SQLExecutionEvent(
                    step_id=step.step_id,
                    step_name=step.name,
                    sql=attempt.sql,
                    rows=attempt.rows,
                    raw_rows=attempt.raw_rows,
                    error=attempt.error,
                    context_snapshot=_snapshot_context(context),
                )

        context.transient_artifacts[step.step_id] = result

        yield OrchestrationStepCompletedEvent(
            step_id=step.step_id,
            step_name=step.name,
            result=result,
            context_snapshot=_snapshot_context(context),
        )

    @staticmethod
    def _derive_policy_tags(step: StepDefinition) -> set[str]:
        tags: set[str] = set()
        if step.approval_type == ApprovalType.SQL:
            tags.add("ddl_dml")
        if step.approval_type == ApprovalType.MCP:
            tags.add("mcp_action")
        if step.approval_type == ApprovalType.CUSTOM:
            tags.add("custom")
        return tags
