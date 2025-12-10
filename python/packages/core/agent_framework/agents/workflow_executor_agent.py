"""Workflow Executor Agent for step-by-step workflow execution with user feedback."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable, Dict, Optional

from agent_framework.orchestrator.context import OrchestrationContext
from agent_framework.orchestrator.events import (
    ApprovalRequiredEvent,
    OrchestrationCompletedEvent,
    OrchestrationEvent,
    OrchestrationStepCompletedEvent,
    OrchestrationStepFailedEvent,
    OrchestrationStepStartedEvent,
    SQLExecutionEvent,
)
from agent_framework.orchestrator.runner import Orchestrator
from agent_framework.schemas.workflow_plan import (
    ExecutionEvent,
    StepExecutionResult,
    UserFeedback,
    WorkflowExecutionSummary,
    WorkflowPlan,
)

logger = logging.getLogger(__name__)


class WorkflowExecutorAgent:
    """Agent that executes workflows step-by-step with user feedback integration.

    This agent wraps the Orchestrator to provide user-friendly execution with:
    - Step-by-step progress tracking
    - User feedback after each step (proceed/rerun/abort)
    - Formatted output (tables, visualizations, JSON)
    - Error handling and recovery

    Example:
        >>> executor = WorkflowExecutorAgent(
        ...     orchestrator=orchestrator,
        ...     feedback_callback=my_feedback_handler,
        ... )
        >>> context = OrchestrationContext(
        ...     workflow_id="wf-123",
        ...     connectors={"database": connector},
        ... )
        >>> async for event in executor.execute_workflow(plan, context):
        ...     if event.type == "step_completed":
        ...         print(f"Step completed: {event.output}")
        ...     elif event.type == "approval_required":
        ...         # Handle approval
        ...         pass
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        feedback_callback: Optional[Callable[[OrchestrationStepCompletedEvent], UserFeedback]] = None,
        *,
        name: str = "workflow_executor",
    ):
        """Initialize the Workflow Executor Agent.

        Args:
            orchestrator: Orchestrator instance for executing StepGraphs
            feedback_callback: Optional callback for requesting user feedback after each step
            name: Agent name
        """
        self.orchestrator = orchestrator
        self.feedback_callback = feedback_callback
        self.name = name
        self._execution_history: list[StepExecutionResult] = []

    async def execute_workflow(
        self,
        plan: WorkflowPlan,
        context: OrchestrationContext,
        graph_builder: Callable[[WorkflowPlan, OrchestrationContext], Any],
    ) -> AsyncIterator[ExecutionEvent]:
        """Execute workflow with step-by-step user feedback.

        Yields:
            ExecutionEvent: Events for each step completion, approval request, etc.

        Args:
            plan: Workflow plan to execute
            context: Orchestration context with connectors and agents
            graph_builder: Function to build StepGraph from WorkflowPlan
                (usually WorkflowPlannerAgent.build_step_graph)
        """
        logger.info(f"Starting workflow execution: {plan.name}")

        # Build StepGraph from plan
        try:
            graph = graph_builder(plan, context)
        except Exception as e:
            logger.error(f"Failed to build execution graph: {e}")
            yield ExecutionEvent(
                type="execution_failed",
                error=f"Failed to build execution graph: {e}",
            )
            return

        # Reset execution history
        self._execution_history = []

        # Execute with orchestrator
        try:
            async for event in self.orchestrator.run(graph, context):
                # Format and yield event
                formatted_event = self._format_event(event)
                if formatted_event:
                    yield formatted_event

                # Handle step completion - request user feedback
                if isinstance(event, OrchestrationStepCompletedEvent):
                    # Record execution result
                    step_result = StepExecutionResult(
                        step_id=event.step_id,
                        step_name=event.step_name,
                        success=True,
                        output=event.result,
                    )
                    self._execution_history.append(step_result)

                    # Request user feedback if callback provided
                    if self.feedback_callback:
                        feedback = await self._request_user_feedback(event)

                        if feedback.action == "rerun":
                            # TODO: Implement step rerun logic
                            logger.warning("Step rerun not yet implemented")
                            yield ExecutionEvent(
                                type="feedback_received",
                                step_id=event.step_id,
                                output={"action": "rerun", "message": feedback.message},
                            )
                        elif feedback.action == "abort":
                            logger.info(f"User requested abort at step {event.step_id}")
                            yield ExecutionEvent(
                                type="execution_aborted",
                                step_id=event.step_id,
                            )
                            break
                        # Otherwise proceed to next step

                elif isinstance(event, OrchestrationStepFailedEvent):
                    # Record failure
                    step_result = StepExecutionResult(
                        step_id=event.step_id,
                        step_name=event.step_name,
                        success=False,
                        error=event.error,
                    )
                    self._execution_history.append(step_result)

                elif isinstance(event, OrchestrationCompletedEvent):
                    # Workflow completed successfully
                    logger.info(f"Workflow completed: {plan.name}")

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            yield ExecutionEvent(
                type="execution_failed",
                error=str(e),
            )

    def _format_event(self, event: OrchestrationEvent) -> ExecutionEvent | None:
        """Format orchestration events for user display.

        Args:
            event: Event from orchestrator

        Returns:
            Formatted ExecutionEvent or None if event should not be displayed
        """
        if isinstance(event, OrchestrationStepStartedEvent):
            return ExecutionEvent(
                type="step_started",
                step_id=event.step_id,
                step_name=event.step_name,
            )

        elif isinstance(event, OrchestrationStepCompletedEvent):
            # Format result as table or visualization
            formatted_output = self._format_output(event.result)

            return ExecutionEvent(
                type="step_completed",
                step_id=event.step_id,
                step_name=event.step_name,
                output=formatted_output,
            )

        elif isinstance(event, OrchestrationStepFailedEvent):
            return ExecutionEvent(
                type="step_failed",
                step_id=event.step_id,
                step_name=event.step_name,
                error=event.error,
            )

        elif isinstance(event, ApprovalRequiredEvent):
            return ExecutionEvent(
                type="approval_required",
                step_id=event.request.step_id,
                step_name=event.request.step_name,
                approval_request=event.request,
            )

        elif isinstance(event, SQLExecutionEvent):
            return ExecutionEvent(
                type="sql_execution",
                step_id=event.step_id,
                step_name=event.step_name,
                output={
                    "sql": event.sql,
                    "rows": event.rows,
                    "raw_rows": event.raw_rows,
                    "error": event.error,
                },
            )

        elif isinstance(event, OrchestrationCompletedEvent):
            return ExecutionEvent(
                type="execution_completed",
            )

        # Don't yield other event types
        return None

    def _format_output(self, result: Any) -> Dict[str, Any]:
        """Format step output for visualization.

        Returns:
            Dict with 'type' (table/text/json) and 'data'
        """
        # Handle structured data agent results
        if hasattr(result, "sql") and hasattr(result, "results"):
            return {
                "type": "structured_data",
                "sql": result.sql,
                "data": result.results or [],
                "raw_data": result.raw_results or [],
                "num_results": len(result.results or []),
            }

        # Handle agent run responses
        if hasattr(result, "text") and hasattr(result, "value"):
            output = {
                "type": "agent_response",
                "text": result.text,
            }
            if result.value:
                output["metadata"] = result.value
            return output

        # Handle list of dicts (tabular data)
        if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
            return {
                "type": "table",
                "data": result,
                "columns": list(result[0].keys()),
                "num_rows": len(result),
            }

        # Handle dict
        if isinstance(result, dict):
            return {
                "type": "json",
                "data": result,
            }

        # Default: convert to string
        return {
            "type": "text",
            "data": str(result),
        }

    async def _request_user_feedback(
        self,
        event: OrchestrationStepCompletedEvent,
    ) -> UserFeedback:
        """Request user feedback after step completion.

        Args:
            event: Step completion event

        Returns:
            UserFeedback with action (proceed/rerun/abort)
        """
        if self.feedback_callback:
            try:
                feedback = self.feedback_callback(event)
                if feedback:
                    return feedback
            except Exception as e:
                logger.error(f"Feedback callback failed: {e}")

        # Default: proceed
        return UserFeedback(action="proceed", message=None)

    def get_execution_summary(
        self,
        workflow_id: str,
        workflow_name: str,
    ) -> WorkflowExecutionSummary:
        """Get summary of workflow execution.

        Args:
            workflow_id: Workflow ID
            workflow_name: Workflow name

        Returns:
            WorkflowExecutionSummary with all step results
        """
        # Determine status
        if not self._execution_history:
            status = "not_started"
        elif any(not result.success for result in self._execution_history):
            status = "failed"
        else:
            status = "completed"

        return WorkflowExecutionSummary(
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=status,
            step_results=list(self._execution_history),
        )


def format_output_as_table(data: list[dict[str, Any]]) -> str:
    """Format tabular data as ASCII table.

    Args:
        data: List of row dictionaries

    Returns:
        Formatted table string
    """
    if not data:
        return "No data"

    # Get columns
    columns = list(data[0].keys())
    max_widths = {col: len(col) for col in columns}

    # Calculate max widths
    for row in data:
        for col in columns:
            val_str = str(row.get(col, ""))
            max_widths[col] = max(max_widths[col], len(val_str))

    # Build table
    lines = []

    # Header
    header = " | ".join(col.ljust(max_widths[col]) for col in columns)
    lines.append(header)
    lines.append("-" * len(header))

    # Rows (limit to first 10 for display)
    for row in data[:10]:
        row_str = " | ".join(
            str(row.get(col, "")).ljust(max_widths[col]) for col in columns
        )
        lines.append(row_str)

    if len(data) > 10:
        lines.append(f"... ({len(data) - 10} more rows)")

    return "\n".join(lines)
