import asyncio
import pytest

from agent_framework.orchestrator import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalType,
    OrchestrationContext,
    Orchestrator,
    StepDefinition,
    StepGraph,
    ApprovalRequiredEvent,
    OrchestrationStepCompletedEvent,
)


@pytest.mark.asyncio
async def test_runs_steps_and_tracks_artifacts():
    context = OrchestrationContext(workflow_metadata={"title": "demo"}, persona={"name": "tester"})

    async def first_step(ctx: OrchestrationContext):
        return {"greeting": "hello", "persona": ctx.persona["name"]}

    def second_step(ctx: OrchestrationContext):
        previous = ctx.transient_artifacts["first"]
        return f"{previous['greeting']} {ctx.workflow_metadata['title']}"

    graph = StepGraph()
    graph.add_step(StepDefinition("first", "First", first_step))
    graph.add_step(StepDefinition("second", "Second", second_step), dependencies=["first"])

    orchestrator = Orchestrator()
    events = [event async for event in orchestrator.run(graph, context)]

    completed = [e for e in events if isinstance(e, OrchestrationStepCompletedEvent)]
    assert len(completed) == 2
    assert context.transient_artifacts["first"]["greeting"] == "hello"
    assert context.transient_artifacts["second"] == "hello demo"


@pytest.mark.asyncio
async def test_gates_steps_on_approval():
    approvals: list[ApprovalRequest] = []

    async def approval_callback(request: ApprovalRequest):
        approvals.append(request)
        await asyncio.sleep(0)
        return ApprovalDecision.allow("approved for testing")

    context = OrchestrationContext()
    graph = StepGraph()
    graph.add_step(
        StepDefinition(
            "plan",
            "Plan",
            lambda ctx: {"plan": "select * from table"},
            approval_type=ApprovalType.SQL,
            summary="Execute generated SQL",
        )
    )

    orchestrator = Orchestrator(approval_callback=approval_callback)
    events = [event async for event in orchestrator.run(graph, context)]

    approval_events = [e for e in events if isinstance(e, ApprovalRequiredEvent)]
    assert len(approvals) == 1
    assert approvals[0].approval_type == ApprovalType.SQL
    assert len(approval_events) == 1

    completed = [e for e in events if isinstance(e, OrchestrationStepCompletedEvent)]
    assert completed[0].result == {"plan": "select * from table"}
