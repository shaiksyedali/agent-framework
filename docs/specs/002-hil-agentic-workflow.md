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
  - Tools for DB metadata (`duckdb`/`sqlite` introspection), SQL execution, RAG retrieval against ingested vectors, and MCP tool calls.
  - Emits normalized payloads (rows, column metadata, citations) for downstream reasoning.
- **SQL Agent (DuckDB-grounded)**:
  - Implements the hybrid RAG + retry loop described by the user: embed the incoming question, retrieve similar prior SQL with positive feedback, fetch relevant table schemas, ask LLM for a query, execute in DuckDB, evaluate correctness, and retry with errors/feedback (up to 3 attempts).
  - For aggregations, auto-request raw rows with `LIMIT` to surface debuggable evidence.
  - Uses `approval_mode="always_require"` for dangerous statements (DDL/DML) and supports a follow-up path that seeds the LLM with recent chat history + prior SQL.
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

## E2E Code Samples

```python
import asyncio
import duckdb
from pathlib import Path
from typing import Annotated

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

db = duckdb.connect(database=":memory:")
db.execute("CREATE TABLE trips(id INTEGER, city VARCHAR, miles DOUBLE, fuel_gal DOUBLE);")
db.execute("INSERT INTO trips VALUES (1, 'Seattle', 12.1, 0.5), (2, 'Portland', 9.4, 0.45);")

@ai_function(name="get_schema", description="Return schemas for referenced tables")
def get_schema(table: Annotated[str, "Table name"]) -> str:
    return db.execute(f"DESCRIBE {table}").fetch_df().to_markdown(index=False)

@ai_function(name="run_duckdb_query", description="Execute read-only SQL", approval_mode="always_require")
def run_duckdb_query(sql: Annotated[str, "Select statement"]) -> str:
    return db.execute(sql).fetch_df(limit=50).to_markdown(index=False)

@ai_function(name="retrieve_docs", description="RAG search over ingested docs")
def retrieve_docs(question: Annotated[str, "User question text"]) -> str:
    # Placeholder: wire to vector store retrieval
    return "[]"  # return JSON or markdown with citations

# Agents --------------------------------------------------------------------

planner = ChatAgent(
    name="Planner",
    chat_client=OpenAIChatClient(),
    instructions=(
        "Plan the workflow using available data (DuckDB + docs + MCP). "
        "Ask for missing inputs before proceeding. Return an approved plan."
    ),
    tools=[get_schema],  # also connect MCP tools with approval maps
)

sql_agent = ChatAgent(
    name="SQLAgent",
    chat_client=OpenAIChatClient(),
    instructions=(
        "Generate and execute DuckDB SQL using few-shot examples, schema, and feedback. "
        "Retry up to 3 times with errors or incorrect answers."
    ),
    tools=[get_schema, run_duckdb_query],
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

workflow = SequentialBuilder().participants([
    planner,
    sql_agent,
    rag_agent,
    reasoner,
]).build()

async def main() -> None:
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
- Users configure the workflow (name/persona/prompts/data sources/steps) via the frontend; those values seed the agents above.
- Planner tools run with `approval_mode="always_require"` so users can confirm plans and risky queries before execution.
- SQL agent follows the hybrid RAG + DuckDB loop with retries; for aggregations, it can add a second `SELECT ... LIMIT` call to surface raw rows.
- RAG + Reasoner provide grounded answers; the orchestration stream exposes every step for human-in-the-loop transparency.
