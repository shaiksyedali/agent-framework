# Human-in-the-loop agentic workflow demo

This demo wires together the planner, SQL, RAG, reasoning, and response agents described in the HIL workflow spec. It ships with a SQLite-backed sample so you can run it without external services, while still supporting DuckDB or Postgres connectors if installed.

## Prerequisites
- Python 3.10+
- `pip install -e python/packages/core` (from the repo root)
- OpenAI-compatible chat model credentials (e.g., `OPENAI_API_KEY`)
- Optional: `duckdb` and/or `psycopg[binary]` if you want to switch engines

## Run the demo
```bash
cd python/samples/demos/hil_workflow
python hil_workflow.py
```

Expected behavior: the workflow streams events for plan, SQL, RAG retrieval, reasoning, and the final formatted response. SQL and other tools run under the configured `approval_mode`, so you can integrate the events with a UI that pauses for human confirmation.
