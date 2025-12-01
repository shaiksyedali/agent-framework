import sqlite3

import pytest

from agent_framework.orchestrator import (
    ApprovalRequiredEvent,
    ApprovalType,
    OrchestrationContext,
    OrchestrationStepCompletedEvent,
    OrchestrationStepStartedEvent,
    Orchestrator,
    SQLExecutionEvent,
    StepDefinition,
    StepGraph,
)


@pytest.mark.asyncio
async def test_orchestrator_streaming_event_envelopes_include_context():
    """Streaming events should carry sanitized context snapshots for UI replay."""

    context = OrchestrationContext(connectors={"db": object()}, workflow_metadata={"token": "secret-value"})

    async def action(ctx: OrchestrationContext) -> dict:
        return {"result": "ok", "ctx": ctx.workflow_id}

    step = StepDefinition(
        step_id="step-1",
        name="First",
        action=action,
        approval_type=ApprovalType.SQL,
        summary="run sql",
    )
    graph = StepGraph()
    graph.add_step(step)

    orchestrator = Orchestrator()
    events = [event async for event in orchestrator.run(graph, context)]

    assert any(isinstance(e, OrchestrationStepStartedEvent) for e in events)
    approvals = [e for e in events if isinstance(e, ApprovalRequiredEvent)]
    assert approvals and approvals[0].context_snapshot["workflow_id"] == context.workflow_id
    assert approvals[0].context_snapshot["workflow_metadata"]["token"] == "<redacted>"
    completions = [e for e in events if isinstance(e, OrchestrationStepCompletedEvent)]
    assert completions and completions[0].context_snapshot["connectors"] == {"db": "object"}


@pytest.mark.asyncio
async def test_sql_events_surface_attempt_metadata(tmp_path):
    """SQL execution events should preserve attempt details for downstream consumers."""

    db_path = tmp_path / "contract.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE numbers (id INTEGER, value INTEGER)")
    connection.executemany("INSERT INTO numbers VALUES (?, ?)", [(1, 2), (2, 3)])
    connection.commit()
    connection.close()

    from agent_framework.agents.sql import SQLAgent
    from agent_framework.data.connectors import SQLiteConnector

    async def llm(_: str) -> str:
        return "SELECT value FROM numbers"

    connector = SQLiteConnector(database=str(db_path))
    agent = SQLAgent(llm=llm)

    async def action(_: OrchestrationContext):
        return await agent.generate_and_execute("fetch", connector)

    step = StepDefinition(step_id="sql", name="sql", action=action, approval_type=ApprovalType.SQL)
    graph = StepGraph()
    graph.add_step(step)

    orchestrator = Orchestrator()
    events = [event async for event in orchestrator.run(graph, OrchestrationContext())]

    sql_events = [e for e in events if isinstance(e, SQLExecutionEvent)]
    assert sql_events and sql_events[0].sql is not None
    assert sql_events[0].rows and sql_events[0].rows[0]["value"] == 2
    assert sql_events[0].context_snapshot["transient_artifacts"].get("sql") is not None
