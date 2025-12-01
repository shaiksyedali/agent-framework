import pytest

from agent_framework.agents import IntentType, Planner
from agent_framework.data.connectors import SQLiteConnector
from agent_framework.data.vector_store import DocumentIngestionService
from agent_framework.orchestrator import (
    ApprovalDecision,
    ApprovalRequiredEvent,
    ApprovalType,
    OrchestrationContext,
    Orchestrator,
    OrchestrationStepCompletedEvent,
)
from agent_framework.orchestrator.events import PlanProposedEvent


@pytest.mark.asyncio
async def test_planner_emits_plan_and_routes_sql():
    context = OrchestrationContext(connectors={"db": SQLiteConnector()})
    planner = Planner()

    graph, artifact = planner.build_graph("select all rows from orders table", context)

    assert artifact.intent.intent == IntentType.SQL
    assert artifact.data_source.connector_key == "db"

    async def approve(request):
        return ApprovalDecision.allow("ok")

    orchestrator = Orchestrator(approval_callback=approve)
    events = [event async for event in orchestrator.run(graph, context)]

    plan_events = [e for e in events if isinstance(e, PlanProposedEvent)]
    assert len(plan_events) == 1
    assert plan_events[0].plan.steps[0].approval_type == ApprovalType.PLAN

    approval_events = [e for e in events if isinstance(e, ApprovalRequiredEvent)]
    assert {e.request.approval_type for e in approval_events} == {ApprovalType.PLAN, ApprovalType.SQL}

    completed = {e.step_id: e for e in events if isinstance(e, OrchestrationStepCompletedEvent)}
    assert completed["execute_sql"].result[0]["result"] == 1


@pytest.mark.asyncio
async def test_planner_routes_to_rag_when_sql_is_unavailable():
    ingestion = DocumentIngestionService()
    ingestion.ingest(["The support manual explains approvals."], metadata={"source": "kb"})
    context = OrchestrationContext(connectors={"kb": ingestion})
    planner = Planner()

    graph, artifact = planner.build_graph("Where is the manual stored?", context)

    assert artifact.data_source.target == IntentType.RAG

    orchestrator = Orchestrator()
    events = [event async for event in orchestrator.run(graph, context)]

    plan_events = [e for e in events if isinstance(e, PlanProposedEvent)]
    assert len(plan_events) == 1

    completed = {e.step_id: e for e in events if isinstance(e, OrchestrationStepCompletedEvent)}
    retrieved = completed["retrieve_context"].result
    assert len(retrieved) == 1
    assert "support manual" in retrieved[0]


@pytest.mark.asyncio
async def test_planner_invokes_custom_tool_when_no_connectors():
    calls: list[str] = []

    def custom_tool(goal: str) -> str:
        calls.append(goal)
        return "scheduled"

    context = OrchestrationContext()
    planner = Planner()

    graph, artifact = planner.build_graph(
        "Schedule the deployment review",
        context,
        custom_tools={"scheduler": custom_tool},
    )

    assert artifact.data_source.target == IntentType.CUSTOM

    orchestrator = Orchestrator(approval_callback=lambda req: ApprovalDecision.allow("custom ok"))
    events = [event async for event in orchestrator.run(graph, context)]

    completed = {e.step_id: e for e in events if isinstance(e, OrchestrationStepCompletedEvent)}
    assert completed["invoke_tool"].result == "scheduled"
    assert calls == ["Schedule the deployment review"]
