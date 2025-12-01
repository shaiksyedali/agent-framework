import sqlite3

import pytest

from agent_framework.agents import Planner, SQLAgent, SQLExample
from agent_framework.data import DataConnectorError, SQLApprovalPolicy, SQLiteConnector
from agent_framework.orchestrator import (
    ApprovalDecision,
    ApprovalRequiredEvent,
    ApprovalType,
    OrchestrationContext,
    OrchestrationStepCompletedEvent,
    Orchestrator,
    SQLExecutionEvent,
)


@pytest.mark.asyncio
async def test_sql_agent_uses_schema_and_history(tmp_path):
    db_path = tmp_path / "orders.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE orders (id INTEGER, total INTEGER)")
    connection.executemany("INSERT INTO orders VALUES (?, ?)", [(1, 10), (2, 20)])
    connection.commit()
    connection.close()

    prompts: list[str] = []

    async def llm(prompt: str) -> str:
        prompts.append(prompt)
        return "SELECT id, total FROM orders ORDER BY id"

    connector = SQLiteConnector(database=str(db_path))
    history = [SQLExample(question="List all orders", sql="SELECT * FROM orders")]
    agent = SQLAgent(llm=llm, few_shot_examples=history)

    result = await agent.generate_and_execute(
        "Show order totals",
        connector,
        max_attempts=1,
    )

    assert result.rows and len(result.rows) == 2
    prompt_text = prompts[-1]
    assert "orders" in prompt_text
    assert "List all orders" in prompt_text


@pytest.mark.asyncio
async def test_sql_agent_retries_and_validator():
    calls = 0

    async def llm(_: str) -> str:
        nonlocal calls
        calls += 1
        return "SELECT missing_column FROM missing_table" if calls == 1 else "SELECT 1 as value"

    def validator(rows):
        return bool(rows) and rows[0].get("value") == 1

    connector = SQLiteConnector()
    agent = SQLAgent(llm=llm)

    result = await agent.generate_and_execute(
        "Get a value",
        connector,
        max_attempts=2,
        validator=validator,
    )

    assert len(result.attempts) == 2
    assert result.rows and result.rows[0]["value"] == 1


@pytest.mark.asyncio
async def test_sql_agent_returns_raw_rows_after_aggregation(tmp_path):
    db_path = tmp_path / "items.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE items (id INTEGER, category TEXT)")
    connection.executemany(
        "INSERT INTO items VALUES (?, ?)",
        [(1, "a"), (2, "a"), (3, "b")],
    )
    connection.commit()
    connection.close()

    connector = SQLiteConnector(database=str(db_path))
    agent = SQLAgent(llm=lambda _: "SELECT category, COUNT(*) as total FROM items GROUP BY category")

    result = await agent.generate_and_execute("Count items by category", connector)

    assert result.raw_rows is not None
    assert any("category" in row for row in result.raw_rows)


@pytest.mark.asyncio
async def test_sql_agent_calculator_fallback():
    agent = SQLAgent(llm=lambda _: "2 + 3 * 4")
    connector = SQLiteConnector()

    result = await agent.generate_and_execute("Quick math", connector)

    assert result.sql is None
    assert result.rows and pytest.approx(result.rows[0]["result"]) == 14.0


@pytest.mark.asyncio
async def test_sql_agent_preserves_attempt_details_for_replay(tmp_path):
    """Ensure attempts capture failures and recovery details for UI replay."""

    db_path = tmp_path / "retries.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE items (id INTEGER, total INTEGER)")
    connection.executemany("INSERT INTO items VALUES (?, ?)", [(1, 5), (2, 7)])
    connection.commit()
    connection.close()

    llm_calls: list[str] = []

    async def llm(_: str) -> str:
        llm_calls.append("called")
        return "SELECT missing FROM nowhere" if len(llm_calls) == 1 else "SELECT SUM(total) AS total FROM items"

    connector = SQLiteConnector(database=str(db_path))
    agent = SQLAgent(llm=llm)

    result = await agent.generate_and_execute("Sum the totals", connector, max_attempts=2)

    assert len(result.attempts) == 2
    assert result.attempts[0].error is not None and "missing" in result.attempts[0].error
    assert result.attempts[1].rows is not None and result.attempts[1].rows[0]["total"] == 12
    assert result.sql and result.sql.lower().startswith("select sum")


@pytest.mark.asyncio
async def test_sql_agent_blocks_writes_when_disabled(tmp_path):
    db_path = tmp_path / "readonly.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE items (id INTEGER)")
    connection.commit()
    connection.close()

    connector = SQLiteConnector(database=str(db_path), approval_policy=SQLApprovalPolicy(allow_writes=False))
    agent = SQLAgent(llm=lambda _: "DELETE FROM items")

    with pytest.raises(DataConnectorError):
        await agent.generate_and_execute("delete all", connector, max_attempts=1)


@pytest.mark.asyncio
async def test_orchestrator_streams_sql_events_and_enforces_approval(tmp_path):
    db_path = tmp_path / "accounts.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE accounts (id INTEGER, status TEXT)")
    connection.executemany(
        "INSERT INTO accounts VALUES (?, ?)",
        [(1, "active"), (2, "inactive")],
    )
    connection.commit()
    connection.close()

    async def llm(_: str) -> str:
        return "SELECT COUNT(*) AS total FROM accounts"

    approval_policy = SQLApprovalPolicy(approval_required=False)
    connector = SQLiteConnector(database=str(db_path), approval_policy=approval_policy)
    context = OrchestrationContext(connectors={"db": connector})
    planner = Planner(sql_llm=llm, sql_history=[SQLExample(question="Count accounts", sql="SELECT COUNT(*) FROM accounts")])

    graph, artifact = planner.build_graph("Count all accounts", context)
    assert artifact.steps[-1].approval_type == ApprovalType.SQL

    orchestrator = Orchestrator(approval_callback=lambda req: ApprovalDecision.allow("ok"))
    events = [event async for event in orchestrator.run(graph, context)]

    approval_events = [e for e in events if isinstance(e, ApprovalRequiredEvent)]
    assert approval_events and approval_events[0].request.approval_type == ApprovalType.SQL

    sql_events = [e for e in events if isinstance(e, SQLExecutionEvent)]
    assert sql_events and sql_events[0].sql.lower().startswith("select count")

    completed = [e for e in events if isinstance(e, OrchestrationStepCompletedEvent)]
    result = completed[-1].result
    assert result.rows[0]["total"] == 2
