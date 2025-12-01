---
status: proposed
contact: contributor
date: 2025-05-05
deciders: tbd
consulted:
informed:
---

# Human-in-the-loop configurable multi-agent workflows

## What is the goal of this feature?

- Let developers assemble repeatable, human-auditable multi-agent workflows from user-provided data and task definitions.
- Support heterogeneous data sources (relational DBs, knowledge documents for RAG, MCP servers) and surface live progress and approvals to end users.
- Success metrics: a user can configure a workflow from the UI (name, persona, prompts, knowledge sources, steps), see a machine-proposed plan, approve/adjust it, and run end-to-end with streamed status and results (text + visualizations).

## What is the problem being solved?

- Today, wiring data ingestion + orchestration + approvals is bespoke per use case; users must hardcode schema introspection, vectorization, and tool approval flows.
- SQL workflows often regress without schema-grounded retries or few-shot grounding from successful queries, and RAG/reasoning steps are not coordinated with planner/orchestrator state.
- Teams need a generic framework that can ingest arbitrary user data and adapt to domain-specific workflows while keeping humans in the loop for planning and high-risk tool calls.

## API Changes

### Workflow configuration inputs
- Accept workflow name, persona/system prompts, instructions, knowledge sources (DB path/credentials, knowledge document locations, MCP servers), and ordered workflow steps from the frontend.
- Persist these inputs as orchestrator context so every agent receives the persona, data handles, and user-provided workflow outline.

### Framework-level agents (backed by `ChatAgent` + tools)
- **Planner Agent**:
  - Derives a concrete execution plan from user inputs and available data sources.
  - Uses `approval_mode="always_require"` tools to request human confirmation or clarifications before finalizing the plan.
  - Classifies the workflow intent (e.g., diagnostics vs. fleet analytics) to select templates and relevant tools.
- **Data Retrieval Agent**:
  - Tools for DB metadata (DuckDB/SQLite/Postgres introspection), SQL execution, RAG retrieval against ingested vectors, and MCP tools.
  - Emits normalized payloads (rows, column metadata, citations) for downstream reasoning.
- **SQL Agent (multi-engine: DuckDB, SQLite, Postgres)**:
  - Implements the hybrid RAG + retry loop described by the user across all engines: embed the incoming question, retrieve similar prior SQL with positive feedback, fetch relevant table schemas for the target engine, ask LLM for a query, execute, evaluate correctness, and retry with errors/feedback (up to 3 attempts).
  - For aggregations, auto-request raw rows with `LIMIT` to surface debuggable evidence.
  - Uses `approval_mode="always_require"` for dangerous statements (DDL/DML) and supports a follow-up path that seeds the LLM with recent chat history + prior SQL.
  - Engine selection is driven by workflow configuration; adapters provide consistent tool signatures while handling engine-specific connection details and approval policies (e.g., Postgres DDL always requires approval; DuckDB/SQLite write attempts blocked by default unless explicitly enabled).
- **RAG Agent**:
  - Uses ingested embeddings to retrieve unstructured docs; returns chunk text + citations.
- **Reasoning Agent**:
  - Merges SQL and RAG results, performs math via calculator tools when LLM output includes calculations, and prepares structured findings.
- **Response Generation Agent**:
  - Formats final answers (including visualizations), references source tables/docs, and writes a conversational hand-off to keep chat history consistent.
- **Custom Agents**:
  - Workflow builder can register additional `ChatAgent` instances (e.g., CAN bus decoder, fleet anomaly scorer) with domain-specific tools when base agents are insufficient.

### Data connectors and ingestion
- Provide helper utilities to ingest knowledge docs into the configured vector store and to extract DB schema metadata; store handles in the workflow context for reuse by SQL/RAG agents.
- MCP connections are exposed as tools; approval maps (`always_require_approval` / `never_require_approval`) can be supplied per MCP local name.

### Execution and HIL experience
- Orchestration uses `WorkflowBuilder`/`SequentialBuilder` to wire Planner → SQL/RAG → Reasoning → Response agents.
- `run_stream` output events let the UI stream step-by-step updates; approval-gated tools pause execution until the human responds.
- Orchestrator captures intermediate artifacts (plan, SQL text, query results, RAG citations) for UI playback and debugging.

