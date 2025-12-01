import pytest

from agent_framework.agents import (
    DomainAgentMatch,
    DomainAgentRegistry,
    DomainAgentRegistration,
    DomainToolRegistration,
    IntentType,
    Planner,
)
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


def _register_sample_domain_agents() -> DomainAgentRegistry:
    registry = DomainAgentRegistry()

    def fleet_detector(goal: str, context: OrchestrationContext) -> DomainAgentMatch | None:
        normalized = goal.lower()
        if "fleet" in normalized and "anomaly" in normalized:
            return DomainAgentMatch(confidence=0.81, reason="Detected fleet anomaly intent", suggested_tool="score")
        return None

    scorer = DomainAgentRegistration(
        key="fleet_scorer",
        name="Fleet anomaly scorer",
        description="Scores CAN and telemetry events for anomalies",
        detector=fleet_detector,
        data_dependencies={"telemetry"},
    )
    scorer.register_tool(
        DomainToolRegistration(
            name="score",
            description="Score recent events for anomalies",
            handler=lambda goal, _: {"goal": goal, "scored": True},
            policy_tags={"fleet"},
        )
    )
    registry.register_agent(scorer)

    def can_detector(goal: str, _: OrchestrationContext) -> DomainAgentMatch | None:
        normalized = goal.lower()
        if "can" in normalized and "decode" in normalized:
            return DomainAgentMatch(confidence=0.77, reason="Detected CAN decode request")
        return None

    decoder = DomainAgentRegistration(
        key="can_decoder",
        name="CAN decoder",
        description="Decodes CAN frames",
        detector=can_detector,
        data_dependencies={"can_bus"},
    )
    decoder.register_tool(
        DomainToolRegistration(
            name="decode",
            description="Decode CAN traces",
            handler=lambda goal, ctx: {"decoded": ctx.connectors.get("can_bus"), "goal": goal},
            approval_type=ApprovalType.CUSTOM,
            summary_prefix="Decode CAN frames",
        )
    )
    registry.register_agent(decoder)
    return registry


@pytest.mark.asyncio
async def test_planner_prefers_domain_agents_and_invokes_tool():
    registry = _register_sample_domain_agents()
    context = OrchestrationContext(connectors={"telemetry": object(), "can_bus": "trace.bin"})
    planner = Planner(domain_registry=registry)

    graph, artifact = planner.build_graph("run fleet anomaly scoring", context)

    assert artifact.intent.intent == IntentType.DOMAIN
    assert artifact.intent.domain_agent_key == "fleet_scorer"
    assert artifact.data_source.domain_agent_key == "fleet_scorer"
    assert artifact.data_source.tool_name == "score"

    orchestrator = Orchestrator()
    events = [event async for event in orchestrator.run(graph, context)]
    completed = {e.step_id: e for e in events if isinstance(e, OrchestrationStepCompletedEvent)}

    assert completed["run_fleet_scorer"].result["scored"] is True
    assert completed["run_fleet_scorer"].result["goal"] == "run fleet anomaly scoring"


@pytest.mark.asyncio
async def test_domain_agents_report_missing_dependencies_in_plan():
    registry = _register_sample_domain_agents()
    context = OrchestrationContext()
    planner = Planner(domain_registry=registry)

    graph, artifact = planner.build_graph("decode CAN logs", context)

    assert artifact.intent.intent == IntentType.DOMAIN
    assert artifact.data_source.missing_dependencies == ["can_bus"]

    orchestrator = Orchestrator()
    events = [event async for event in orchestrator.run(graph, context)]
    completed = {e.step_id: e for e in events if isinstance(e, OrchestrationStepCompletedEvent)}

    blocked = completed["review_can_decoder_inputs"].result
    assert blocked["status"] == "blocked"
    assert blocked["missing_dependencies"] == ["can_bus"]
