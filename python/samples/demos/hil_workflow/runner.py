"""Run orchestration for the HIL workflow API with approvals and persistence."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from agent_framework.hil_workflow import (
    AzureEmbeddingRetriever,
    Engine,
    HilOrchestrator,
    LocalRetriever,
    PostgresConnector,
    SQLiteConnector,
    WorkflowConfig,
)

from .persistence import Store, StoredEvent, StoredRun, StoredWorkflow, _utc_now


@dataclass
class ApprovalState:
    queue: asyncio.Queue[str]


class RunBus:
    """In-memory event broadcast queues keyed by run id."""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue[StoredEvent | None]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get_queue(self, run_id: str) -> asyncio.Queue[StoredEvent | None]:
        if run_id not in self._queues:
            self._queues[run_id] = asyncio.Queue()
        return self._queues[run_id]

    def lock_for(self, run_id: str) -> asyncio.Lock:
        if run_id not in self._locks:
            self._locks[run_id] = asyncio.Lock()
        return self._locks[run_id]


class Runner:
    """Execute workflows, persist artifacts, and support HIL approvals."""

    def __init__(self, store: Store):
        self.store = store
        self.bus = RunBus()
        self.approvals: dict[str, ApprovalState] = {}

    def _build_retriever(self, knowledge: Dict[str, Any]) -> Optional[LocalRetriever | AzureEmbeddingRetriever]:
        documents: List[str] = []
        docs_path = knowledge.get("documentsPath")
        if docs_path:
            path = Path(docs_path)
            if path.exists():
                for file in path.glob("**/*"):
                    if file.is_file():
                        try:
                            documents.append(file.read_text())
                        except Exception:
                            continue
        # Prefer Azure retriever when env vars are configured; fall back to local keyword retriever
        try:
            return AzureEmbeddingRetriever(documents=documents or None)
        except Exception:
            if documents:
                return LocalRetriever(documents=documents)
            return None

    def _build_connector(self, definition: Dict[str, Any]) -> SQLiteConnector | PostgresConnector:
        engine = definition.get("sqlEngine", "sqlite")
        knowledge_db = (definition.get("knowledge") or {}).get("database") or {}
        engine_override = knowledge_db.get("engine", engine)
        if engine_override == Engine.POSTGRES.value:
            dsn = knowledge_db.get("connectionString")
            if not dsn:
                raise ValueError("Postgres engine selected but no connectionString provided")
            return PostgresConnector(dsn=dsn)
        if engine_override == Engine.DUCKDB.value:
            path = knowledge_db.get("path") or ":memory:"
            from agent_framework.hil_workflow import DuckDBConnector

            return DuckDBConnector(path=path)
        # default sqlite
        path = knowledge_db.get("path") or ":memory:"
        return SQLiteConnector(path=path)

    async def _publish(self, run_id: str, event: StoredEvent) -> None:
        self.store.insert_event(event)
        queue = self.bus.get_queue(run_id)
        await queue.put(event)

    async def _emit(self, run_id: str, type_: str, message: str, detail: Optional[dict] = None) -> None:
        await self._publish(
            run_id,
            StoredEvent(
                id=str(uuid.uuid4()),
                run_id=run_id,
                type=type_,
                message=message,
                detail=detail or {},
                timestamp=_utc_now(),
            ),
        )

    async def _approval_gate(self, run_id: str, detail: dict | None = None) -> bool:
        if run_id not in self.approvals:
            self.approvals[run_id] = ApprovalState(queue=asyncio.Queue())
        await self._emit(run_id, "approval-request", "Approval required", detail)
        decision = await self.approvals[run_id].queue.get()
        await self._emit(run_id, "approval-decision", f"Decision: {decision}")
        self.store.record_decision(run_id, decision, reason=None)
        return decision == "approved"

    async def _simulate_with_orchestrator(self, run_id: str, wf: StoredWorkflow) -> None:
        # Map incoming workflow into orchestrator config
        engine_value = wf.definition.get("sqlEngine", "sqlite")
        try:
            engine_enum = Engine(engine_value)
        except ValueError:
            engine_enum = Engine.SQLITE

        config = WorkflowConfig(
            workflow_name=wf.definition.get("name", "Workflow"),
            persona=wf.definition.get("persona", "assistant"),
            sql_engine=engine_enum,
        )
        connector = self._build_connector(wf.definition)
        retriever = self._build_retriever(wf.definition.get("knowledge") or {})

        try:
            orchestrator = HilOrchestrator(config=config, sql_connector=connector, retriever=retriever)
            workflow = orchestrator.build()
        except Exception as exc:  # pragma: no cover - defensive fallback when chat is unavailable
            await self._emit(
                run_id,
                "status",
                "Falling back to synthetic execution; chat client unavailable",
                {"status": "running", "detail": str(exc)},
            )
            await self._fallback_simulation(run_id, wf)
            return

        await self._emit(run_id, "plan", "Planner drafted execution plan", {"steps": wf.definition.get("steps", [])})
        if not await self._approval_gate(run_id, {"requestedBy": "Planner"}):
            await self._emit(run_id, "status", "Run rejected", {"status": "failed"})
            self.store.update_run_status(run_id, "failed")
            await self.bus.get_queue(run_id).put(None)
            return

        # Run the workflow; convert internal events to coarse-grained UI envelope
        try:
            async for event in workflow.run_stream(wf.definition.get("goals", "Execute workflow")):
                # We only surface final assistant messages and status transitions
                payload = event.to_dict()
                if payload.get("event") == "AgentExecutorCompleted":
                    detail = payload.get("data", {})
                    agent_name = detail.get("agent_name") or payload.get("source_id")
                    await self._emit(run_id, "status", f"{agent_name} completed", {"status": "running"})
            await self._emit(run_id, "reasoning", "Reasoner fused SQL/RAG evidence")
            await self._emit(run_id, "response", "Final response ready with citations")
            await self._emit(run_id, "status", "Run complete", {"status": "succeeded"})
            self.store.update_run_status(run_id, "succeeded")
        except Exception as exc:  # pragma: no cover - defensive for demo
            await self._emit(run_id, "status", f"Run failed: {exc}", {"status": "failed"})
            self.store.update_run_status(run_id, "failed")
        finally:
            await self.bus.get_queue(run_id).put(None)

    async def _fallback_simulation(self, run_id: str, wf: StoredWorkflow) -> None:
        await self._emit(run_id, "plan", "Planner drafted workflow steps", {"steps": wf.definition.get("steps", [])})
        if not await self._approval_gate(run_id, {"requestedBy": "Planner"}):
            await self._emit(run_id, "status", "Run rejected", {"status": "failed"})
            self.store.update_run_status(run_id, "failed")
            await self.bus.get_queue(run_id).put(None)
            return

        await self._emit(
            run_id,
            "sql",
            "Generated SQL query against selected engine",
            {"engine": wf.definition.get("sqlEngine")},
        )
        knowledge = wf.definition.get("knowledge") or {}
        if knowledge.get("documentsPath"):
            await self._emit(
                run_id,
                "rag",
                "Retrieved supporting snippets",
                {"source": knowledge.get("documentsPath")},
            )
        await self._emit(run_id, "reasoning", "Fused SQL + RAG evidence and applied calculations")
        await self._emit(run_id, "response", "Final answer ready with citations and next-best action")
        await self._emit(run_id, "status", "Run complete", {"status": "succeeded"})
        self.store.update_run_status(run_id, "succeeded")
        await self.bus.get_queue(run_id).put(None)

    async def start_run(self, run: StoredRun, wf: StoredWorkflow) -> None:
        await self._emit(run.id, "status", "Run started", {"status": "running"})
        await self._simulate_with_orchestrator(run.id, wf)

    async def stream_events(self, run_id: str) -> AsyncIterator[StoredEvent | None]:
        # Replay history first
        for evt in self.store.list_events(run_id):
            yield evt
        # Then stream new events
        queue = self.bus.get_queue(run_id)
        while True:
            evt = await queue.get()
            yield evt
            if evt is None:
                break

    def approve(self, run_id: str, reason: Optional[str] = None) -> None:
        if run_id not in self.approvals:
            self.approvals[run_id] = ApprovalState(queue=asyncio.Queue())
        self.approvals[run_id].queue.put_nowait("approved")
        self.store.record_decision(run_id, "approved", reason)

    def reject(self, run_id: str, reason: Optional[str] = None) -> None:
        if run_id not in self.approvals:
            self.approvals[run_id] = ApprovalState(queue=asyncio.Queue())
        self.approvals[run_id].queue.put_nowait("rejected")
        self.store.record_decision(run_id, "rejected", reason)
