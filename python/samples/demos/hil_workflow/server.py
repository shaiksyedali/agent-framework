"""FastAPI service to expose the HIL workflow sample over HTTP + SSE.

This server is intentionally lightweight and in-memory so the UI can connect to
real endpoints instead of the mock client:

- POST /workflows to create a workflow definition
- POST /runs to start a run for a workflow
- GET  /runs/{run_id}/events to stream orchestration progress (text/event-stream)
- POST /runs/{run_id}/approve or /reject to unblock HIL pauses

The event envelope mirrors ui/hil-workflow/lib/types.ts so the Next.js demo can
render real runs with approvals. This stub emits synthetic events; wire your
`HilOrchestrator` in place of ``simulate_run`` to drive production flows.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeSources(BaseModel):
    documentsPath: Optional[str] = None
    database: Optional[dict] = None
    mcpServer: Optional[str] = None


class WorkflowStep(BaseModel):
    id: str
    title: str
    description: str
    agent: str
    requiresApproval: bool | None = False


class WorkflowDefinition(BaseModel):
    name: str
    persona: str
    goals: str
    knowledge: KnowledgeSources
    steps: List[WorkflowStep]
    sqlEngine: str


class RunRecord(BaseModel):
    id: str
    workflowName: str
    startedAt: str
    status: str
    engine: str


class EventEnvelope(BaseModel):
    id: str
    type: str
    message: str
    detail: dict | None = None
    timestamp: str


class RunCreateRequest(BaseModel):
    workflowId: str


class DecisionPayload(BaseModel):
    reason: str | None = None


@dataclass
class RunState:
    record: RunRecord
    queue: asyncio.Queue[Optional[EventEnvelope]] = field(default_factory=asyncio.Queue)
    approval: asyncio.Queue[str] = field(default_factory=asyncio.Queue)


WORKFLOWS: Dict[str, WorkflowDefinition] = {}
RUNS: Dict[str, RunState] = {}

app = FastAPI(title="HIL Workflow Sample API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _publish(state: RunState, *, type_: str, message: str, detail: Optional[dict] = None) -> None:
    event = EventEnvelope(id=str(uuid.uuid4()), type=type_, message=message, detail=detail or {}, timestamp=_utc_now())
    await state.queue.put(event)


async def simulate_run(state: RunState, definition: WorkflowDefinition) -> None:
    try:
        await _publish(state, type_="status", message="Run started", detail={"status": "running"})
        await _publish(
            state,
            type_="plan",
            message="Planner drafted workflow steps",
            detail={"steps": [step.title for step in definition.steps]},
        )
        await _publish(
            state,
            type_="approval-request",
            message="Approve execution of the planned SQL + RAG steps?",
            detail={"requestedBy": "Planner"},
        )

        decision = await state.approval.get()
        await _publish(state, type_="approval-decision", message=f"Decision: {decision}")
        if decision != "approved":
            state.record.status = "failed"
            await _publish(state, type_="status", message="Run rejected", detail={"status": "failed"})
            await state.queue.put(None)
            return

        await _publish(
            state,
            type_="sql",
            message="Generated SQL query against selected engine",
            detail={"engine": definition.sqlEngine},
        )
        if definition.knowledge.documentsPath:
            await _publish(
                state,
                type_="rag",
                message="Retrieved supporting snippets",
                detail={"source": definition.knowledge.documentsPath},
            )
        await _publish(state, type_="reasoning", message="Fused SQL + RAG evidence and applied calculations")
        await _publish(state, type_="response", message="Final answer ready with citations and next-best action")

        state.record.status = "succeeded"
        await _publish(state, type_="status", message="Run complete", detail={"status": "succeeded"})
    except asyncio.CancelledError:  # pragma: no cover - sample server
        state.record.status = "failed"
        await _publish(state, type_="status", message="Run cancelled", detail={"status": "failed"})
    finally:
        await state.queue.put(None)


@app.post("/workflows", response_model=dict)
async def create_workflow(definition: WorkflowDefinition):
    workflow_id = str(uuid.uuid4())
    WORKFLOWS[workflow_id] = definition
    return {"id": workflow_id, "definition": definition}


@app.get("/workflows", response_model=dict)
async def list_workflows():
    return {"items": [{"id": wf_id, "definition": definition} for wf_id, definition in WORKFLOWS.items()]}


@app.post("/runs", response_model=RunRecord)
async def create_run(payload: RunCreateRequest):
    definition = WORKFLOWS.get(payload.workflowId)
    if not definition:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_id = str(uuid.uuid4())
    record = RunRecord(
        id=run_id,
        workflowName=definition.name,
        startedAt=_utc_now(),
        status="running",
        engine=definition.sqlEngine,
    )
    state = RunState(record=record)
    RUNS[run_id] = state
    asyncio.create_task(simulate_run(state, definition))
    return record


@app.get("/runs", response_model=dict)
async def list_runs():
    return {"items": [state.record for state in RUNS.values()]}


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str):
    state = RUNS.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator() -> AsyncIterator[bytes]:
        while True:
            event = await state.queue.get()
            if event is None:
                break
            payload = json.dumps(event.model_dump())
            yield f"data: {payload}\n\n".encode()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str, payload: DecisionPayload):
    state = RUNS.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    await state.approval.put("approved")
    return {"status": "ok", "reason": payload.reason}


@app.post("/runs/{run_id}/reject")
async def reject_run(run_id: str, payload: DecisionPayload):
    state = RUNS.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    state.record.status = "failed"
    await state.approval.put("rejected")
    return {"status": "ok", "reason": payload.reason}