### Engine-specific SQL behaviors
- **DuckDB**: best for local analytics and joins with Parquet/CSV; default mode blocks writes unless the workflow explicitly enables DML/DDL approvals. Schema tool uses `DESCRIBE`; query tool caps row output for chat display.
- **SQLite**: lightweight edge/local workflows; schema tool uses `PRAGMA table_info`; query tool enforces `LIMIT` for aggregations and keeps a capped rowset for display.
- **Postgres**: remote/production-grade; requires DSN from the UI. All DDL/DML must pass approvals. Schema tool should surface column descriptions if available to strengthen SQL generation grounding.
- All engines share the same hybrid RAG + few-shot + retry policy and aggregation/raw-row fetch pattern; planner chooses the engine-specific tools based on workflow configuration and available handles.

## E2E Code Samples

```python
import asyncio
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Callable, Iterable, List, Optional

import duckdb

from agent_framework import (
    ChatAgent,
    ChatMessage,
    Role,
    SequentialBuilder,
    WorkflowOutputEvent,
    ai_function,
)
from agent_framework.openai import OpenAIChatClient

# Data adapters -------------------------------------------------------------

class Engine(str, Enum):
    DUCKDB = "duckdb"
    SQLITE = "sqlite"
    POSTGRES = "postgres"

@dataclass
class WorkflowConfig:
    workflow_name: str
    persona: str
    sql_engine: Engine
    duckdb_path: str = ":memory:"
    sqlite_path: str = ":memory:"
    postgres_dsn: Optional[str] = None  # supply at runtime for Postgres

# Demo connections (in production, pass pre-authenticated handles from the UI)
duckdb_conn = duckdb.connect(database=":memory:")
duckdb_conn.execute("CREATE TABLE trips(id INTEGER, city VARCHAR, miles DOUBLE, fuel_gal DOUBLE);")
duckdb_conn.execute(
    "INSERT INTO trips VALUES (1, 'Seattle', 12.1, 0.5), (2, 'Portland', 9.4, 0.45);"
)

sqlite_conn = sqlite3.connect(":memory:")
sqlite_conn.execute("CREATE TABLE trips(id INTEGER, city TEXT, miles REAL, fuel_gal REAL);")
sqlite_conn.execute(
    "INSERT INTO trips VALUES (1, 'Seattle', 12.1, 0.5), (2, 'Portland', 9.4, 0.45);"
)
sqlite_conn.commit()

# Postgres is shown as a stub; wire psycopg in production with real credentials.
def postgres_execute(sql: str, dsn: str) -> List[tuple]:
    raise NotImplementedError("Attach a psycopg connection using provided DSN")

# DuckDB tools
@ai_function(name="duckdb_get_schema", description="Return schemas for referenced tables")
def duckdb_get_schema(table: Annotated[str, "Table name"]) -> str:
    return duckdb_conn.execute(f"DESCRIBE {table}").fetch_df().to_markdown(index=False)

@ai_function(name="run_duckdb_query", description="Execute read-only SQL", approval_mode="always_require")
def run_duckdb_query(sql: Annotated[str, "Select statement"]) -> str:
    return duckdb_conn.execute(sql).fetch_df(limit=50).to_markdown(index=False)

# SQLite tools
@ai_function(name="sqlite_get_schema", description="Return schemas for referenced tables")
def sqlite_get_schema(table: Annotated[str, "Table name"]) -> str:
    cursor = sqlite_conn.execute(f"PRAGMA table_info({table})")
    rows = cursor.fetchall()
    header = ["cid", "name", "type", "notnull", "default", "pk"]
    return "\n".join(
        [" | ".join(header)]
        + [
            " | ".join(str(col) for col in row)
            for row in rows
        ]
    )

@ai_function(name="run_sqlite_query", description="Execute read-only SQL", approval_mode="always_require")
def run_sqlite_query(sql: Annotated[str, "Select statement"]) -> str:
    cursor = sqlite_conn.execute(sql)
    rows = cursor.fetchall()
    header = [description[0] for description in cursor.description]
    table_rows = [" | ".join(header)] + [" | ".join(str(col) for col in row) for row in rows[:50]]
    return "\n".join(table_rows)

# Postgres tool stubs
@ai_function(name="postgres_get_schema", description="Return schemas for referenced tables")
def postgres_get_schema(table: Annotated[str, "Table name"], dsn: Annotated[str, "Connection string"]) -> str:
    _ = dsn  # placeholder usage until wired
    raise NotImplementedError("Call psycopg with provided DSN and return column names/types")

@ai_function(name="run_postgres_query", description="Execute read-only SQL", approval_mode="always_require")
def run_postgres_query(sql: Annotated[str, "Select statement"], dsn: Annotated[str, "Connection string"]) -> str:
    _ = dsn
    raise NotImplementedError("Call psycopg with provided DSN and return markdown table")

@ai_function(name="retrieve_docs", description="RAG search over ingested docs")
def retrieve_docs(question: Annotated[str, "User question text"]) -> str:
    # Placeholder: wire to vector store retrieval
    return "[]"  # return JSON or markdown with citations

# Tool selection ------------------------------------------------------------

def sql_tools_for(engine: Engine, config: WorkflowConfig) -> Iterable[Callable]:
    if engine is Engine.DUCKDB:
        return [duckdb_get_schema, run_duckdb_query]
    if engine is Engine.SQLITE:
        return [sqlite_get_schema, run_sqlite_query]
    return [postgres_get_schema, run_postgres_query]

# Agents --------------------------------------------------------------------

def make_planner(config: WorkflowConfig) -> ChatAgent:
    return ChatAgent(
        name="Planner",
        chat_client=OpenAIChatClient(),
        instructions=(
            f"Plan the workflow for {config.workflow_name} using available data (SQL + docs + MCP). "
            "Ask for missing inputs before proceeding. Return an approved plan."
        ),
        tools=[
            *sql_tools_for(config.sql_engine, config),
            # also connect MCP tools with approval maps
        ],
    )

def make_sql_agent(config: WorkflowConfig) -> ChatAgent:
    return ChatAgent(
        name="SQLAgent",
        chat_client=OpenAIChatClient(),
        instructions=(
            "Generate and execute SQL using few-shot examples, schema, and feedback. "
            "Retry up to 3 times with errors or incorrect answers. "
            f"Target engine: {config.sql_engine.value}."
        ),
        tools=list(sql_tools_for(config.sql_engine, config)),
    )

rag_agent = ChatAgent(
    name="RAGAgent",
    chat_client=OpenAIChatClient(),
    instructions="Answer with cited snippets from retrieved docs.",
    tools=[retrieve_docs],
)

reasoner = ChatAgent(
    name="Reasoner",
    chat_client=OpenAIChatClient(),
    instructions=(
        "Combine SQL + RAG evidence. Check for math in the draft answer and call a calculator tool "
        "when needed. Return a concise, cited summary and a follow-up prompt for the user."
    ),
)

# Orchestration -------------------------------------------------------------

def build_workflow(config: WorkflowConfig):
    planner = make_planner(config)
    sql_agent = make_sql_agent(config)
    return SequentialBuilder().participants([
        planner,
        sql_agent,
        rag_agent,
        reasoner,
    ]).build()

async def main() -> None:
    config = WorkflowConfig(
        workflow_name="Fleet Ops Summary",
        persona="Operations analyst",
        sql_engine=Engine.SQLITE,  # swap to Engine.DUCKDB or Engine.POSTGRES per workflow
    )
    workflow = build_workflow(config)
    user_goal = "Summarize average miles per trip and cite any relevant fleet notes."
    async for event in workflow.run_stream(user_goal):
        if isinstance(event, WorkflowOutputEvent):
            print(f"Final answer: {event.data}")
        else:
            print(f"Progress: {event}")

if __name__ == "__main__":
    asyncio.run(main())
```

How this maps to the use case:
- Users configure the workflow (name/persona/prompts/data sources/steps) via the frontend; those values seed the agents above and decide which SQL toolchain (DuckDB/SQLite/Postgres) is attached.
- Planner tools run with `approval_mode="always_require"` so users can confirm plans and risky queries before execution; planner also asks the user for missing DB credentials, MCP endpoints, or doc ingestion status before moving on.
- SQL agent follows the hybrid RAG + retry loop for the selected engine; for aggregations, it can add a second `SELECT ... LIMIT` call to surface raw rows and keep the UI debuggable. DDL/DML always routes through approvals (Postgres requires approval, DuckDB/SQLite writes are blocked unless enabled).
- RAG + Reasoner provide grounded answers; the orchestration stream exposes every step for human-in-the-loop transparency (plan drafts, SQL text/results, cited snippets, and final response payloads/visualizations).
- Custom agents can be registered when the planner detects domain-specific needs (e.g., CAN decoder, anomaly scorer); they are appended to the participant list before building the workflow and inherit the same approval + streaming behaviors.
