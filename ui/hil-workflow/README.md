# HIL Workflow UI

A Next.js UI for configuring and monitoring human-in-the-loop (HIL) agentic workflows. It mirrors the backend orchestration contract (workflow definition + streaming events + approvals) and provides approachable panels for planners, operators, and reviewers.

## Features
- Workflow builder capturing name, persona, goals, SQL engine selection, and knowledge sources (docs, SQL engines, MCP).
- Step composer with recommended agent chain (Planner → SQL → RAG → Reasoner → Responder) plus custom steps.
- Live execution console that streams orchestrator events, approvals, and status updates.
- Approval panel to accept/reject planner/SQL actions, with mock artifacts for visibility.
- Recent run history table to showcase status across engines.

## Running locally (UI only)
## Running locally
```bash
cd ui/hil-workflow
npm install
npm run dev
```

Navigate to `http://localhost:3000` to use the UI. All data is mocked via `lib/mockClient.ts`; wire it to the real orchestrator event stream and workflow creation endpoint when available.

## Wiring to the backend
- Replace `startMockRun` with a client that calls the orchestrator API to create a run, then attaches to Server-Sent Events or WebSockets for streaming updates.
- Forward approval actions to the backend using the run identifier and step metadata returned in approval-request events.
- Populate the run history table from the backend’s run listing endpoint.

## Project layout
- `app/page.tsx`: top-level composition of builder, approvals, execution, and history panels.
- `components/`: reusable UI widgets (event stream, execution console, approvals, history).
- `components/forms/`: workflow capture forms for persona, data sources, and steps.
- `lib/`: shared types plus API + mock clients that simulate orchestrator behavior.
- `lib/`: shared types and the mock client that simulates orchestrator behavior.
- `app/globals.css`: minimal styling inspired by the dark spec screens.

## Notes
- Tailwind is configured but only a handful of utility classes are used; the current styling relies on the shared CSS tokens in `globals.css` for clarity.
- The mock and API clients emit plan → SQL → RAG → Reasoning → Response events and pause for approval before SQL execution to reflect HIL flows.
- The mock client emits plan → SQL → RAG → Reasoning → Response events and pauses for approval before SQL execution to reflect HIL flows.
