"""FastAPI service exposing the HIL workflow sample with durable storage and SSE."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .knowledge import IngestDocument, VectorStore
from .persistence import Store, StoredApproval, StoredEvent, StoredRun, _utc_now
from .runner import Runner

logger = logging.getLogger(__name__)


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


class ApprovalRecord(BaseModel):
    id: str
    decision: str
    reason: str | None = None
    timestamp: str


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


class IngestDocumentPayload(BaseModel):
    id: Optional[str] = None
    text: str
    metadata: dict | None = None


class KnowledgeIngestRequest(BaseModel):
    workflowId: str
    documents: List[IngestDocumentPayload]


# SQLite-backed persistence layer and orchestrated runner
DB_PATH = Path(__file__).parent / "data" / "hil_api.db"
store = Store(DB_PATH)
vectors = VectorStore(store)
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


def _stored_approval_to_record(approval: StoredApproval) -> ApprovalRecord:
    return ApprovalRecord(
        id=approval.id,
        decision=approval.decision,
        reason=approval.reason,
        timestamp=approval.timestamp,
    )


def _ingest_from_definition(workflow_id: str, definition: dict) -> int:
    knowledge = definition.get("knowledge") or {}
    docs_path = knowledge.get("documentsPath")
    if not docs_path:
        return 0
    path = Path(docs_path)
    if not path.exists():
        return 0
    documents: List[IngestDocument] = []
    for idx, file in enumerate(path.glob("**/*")):
        if file.is_file():
            try:
                documents.append(IngestDocument(id=f"{workflow_id}:{idx}", text=file.read_text()))
            except Exception as exc:  # pragma: no cover - defensive for unreadable files
                logger.warning("Skipping unreadable document %s: %s", file, exc)
    if not documents:
        return 0
    return vectors.ingest(workflow_id, documents)


@app.post("/workflows", response_model=dict)
async def create_workflow(definition: WorkflowDefinition):
    workflow_id = str(uuid.uuid4())
    store.create_workflow(workflow_id, definition.model_dump())
    _ingest_from_definition(workflow_id, definition.model_dump())
    return {"id": workflow_id, "definition": definition}


@app.get("/workflows", response_model=dict)
async def list_workflows():
    return {"items": [{"id": wf.id, "definition": wf.definition} for wf in store.list_workflows()]}


@app.get("/workflows/{workflow_id}", response_model=dict)
async def get_workflow(workflow_id: str):
    wf = store.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    docs = store.list_documents(workflow_id)
    return {"id": wf.id, "definition": wf.definition, "documents": len(docs)}


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


@app.post("/knowledge", response_model=dict)
async def ingest_knowledge(payload: KnowledgeIngestRequest):
    workflow = store.get_workflow(payload.workflowId)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    docs = [
        IngestDocument(id=doc.id or f"{payload.workflowId}:{idx}", text=doc.text, metadata=doc.metadata)
        for idx, doc in enumerate(payload.documents)
    ]
    count = vectors.ingest(payload.workflowId, docs)
    return {"ingested": count}


@app.get("/runs", response_model=dict)
async def list_runs():
    return {"items": [_stored_to_record(run) for run in store.list_runs()]}


@app.get("/runs/{run_id}", response_model=dict)
async def get_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    approvals = [_stored_approval_to_record(a) for a in store.list_approvals(run_id)]
    return {"run": _stored_to_record(run), "approvals": approvals}


@app.get("/runs/{run_id}/artifacts", response_model=dict)
async def list_artifacts(run_id: str):
    if not store.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    artifacts = store.list_artifacts(run_id)
    return {"items": [artifact.__dict__ for artifact in artifacts]}


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str, since: str | None = None):
    # Validate run existence
    if not store.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator() -> AsyncIterator[bytes]:
        async for event in runner.stream_events(run_id, since=since):
            if event is None:
                break
            payload = json.dumps(_stored_event_to_envelope(event).model_dump())
            yield f"data: {payload}\n\n".encode()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.websocket("/runs/{run_id}/events/ws")
async def websocket_events(websocket: WebSocket, run_id: str, since: str | None = None):
    run = store.get_run(run_id)
    if not run:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        # Replay history
        for event in store.list_events_since(run_id, after_event_id=since):
            await websocket.send_json(_stored_event_to_envelope(event).model_dump())
        # Stream live events
        queue = runner.bus.subscribe(run_id)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    await websocket.send_json({"type": "complete", "runId": run_id})
                    break
                await websocket.send_json(_stored_event_to_envelope(event).model_dump())
        finally:
            runner.bus.unsubscribe(run_id, queue)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for run %s", run_id)
    except Exception as exc:  # pragma: no cover - runtime protection
        logger.exception("WebSocket error for run %s: %s", run_id, exc)
        await websocket.close(code=1011)


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str, payload: DecisionPayload):
    if not store.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    runner.approve(run_id, payload.reason)
    return {"status": "ok", "reason": payload.reason}


@app.post("/runs/{run_id}/reject")
async def reject_run(run_id: str, payload: DecisionPayload):
    if not store.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    runner.reject(run_id, payload.reason)
    store.update_run_status(run_id, "failed")
    return {"status": "ok", "reason": payload.reason}


@app.get("/runs/{run_id}/approvals", response_model=dict)
async def list_approvals(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    approvals = [_stored_approval_to_record(a).model_dump() for a in store.list_approvals(run_id)]
    return {"items": approvals, "run": _stored_to_record(run)}
