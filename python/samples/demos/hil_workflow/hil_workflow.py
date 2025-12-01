"""
Human-in-the-loop multi-agent workflow sample.

This sample shows how to compose Planner → SQL → RAG → Reasoning → Response agents
with engine-specific SQL connectors (DuckDB/SQLite/Postgres) and approval-gated tools.
It uses SQLite by default to avoid external dependencies.
"""
import asyncio
from typing import Annotated

from agent_framework import ai_function
from agent_framework.hil_workflow import (
    Engine,
    HilOrchestrator,
    LocalRetriever,
    SQLiteConnector,
    WorkflowConfig,
)


# Optional calculator to demonstrate tool chaining during reasoning
@ai_function(name="calculator", description="Perform reliable numeric calculations")
def calculator(expression: Annotated[str, "Python arithmetic expression"]) -> str:
    return str(eval(expression))  # noqa: S307 - sample-only evaluation


def build_sample_workflow():
    # Configure the workflow coming from the UI
    config = WorkflowConfig(
        workflow_name="Fleet Ops Summary",
        persona="Operations analyst",
        sql_engine=Engine.SQLITE,
        approval_mode="always_require",  # Gate SQL execution for HIL confirmation
        retriever_top_k=3,
        calculator_tool=calculator,
    )

    # Use SQLite for the sample (swap to DuckDBConnector or PostgresConnector if available)
    sql_connector = SQLiteConnector()
    sql_connector._conn.execute(
        "CREATE TABLE trips(id INTEGER, city TEXT, miles REAL, fuel_gal REAL);"
    )
    sql_connector._conn.execute(
        "INSERT INTO trips VALUES (1, 'Seattle', 12.1, 0.5), (2, 'Portland', 9.4, 0.45);"
    )

    retriever = LocalRetriever(
        documents=[
            "Seattle fleet: prioritize charging near the port terminals.",
            "Portland trips frequently include hills—expect higher energy draw.",
        ],
        top_k=config.retriever_top_k,
    )

    orchestrator = HilOrchestrator(
        config=config,
        sql_connector=sql_connector,
        retriever=retriever,
    )

    return orchestrator.build()


async def main():
    workflow = build_sample_workflow()
    user_goal = "Summarize average miles per trip and cite any relevant fleet notes."

    async for event in workflow.run_stream(user_goal):
        print(event)


if __name__ == "__main__":
    asyncio.run(main())

"""
Sample output (truncated):
WorkflowOutputEvent(data="Average miles: ...")
"""
