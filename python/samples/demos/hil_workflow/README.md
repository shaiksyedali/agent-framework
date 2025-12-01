# Human-in-the-loop agentic workflow demo

This demo wires together the planner, SQL, RAG, reasoning, and response agents described in the HIL workflow spec. It ships with a SQLite-backed sample so you can run it without external services, while still supporting DuckDB or Postgres connectors if installed.

## Prerequisites
- Python 3.10+
- `pip install -e python/packages/core` (from the repo root)
- OpenAI-compatible chat model credentials (e.g., `OPENAI_API_KEY`) if you want to run the `hil_workflow.py` streaming sample
- Optional: `duckdb` and/or `psycopg[binary]` if you want to switch engines

## Run the streaming console demo
```bash
cd python/samples/demos/hil_workflow
python hil_workflow.py
```

Expected behavior: the workflow streams events for plan, SQL, RAG retrieval, reasoning, and the final formatted response. SQL and other tools run under the configured `approval_mode`, so you can integrate the events with a UI that pauses for human confirmation.

## Run the lightweight API server (for the Next.js UI)
The UI demo can talk to a real backend using a small FastAPI service that mirrors the event envelope expected by `ui/hil-workflow`.

```bash
cd python/samples/demos/hil_workflow
python -m pip install -r requirements.txt
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

The server exposes:
- `POST /workflows` to register a workflow definition
- `POST /runs` to start a run for a workflow
- `GET  /runs/{run_id}/events` to stream events via `text/event-stream`
- `POST /runs/{run_id}/approve` or `/reject` to respond to approvals

Events use the same shape as `ui/hil-workflow/lib/types.ts` so the UI can render plan/SQL/RAG/reasoning/response updates with HIL pauses.
