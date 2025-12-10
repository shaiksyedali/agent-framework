"""Dynamic orchestrator utilities for building and managing workflows.

This module provides helper functions and utilities for:
- Dynamic StepGraph construction
- Approval policy builders
- Context management
- Common workflow patterns
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from agent_framework.orchestrator.approvals import ApprovalType
from agent_framework.orchestrator.context import OrchestrationContext
from agent_framework.orchestrator.graph import StepDefinition, StepGraph

logger = logging.getLogger(__name__)


def create_sequential_graph(
    steps: List[Dict[str, Any]],
    context: OrchestrationContext,
) -> StepGraph:
    """Create a sequential workflow graph where each step depends on the previous.

    Args:
        steps: List of step configurations, each with:
            - step_id: Unique identifier
            - name: Human-readable name
            - action: Callable step action
            - approval_type: Optional ApprovalType
            - summary: Optional summary
        context: Orchestration context

    Returns:
        StepGraph with sequential dependencies

    Example:
        >>> steps = [
        ...     {"step_id": "step1", "name": "Query DB", "action": query_fn},
        ...     {"step_id": "step2", "name": "Format", "action": format_fn},
        ... ]
        >>> graph = create_sequential_graph(steps, context)
    """
    graph = StepGraph()
    previous_step_id = None

    for step_config in steps:
        step_def = StepDefinition(
            step_id=step_config["step_id"],
            name=step_config["name"],
            action=step_config["action"],
            approval_type=step_config.get("approval_type"),
            summary=step_config.get("summary"),
            metadata=step_config.get("metadata", {}),
        )

        dependencies = [previous_step_id] if previous_step_id else None
        graph.add_step(step_def, dependencies=dependencies)
        previous_step_id = step_config["step_id"]

    graph.validate_acyclic()
    return graph


def create_parallel_graph(
    parallel_steps: List[Dict[str, Any]],
    context: OrchestrationContext,
    merge_step: Optional[Dict[str, Any]] = None,
) -> StepGraph:
    """Create a workflow graph with parallel execution and optional merge.

    Args:
        parallel_steps: List of steps to execute in parallel
        context: Orchestration context
        merge_step: Optional final step that depends on all parallel steps

    Returns:
        StepGraph with parallel structure

    Example:
        >>> parallel = [
        ...     {"step_id": "query1", "name": "Query A", "action": fn1},
        ...     {"step_id": "query2", "name": "Query B", "action": fn2},
        ... ]
        >>> merge = {"step_id": "merge", "name": "Combine", "action": merge_fn}
        >>> graph = create_parallel_graph(parallel, context, merge)
    """
    graph = StepGraph()

    # Add all parallel steps (no dependencies)
    for step_config in parallel_steps:
        step_def = StepDefinition(
            step_id=step_config["step_id"],
            name=step_config["name"],
            action=step_config["action"],
            approval_type=step_config.get("approval_type"),
            summary=step_config.get("summary"),
            metadata=step_config.get("metadata", {}),
        )
        graph.add_step(step_def, dependencies=None)

    # Add merge step if provided (depends on all parallel steps)
    if merge_step:
        merge_def = StepDefinition(
            step_id=merge_step["step_id"],
            name=merge_step["name"],
            action=merge_step["action"],
            approval_type=merge_step.get("approval_type"),
            summary=merge_step.get("summary"),
            metadata=merge_step.get("metadata", {}),
        )
        # Merge depends on all parallel steps
        dependencies = [step["step_id"] for step in parallel_steps]
        graph.add_step(merge_def, dependencies=dependencies)

    graph.validate_acyclic()
    return graph


def create_conditional_graph(
    condition_step: Dict[str, Any],
    true_branch_steps: List[Dict[str, Any]],
    false_branch_steps: List[Dict[str, Any]],
    context: OrchestrationContext,
    merge_step: Optional[Dict[str, Any]] = None,
) -> StepGraph:
    """Create a conditional workflow graph (not fully supported by current StepGraph).

    Note: Current StepGraph implementation doesn't support true conditionals.
    This creates both branches and relies on steps to check context conditions.

    Args:
        condition_step: Step that evaluates condition (stores result in context)
        true_branch_steps: Steps to execute if condition is true
        false_branch_steps: Steps to execute if condition is false
        context: Orchestration context
        merge_step: Optional final step after branches

    Returns:
        StepGraph with conditional structure (limited support)
    """
    logger.warning("Conditional graphs have limited support in current implementation")

    graph = StepGraph()

    # Add condition step
    cond_def = StepDefinition(
        step_id=condition_step["step_id"],
        name=condition_step["name"],
        action=condition_step["action"],
        metadata={"type": "condition"},
    )
    graph.add_step(cond_def)

    # Add true branch (depends on condition)
    for step_config in true_branch_steps:
        step_def = StepDefinition(
            step_id=step_config["step_id"],
            name=step_config["name"],
            action=step_config["action"],
            approval_type=step_config.get("approval_type"),
            metadata={"branch": "true"},
        )
        graph.add_step(step_def, dependencies=[condition_step["step_id"]])

    # Add false branch (depends on condition)
    for step_config in false_branch_steps:
        step_def = StepDefinition(
            step_id=step_config["step_id"],
            name=step_config["name"],
            action=step_config["action"],
            approval_type=step_config.get("approval_type"),
            metadata={"branch": "false"},
        )
        graph.add_step(step_def, dependencies=[condition_step["step_id"]])

    # Add merge step if provided
    if merge_step:
        merge_def = StepDefinition(
            step_id=merge_step["step_id"],
            name=merge_step["name"],
            action=merge_step["action"],
            metadata={"type": "merge"},
        )
        # Depends on last steps of both branches
        all_branch_steps = true_branch_steps + false_branch_steps
        dependencies = [step["step_id"] for step in all_branch_steps]
        graph.add_step(merge_def, dependencies=dependencies)

    return graph


def create_agent_action(
    agent: Any,
    input_formatter: Optional[Callable[[OrchestrationContext], str]] = None,
) -> Callable[[OrchestrationContext], Awaitable[Any]]:
    """Create a step action that executes an agent.

    Args:
        agent: Agent to execute (must have run() method)
        input_formatter: Optional function to format input from context

    Returns:
        Async function suitable for StepDefinition.action

    Example:
        >>> sql_agent = StructuredDataAgent(...)
        >>> action = create_agent_action(
        ...     agent=sql_agent,
        ...     input_formatter=lambda ctx: ctx.transient_artifacts.get("query", "")
        ... )
        >>> step = StepDefinition(step_id="sql", name="Query", action=action)
    """
    async def step_action(context: OrchestrationContext) -> Any:
        """Execute agent within context."""
        # Format input from context
        if input_formatter:
            agent_input = input_formatter(context)
        else:
            # Default: look for 'input' in transient_artifacts
            agent_input = context.transient_artifacts.get("input", "")

        # Execute agent
        result = await agent.run(agent_input)

        return result

    return step_action


def create_approval_policy_builder() -> Dict[str, ApprovalType]:
    """Create approval policy mapping for common operations.

    Returns:
        Dictionary mapping operation types to ApprovalType

    Example:
        >>> policy = create_approval_policy_builder()
        >>> sql_approval = policy.get("sql", ApprovalType.CUSTOM)
    """
    return {
        "sql": ApprovalType.SQL,
        "sql_write": ApprovalType.SQL,
        "sql_read": None,  # No approval needed for read-only
        "database": ApprovalType.SQL,
        "api_call": ApprovalType.MCP,
        "external_service": ApprovalType.MCP,
        "mcp": ApprovalType.MCP,
        "custom": ApprovalType.CUSTOM,
    }


def enrich_context(
    context: OrchestrationContext,
    connectors: Optional[Dict[str, Any]] = None,
    artifacts: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> OrchestrationContext:
    """Enrich orchestration context with additional data.

    Args:
        context: Base context to enrich
        connectors: Additional connectors to add
        artifacts: Additional artifacts to add
        metadata: Additional metadata to add

    Returns:
        Enriched OrchestrationContext

    Example:
        >>> base_context = OrchestrationContext(workflow_id="wf-123")
        >>> enriched = enrich_context(
        ...     context=base_context,
        ...     connectors={"database": sql_connector},
        ...     artifacts={"user_id": "123"}
        ... )
    """
    new_context = context

    # Add connectors
    if connectors:
        for key, connector in connectors.items():
            new_context = new_context.with_connector(key, connector)

    # Add artifacts
    if artifacts:
        for key, value in artifacts.items():
            new_context = new_context.with_artifact(key, value)

    # Add metadata
    if metadata:
        new_metadata = dict(context.workflow_metadata)
        new_metadata.update(metadata)
        new_context.workflow_metadata = new_metadata

    return new_context


def create_data_flow_graph(
    data_flow: Dict[str, List[str]],
    step_actions: Dict[str, Callable],
    step_names: Optional[Dict[str, str]] = None,
) -> StepGraph:
    """Create StepGraph from data flow specification.

    Args:
        data_flow: Dictionary mapping step_id to list of dependent step_ids
            Example: {"step2": ["step1"], "step3": ["step1", "step2"]}
        step_actions: Dictionary mapping step_id to action callable
        step_names: Optional dictionary mapping step_id to human-readable names

    Returns:
        StepGraph with specified dependencies

    Example:
        >>> flow = {"analyze": ["fetch"], "report": ["analyze"]}
        >>> actions = {"fetch": fetch_fn, "analyze": analyze_fn, "report": report_fn}
        >>> graph = create_data_flow_graph(flow, actions)
    """
    graph = StepGraph()

    # Collect all step IDs
    all_steps = set(data_flow.keys())
    for deps in data_flow.values():
        all_steps.update(deps)

    # Add steps with no dependencies first
    root_steps = all_steps - set(data_flow.keys())
    for step_id in root_steps:
        if step_id in step_actions:
            step_def = StepDefinition(
                step_id=step_id,
                name=step_names.get(step_id, step_id) if step_names else step_id,
                action=step_actions[step_id],
            )
            graph.add_step(step_def, dependencies=None)

    # Add dependent steps in order
    added = set(root_steps)
    while len(added) < len(all_steps):
        for step_id, deps in data_flow.items():
            if step_id not in added and all(dep in added for dep in deps):
                if step_id in step_actions:
                    step_def = StepDefinition(
                        step_id=step_id,
                        name=step_names.get(step_id, step_id) if step_names else step_id,
                        action=step_actions[step_id],
                    )
                    graph.add_step(step_def, dependencies=deps)
                    added.add(step_id)

    graph.validate_acyclic()
    return graph


def create_retry_wrapper(
    action: Callable[[OrchestrationContext], Awaitable[Any]],
    max_retries: int = 3,
    backoff_multiplier: float = 1.0,
) -> Callable[[OrchestrationContext], Awaitable[Any]]:
    """Wrap a step action with retry logic.

    Args:
        action: Original step action
        max_retries: Maximum number of retry attempts
        backoff_multiplier: Multiplier for exponential backoff

    Returns:
        Wrapped action with retry logic

    Example:
        >>> original_action = lambda ctx: risky_operation()
        >>> retry_action = create_retry_wrapper(original_action, max_retries=3)
        >>> step = StepDefinition(step_id="risky", name="Risky Op", action=retry_action)
    """
    import asyncio

    async def retry_action(context: OrchestrationContext) -> Any:
        """Execute action with retry logic."""
        last_exception = None

        for attempt in range(max_retries):
            try:
                result = await action(context)
                return result
            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Action failed (attempt {attempt + 1}/{max_retries}): {e}"
                )

                if attempt < max_retries - 1:
                    # Exponential backoff
                    wait_time = backoff_multiplier * (2 ** attempt)
                    await asyncio.sleep(wait_time)

        # All retries exhausted
        raise Exception(
            f"Action failed after {max_retries} attempts: {last_exception}"
        )

    return retry_action


def merge_workflow_outputs(
    outputs: List[Any],
    strategy: str = "concatenate",
) -> Any:
    """Merge outputs from multiple workflow steps.

    Args:
        outputs: List of outputs to merge
        strategy: Merge strategy ('concatenate', 'dict', 'first', 'last')

    Returns:
        Merged output

    Example:
        >>> outputs = [{"a": 1}, {"b": 2}, {"c": 3}]
        >>> merged = merge_workflow_outputs(outputs, strategy="dict")
        >>> # Result: {"a": 1, "b": 2, "c": 3}
    """
    if not outputs:
        return None

    if strategy == "first":
        return outputs[0]

    elif strategy == "last":
        return outputs[-1]

    elif strategy == "concatenate":
        # Concatenate lists or strings
        if all(isinstance(o, list) for o in outputs):
            result = []
            for output in outputs:
                result.extend(output)
            return result
        elif all(isinstance(o, str) for o in outputs):
            return "\n".join(outputs)
        else:
            return outputs

    elif strategy == "dict":
        # Merge dictionaries
        result = {}
        for output in outputs:
            if isinstance(output, dict):
                result.update(output)
        return result

    else:
        raise ValueError(f"Unknown merge strategy: {strategy}")
