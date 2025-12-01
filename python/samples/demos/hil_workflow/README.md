# Human-in-the-loop agentic workflow demo

This demo wires together the planner, SQL, RAG, reasoning, and response agents described in the HIL workflow spec. It ships with a SQLite-backed sample so you can run it without external services, while still supporting DuckDB or Postgres connectors if installed.

## Prerequisites
- Python 3.10+
- `pip install -e python/packages/core` (from the repo root)
- Azure OpenAI credentials (preferred) using the same variables the framework reads:
  - `AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/`
  - `AZURE_OPENAI_API_KEY=<key>`
  - `AZURE_OPENAI_DEPLOYMENT=<chat deployment>` (or `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`)
  - `AZURE_OPENAI_API_VERSION=2025-01-01-preview`
  - `AZURE_EMBED_DEPLOYMENT=text-embedding-3-small` for the RAG retriever
- OpenAI-compatible chat model credentials (e.g., `OPENAI_API_KEY`) if you want to fall back to the non-Azure path
- Optional: `duckdb` and/or `psycopg[binary]` if you want to switch engines

## Run the streaming console demo
```bash
cd python/samples/demos/hil_workflow
python hil_workflow.py
```

Expected behavior: the workflow streams events for plan, SQL, RAG retrieval, reasoning, and the final formatted response. SQL and other tools run under the configured `approval_mode`, so you can integrate the events with a UI that pauses for human confirmation.

Azure OpenAI is the default LLM and embedding provider for this sample. If the Azure env vars are set, the Planner/SQL/RAG/Reasoner agents will use `AzureOpenAIChatClient`, and the RAG retriever will embed docs with `AZURE_EMBED_DEPLOYMENT`. When the variables are absent, the demo falls back to a lightweight in-process keyword retriever so the streaming sample still runs offline.

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

The server now persists workflows, runs, events, and approval decisions to `python/samples/demos/hil_workflow/data/hil_api.db` so you can:
- Restart the server and replay past events in the UI
- Keep a run history without relying on in-memory state
- Stream live updates after the historical replay
