"""FastAPI service exposing the HIL workflow sample with durable storage and SSE."""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import AsyncIterator, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .persistence import Store, StoredEvent, StoredRun, _utc_now
from .runner import Runner


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


# SQLite-backed persistence layer and orchestrated runner
DB_PATH = Path(__file__).parent / "data" / "hil_api.db"
store = Store(DB_PATH)
runner = Runner(store)

app = FastAPI(title="HIL Workflow Sample API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _stored_to_record(run: StoredRun) -> RunRecord:
    return RunRecord(
        id=run.id,
        workflowName=run.workflow_name,
        startedAt=run.started_at,
        status=run.status,
        engine=run.engine,
    )


def _stored_event_to_envelope(event: StoredEvent) -> EventEnvelope:
    return EventEnvelope(
        id=event.id,
        type=event.type,
        message=event.message,
        detail=event.detail,
        timestamp=event.timestamp,
    )


@app.post("/workflows", response_model=dict)
async def create_workflow(definition: WorkflowDefinition):
    workflow_id = str(uuid.uuid4())
    store.create_workflow(workflow_id, definition.model_dump())
    return {"id": workflow_id, "definition": definition}


@app.get("/workflows", response_model=dict)
async def list_workflows():
    return {"items": [{"id": wf.id, "definition": wf.definition} for wf in store.list_workflows()]}


@app.post("/runs", response_model=RunRecord)
async def create_run(payload: RunCreateRequest):
    workflow = store.get_workflow(payload.workflowId)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_id = str(uuid.uuid4())
    run = StoredRun(
        id=run_id,
        workflow_id=workflow.id,
        workflow_name=workflow.definition.get("name", "Workflow"),
        started_at=_utc_now(),
        status="running",
        engine=workflow.definition.get("sqlEngine", "sqlite"),
    )
    store.create_run(run)
    asyncio.create_task(runner.start_run(run, workflow))
    return _stored_to_record(run)


@app.get("/runs", response_model=dict)
async def list_runs():
    return {"items": [_stored_to_record(run) for run in store.list_runs()]}


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str):
    # Validate run existence
    found = [r for r in store.list_runs() if r.id == run_id]
    if not found:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator() -> AsyncIterator[bytes]:
        async for event in runner.stream_events(run_id):
            if event is None:
                break
            payload = json.dumps(_stored_event_to_envelope(event).model_dump())
            yield f"data: {payload}\n\n".encode()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str, payload: DecisionPayload):
    if not any(r.id == run_id for r in store.list_runs()):
        raise HTTPException(status_code=404, detail="Run not found")
    runner.approve(run_id, payload.reason)
    return {"status": "ok", "reason": payload.reason}


@app.post("/runs/{run_id}/reject")
async def reject_run(run_id: str, payload: DecisionPayload):
    if not any(r.id == run_id for r in store.list_runs()):
        raise HTTPException(status_code=404, detail="Run not found")
    runner.reject(run_id, payload.reason)
    store.update_run_status(run_id, "failed")
    return {"status": "ok", "reason": payload.reason}
