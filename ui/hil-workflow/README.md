# HIL Workflow UI

A Next.js UI for configuring and monitoring human-in-the-loop (HIL) agentic workflows. It mirrors the backend orchestration contract (workflow definition + streaming events + approvals) and provides approachable panels for planners, operators, and reviewers.

## Features
- Workflow builder capturing name, persona, goals, SQL engine selection, and knowledge sources (docs, SQL engines, MCP).
- Step composer with recommended agent chain (Planner → SQL → RAG → Reasoner → Responder) plus custom steps.
- Live execution console that streams orchestrator events, approvals, and status updates.
- Approval panel to accept/reject planner/SQL actions, with mock artifacts for visibility.
- Recent run history table to showcase status across engines.

## Running locally (UI only)
```bash
cd ui/hil-workflow
npm install
npm run dev
```

Navigate to `http://localhost:3000` to use the UI. By default all data is mocked via `lib/mockClient.ts`.

## Wiring to the FastAPI backend
Run the sample backend first:
```bash
cd python/samples/demos/hil_workflow
python -m pip install -r requirements.txt
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Then point the UI at it:
```bash
cd ui/hil-workflow
NEXT_PUBLIC_HIL_API_BASE=http://localhost:8000 npm run dev
```

- `lib/apiClient.ts` calls the backend to create workflows/runs and streams events via `text/event-stream`.
- `lib/runClient.ts` automatically falls back to the mock client if the API is unreachable.
- Approval actions call `/runs/{id}/approve` or `/reject`, matching the backend envelope in `python/samples/demos/hil_workflow/server.py`.

## Project layout
- `app/page.tsx`: top-level composition of builder, approvals, execution, and history panels.
- `components/`: reusable UI widgets (event stream, execution console, approvals, history).
- `components/forms/`: workflow capture forms for persona, data sources, and steps.
- `lib/`: shared types plus API + mock clients that simulate orchestrator behavior.
- `app/globals.css`: minimal styling inspired by the dark spec screens.

## Notes
- Tailwind is configured but only a handful of utility classes are used; the current styling relies on the shared CSS tokens in `globals.css` for clarity.
- The mock and API clients emit plan → SQL → RAG → Reasoning → Response events and pause for approval before SQL execution to reflect HIL flows.
