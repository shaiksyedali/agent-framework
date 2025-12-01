"""Runtime orchestration for step graphs with approval gating."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import AsyncIterator

from agent_framework.agents.sql import SQLExecutionResult
from agent_framework.observability import get_meter, get_tracer

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


logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)
meter = get_meter(__name__)

step_counter = meter.create_counter(
    name="agent_steps_total",
    description="Count of orchestrated steps processed",
)
failure_counter = meter.create_counter(
    name="agent_failures_total",
    description="Count of orchestrated steps that surfaced failures",
)
approval_counter = meter.create_counter(
    name="agent_approvals_total",
    description="Count of approvals evaluated for orchestrated steps",
)
sql_attempt_counter = meter.create_counter(
    name="agent_sql_attempts_total",
    description="Count of SQL execution attempts emitted from orchestrator steps",
)


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

        with tracer.start_as_current_span(
            "orchestration.run",
            attributes={
                "workflow.id": context.workflow_id,
                "workflow.step_count": len(graph),
            },
        ):
            logger.info(
                "orchestration.start",
                extra={"event_name": "orchestration_start", "workflow_id": context.workflow_id},
            )

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
            logger.info(
                "orchestration.completed",
                extra={
                    "event_name": "orchestration_completed",
                    "workflow_id": context.workflow_id,
                    "steps_completed": len(completed),
                },
            )

    async def _run_step(
        self, step: StepDefinition, context: OrchestrationContext
    ) -> AsyncIterator[OrchestrationEvent]:
        with tracer.start_as_current_span(
            "orchestration.step",
            attributes={"step.id": step.step_id, "step.name": step.name, "step.approval": str(step.approval_type)},
        ) as span:
            step_counter.add(1, {"step_name": step.name, "step_id": step.step_id})
            yield OrchestrationStepStartedEvent(
                step_id=step.step_id,
                step_name=step.name,
                context_snapshot=_snapshot_context(context),
            )
            logger.info(
                "orchestration.step_start",
                extra={
                    "event_name": "step_start",
                    "step_id": step.step_id,
                    "step_name": step.name,
                    "approval_type": str(step.approval_type),
                },
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
                approval_counter.add(1, {"approval_type": step.approval_type.value})
                yield ApprovalRequiredEvent(
                    request=request,
                    context_snapshot=_snapshot_context(context),
                )
                logger.info(
                    "orchestration.approval_required",
                    extra={
                        "event_name": "approval_required",
                        "step_id": step.step_id,
                        "approval_type": step.approval_type.value,
                    },
                )
                decision = await self._approval_policy.evaluate(request, self._approval_callback)
                if not decision.approved:
                    failure_counter.add(1, {"step_id": step.step_id, "reason": "approval_denied"})
                    span.set_attribute("step.denied", True)
                    raise ApprovalDeniedError(request, decision)

            try:
                result = await _resolve_action(step, context)
            except Exception as exc:  # pragma: no cover - exception path validated via events
                failure_counter.add(1, {"step_id": step.step_id, "reason": type(exc).__name__})
                yield OrchestrationStepFailedEvent(
                    step_id=step.step_id,
                    step_name=step.name,
                    error=str(exc),
                    context_snapshot=_snapshot_context(context),
                )
                logger.info(
                    "orchestration.step_failed",
                    extra={
                        "event_name": "step_failed",
                        "step_id": step.step_id,
                        "step_name": step.name,
                        "error": str(exc),
                    },
                )
                raise

            context.transient_artifacts[step.step_id] = result

            if isinstance(result, SQLExecutionResult):
                for attempt in result.attempts:
                    sql_attempt_counter.add(
                        1,
                        {
                            "step_id": step.step_id,
                            "step_name": step.name,
                            "outcome": "success" if attempt.error is None else "error",
                        },
                    )
                    logger.info(
                        "orchestration.sql_attempt",
                        extra={
                            "event_name": "sql_attempt",
                            "step_id": step.step_id,
                            "step_name": step.name,
                            "sql": attempt.sql,
                            "error": attempt.error,
                        },
                    )
                    yield SQLExecutionEvent(
                        step_id=step.step_id,
                        step_name=step.name,
                        sql=attempt.sql,
                        rows=attempt.rows,
                        raw_rows=attempt.raw_rows,
                        error=attempt.error,
                        context_snapshot=_snapshot_context(context),
                    )

            yield OrchestrationStepCompletedEvent(
                step_id=step.step_id,
                step_name=step.name,
                result=result,
                context_snapshot=_snapshot_context(context),
            )
            logger.info(
                "orchestration.step_completed",
                extra={
                    "event_name": "step_completed",
                    "step_id": step.step_id,
                    "step_name": step.name,
                },
            )

    @staticmethod
    def _derive_policy_tags(step: StepDefinition) -> set[str]:
        tags: set[str] = set(step.metadata.get("policy_tags", set()))
        if step.approval_type == ApprovalType.SQL:
            tags.add("ddl_dml")
        if step.approval_type == ApprovalType.MCP:
            tags.add("mcp_action")
        if step.approval_type == ApprovalType.CUSTOM:
            tags.add("custom")
        return tags
