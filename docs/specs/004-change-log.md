# Current change status

## Working tree
- Pending changes extend the HIL demo with a FastAPI backend and hook the Next.js UI to real streaming events (with mock fallback).

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
