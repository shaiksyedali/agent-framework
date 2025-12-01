# Current change status

## Working tree
- Pending changes add durable SQLite-backed workflow/run/event storage for the HIL FastAPI demo, wire approvals + orchestration through the runner, and refresh the UI to load persisted run history.
- The demo backend now persists RAG documents with embeddings, stores artifacts (plan/SQL/RAG), exposes `/knowledge` and artifact APIs, and adds guarded SQL/RAG probes plus PII-redacted event streaming. UI data-source forms surface validation hints for DB configuration.

## Most recent commit
- Commit: `2d3a539ef74b706667786126f1f19bf180087d94` ("Add HIL workflow scaffolding and roadmap").
- Files changed in that commit:
  - `docs/specs/002-hil-agentic-workflow.md` — added detailed HIL workflow scaffold covering agents and orchestration.
  - `docs/specs/003-workflow-interface-roadmap.md` — documented CLI-first then UI layering roadmap.
  - `python/packages/core/agent_framework/__init__.py` — exported new HIL workflow module.
  - `python/packages/core/agent_framework/hil_workflow.py` — implemented scaffolding with agents, connectors, and orchestrator wiring.
- `python/samples/demos/hil_workflow/README.md` — added usage notes for the demo.
- `python/samples/demos/hil_workflow/hil_workflow.py` — created runnable SQLite-based HIL workflow demo.

## Summary
Use this log to answer "Any files changed?"—there are new in-progress modifications for the HIL backend/UI integration in this working tree.
