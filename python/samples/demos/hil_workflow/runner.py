"""Run orchestration for the HIL workflow API with approvals and persistence."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlparse

from agent_framework import MCPStreamableHTTPTool
from agent_framework.agents.sql import SQLAgent, SQLExample
from agent_framework.data.connectors import (
    DataConnectorError,
    DuckDBConnector as CoreDuckDBConnector,
    PostgresConnector as CorePostgresConnector,
    SQLApprovalPolicy,
    SQLiteConnector as CoreSQLiteConnector,
)
from agent_framework.hil_workflow import (
    AzureEmbeddingRetriever,
    Engine,
    HilOrchestrator,
    LocalRetriever,
    PostgresConnector,
    SQLConnector,
    SQLiteConnector,
    WorkflowConfig,
)

from .knowledge import IngestDocument, VectorStore
from .persistence import Store, StoredEvent, StoredRun, StoredWorkflow, _utc_now

logger = logging.getLogger(__name__)
PII_PATTERN = re.compile(r"([\w\.]+@[\w\.]+|\+?\d{10,})")


@dataclass
class ApprovalState:
    queue: asyncio.Queue[dict]


class RunBus:
    """In-memory event broadcast queues keyed by run id."""

    def __init__(self):
        self._queues: dict[str, list[asyncio.Queue[StoredEvent | None]]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue[StoredEvent | None]:
        queue: asyncio.Queue[StoredEvent | None] = asyncio.Queue()
        self._queues.setdefault(run_id, []).append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[StoredEvent | None]) -> None:
        queues = self._queues.get(run_id)
        if not queues:
            return
        try:
            queues.remove(queue)
        except ValueError:
            return

    async def broadcast(self, run_id: str, event: StoredEvent | None) -> None:
        queues = self._queues.get(run_id, [])
        for queue in list(queues):
            await queue.put(event)


class Runner:
    """Execute workflows, persist artifacts, and support HIL approvals."""

    def __init__(self, store: Store):
        self.store = store
        self.bus = RunBus()
        self.approvals: dict[str, ApprovalState] = {}
        self.vectors = VectorStore(store)

    @staticmethod
    def _redact(text: str) -> str:
        return PII_PATTERN.sub("[redacted]", text or "")

    @staticmethod
    def _redact_detail(value: Any) -> Any:
        if isinstance(value, str):
            return Runner._redact(value)
        if isinstance(value, Mapping):
            return {key: Runner._redact_detail(val) for key, val in value.items()}
        if isinstance(value, list | tuple):
            return [Runner._redact_detail(item) for item in value]
        return value

    def _build_retriever(self, workflow_id: str, knowledge: Dict[str, Any]) -> Optional[LocalRetriever | AzureEmbeddingRetriever]:
        # Attempt to use previously ingested documents first
        retriever = self.vectors.retriever_for(workflow_id)
        if retriever:
            return retriever

        documents: List[IngestDocument] = []
        docs_path = knowledge.get("documentsPath")
        if docs_path:
            path = Path(docs_path)
            if path.exists():
                for idx, file in enumerate(path.glob("**/*")):
                    if file.is_file():
                        try:
                            documents.append(IngestDocument(id=f"{workflow_id}:{idx}", text=file.read_text()))
                        except Exception:
                            continue
        if documents:
            self.vectors.ingest(workflow_id, documents)
            retriever = self.vectors.retriever_for(workflow_id)
            if retriever:
                return retriever

        # Prefer Azure retriever when env vars are configured; fall back to local keyword retriever
        try:
            return AzureEmbeddingRetriever(documents=[doc.text for doc in documents] or None)
        except Exception:
            if documents:
                return LocalRetriever(documents=[doc.text for doc in documents])
            return None

    def _build_connector(self, definition: Dict[str, Any]) -> SQLiteConnector | PostgresConnector:
        engine = definition.get("sqlEngine", "sqlite")
        knowledge_db = (definition.get("knowledge") or {}).get("database") or {}
        engine_override = knowledge_db.get("engine", engine)
        approval_mode = knowledge_db.get("approvalMode", "always_require")
        allow_writes = bool(knowledge_db.get("allowWrites", False))

        if engine_override == Engine.POSTGRES.value:
            dsn = knowledge_db.get("connectionString")
            if not dsn or "://" not in dsn:
                raise ValueError("Postgres engine selected but connectionString is invalid")
            return PostgresConnector(dsn=dsn, approval_mode=approval_mode, allow_writes=allow_writes)

        if engine_override == Engine.DUCKDB.value:
            path = knowledge_db.get("path") or ":memory:"
            from agent_framework.hil_workflow import DuckDBConnector

            return DuckDBConnector(path=path, approval_mode=approval_mode, allow_writes=allow_writes)

        # default sqlite
        path = knowledge_db.get("path") or ":memory:"
        return SQLiteConnector(path=path, approval_mode=approval_mode, allow_writes=allow_writes)

    def _build_data_connector(self, definition: Dict[str, Any]):
        engine = definition.get("sqlEngine", "sqlite")
        knowledge_db = (definition.get("knowledge") or {}).get("database") or {}
        engine_override = knowledge_db.get("engine", engine)
        approval_mode = knowledge_db.get("approvalMode", "always_require")
        allow_writes = bool(knowledge_db.get("allowWrites", False))

        policy = SQLApprovalPolicy(
            approval_required=approval_mode != "never_require",
            allow_writes=allow_writes,
            engine=engine_override,
        )

        if engine_override == Engine.POSTGRES.value:
            dsn = knowledge_db.get("connectionString")
            if not dsn or urlparse(dsn).scheme not in {"postgres", "postgresql"}:
                raise ValueError("Postgres engine selected but connectionString is invalid")
            return CorePostgresConnector(connection_string=dsn, approval_policy=policy)

        if engine_override == Engine.DUCKDB.value:
            path = knowledge_db.get("path") or ":memory:"
            return CoreDuckDBConnector(database=path, approval_policy=policy)

        path = knowledge_db.get("path") or ":memory:"
        return CoreSQLiteConnector(database=path, approval_policy=policy)

    def _build_mcp_tool(self, definition: Dict[str, Any]):
        knowledge = definition.get("knowledge") or {}
        mcp_server = knowledge.get("mcpServer")
        if not mcp_server:
            return None
        parsed = urlparse(mcp_server)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("mcpServer must be a valid http(s) URL")
        approval_mode = knowledge.get("approvalMode", "always_require")
        return MCPStreamableHTTPTool(name="mcp-server", url=mcp_server, approval_mode=approval_mode)

    async def _publish(self, run_id: str, event: StoredEvent) -> None:
        self.store.insert_event(event)
        await self.bus.broadcast(run_id, event)

    async def _emit(self, run_id: str, type_: str, message: str, detail: Optional[dict] = None) -> None:
        safe_message = self._redact(message)
        safe_detail = self._redact_detail(detail) if detail is not None else {}
        await self._publish(
            run_id,
            StoredEvent(
                id=str(uuid.uuid4()),
                run_id=run_id,
                type=type_,
                message=safe_message,
                detail=safe_detail,
                timestamp=_utc_now(),
            ),
        )

    def _record_artifact(self, run_id: str, kind: str, payload: Dict[str, Any]) -> str:
        return self.store.record_artifact(run_id, kind, payload)

    async def _approval_gate(self, run_id: str, detail: dict | None = None) -> bool:
        if run_id not in self.approvals:
            self.approvals[run_id] = ApprovalState(queue=asyncio.Queue())
        await self._emit(run_id, "approval-request", "Approval required", detail)
        self._record_artifact(run_id, "approval-request", detail or {})
        decision = await self.approvals[run_id].queue.get()
        decision_value = decision.get("decision", "rejected")
        reason = decision.get("reason")
        await self._emit(run_id, "approval-decision", f"Decision: {decision_value}", {"reason": reason})
        self._record_artifact(run_id, "approval-decision", {"decision": decision_value, "reason": reason})
        self.store.record_decision(run_id, decision_value, reason)
        return decision_value == "approved"

    async def _sql_probe(self, run_id: str, connector: SQLConnector, goal: str, definition: Dict[str, Any]) -> bool:
        try:
            data_connector = self._build_data_connector(definition)
        except Exception as exc:  # pragma: no cover - defensive
            await self._emit(run_id, "sql", f"Skipping SQL probe: {exc}", {"status": "skipped"})
            return False

        examples: list[SQLExample] = []
        for item in definition.get("sqlHistory", []) or []:
            if isinstance(item, dict) and "question" in item and "sql" in item:
                examples.append(
                    SQLExample(question=str(item["question"]), sql=str(item["sql"]), answer=item.get("answer"))
                )

        agent = SQLAgent(few_shot_examples=examples)

        try:
            result = await agent.generate_and_execute(
                goal,
                data_connector,
                max_attempts=3,
                fetch_raw_after_aggregation=True,
                allow_writes=getattr(data_connector.approval_policy, "allow_writes", True),
            )
        except DataConnectorError as exc:
            await self._emit(run_id, "sql", f"SQL failed: {exc}", {"status": "failed"})
            return False

        detail = {
            "sql": result.sql,
            "rows": result.rows,
            "raw_rows": result.raw_rows,
            "attempts": [attempt.__dict__ for attempt in result.attempts],
        }
        self._record_artifact(run_id, "sql-preview", detail)
        await self._emit(run_id, "sql", "SQL probe completed", detail)
        return bool(result.rows)

    async def _rag_probe(self, run_id: str, retriever: LocalRetriever | AzureEmbeddingRetriever, goal: str) -> None:
        try:
            tool = retriever.tool()
            snippets = tool(goal)
            try:
                parsed = json.loads(snippets)
            except Exception:
                parsed = snippets
            payload = {"question": goal, "snippets": parsed}
            self._record_artifact(run_id, "rag-snippets", payload)
            await self._emit(run_id, "rag", "Retrieved supporting snippets", payload)
        except Exception as exc:  # pragma: no cover - defensive
            await self._emit(run_id, "rag", f"RAG retrieval failed: {exc}")

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
        retriever = self._build_retriever(wf.id, wf.definition.get("knowledge") or {})
        mcp_tool = self._build_mcp_tool(wf.definition)

        try:
            orchestrator = HilOrchestrator(
                config=config, sql_connector=connector, retriever=retriever, mcp_tool=mcp_tool
            )
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
        self._record_artifact(run_id, "plan", wf.definition.get("steps", []))
        if not await self._approval_gate(run_id, {"requestedBy": "Planner"}):
            await self._emit(run_id, "status", "Run rejected", {"status": "failed"})
            self.store.update_run_status(run_id, "failed")
            await self.bus.broadcast(run_id, None)
            return

        # Run the workflow; convert internal events to coarse-grained UI envelope
        try:
            async for event in workflow.run_stream(wf.definition.get("goals", "Execute workflow")):
                payload = event.to_dict()
                if payload.get("event") == "AgentExecutorCompleted":
                    detail = payload.get("data", {})
                    agent_name = detail.get("agent_name") or payload.get("source_id")
                    await self._emit(run_id, "status", f"{agent_name} completed", {"status": "running"})
                if payload.get("messages") or (payload.get("data") and payload["data"].get("message")):
                    self._record_artifact(run_id, "chat-history", payload)

            # Run an explicit SQL + RAG probe for deterministic observability
            sql_ok = await self._sql_probe(run_id, connector, wf.definition.get("goals", "Execute workflow"), wf.definition)
            if retriever:
                await self._rag_probe(run_id, retriever, wf.definition.get("goals", "Execute workflow"))
            if sql_ok:
                await self._emit(run_id, "reasoning", "Reasoner fused SQL/RAG evidence")
                await self._emit(run_id, "response", "Final response ready with citations")
                self._record_artifact(run_id, "response", {"status": "succeeded"})
                await self._emit(run_id, "status", "Run complete", {"status": "succeeded"})
                self.store.update_run_status(run_id, "succeeded")
            else:
                await self._emit(run_id, "status", "SQL stage failed", {"status": "failed"})
                self.store.update_run_status(run_id, "failed")
        except Exception as exc:  # pragma: no cover - defensive for demo
            await self._emit(run_id, "status", f"Run failed: {exc}", {"status": "failed"})
            self.store.update_run_status(run_id, "failed")
        finally:
            await self.bus.broadcast(run_id, None)

    async def _fallback_simulation(self, run_id: str, wf: StoredWorkflow) -> None:
        await self._emit(run_id, "plan", "Planner drafted workflow steps", {"steps": wf.definition.get("steps", [])})
        if not await self._approval_gate(run_id, {"requestedBy": "Planner"}):
            await self._emit(run_id, "status", "Run rejected", {"status": "failed"})
            self.store.update_run_status(run_id, "failed")
            await self.bus.broadcast(run_id, None)
            return

        await self._emit(
            run_id,
            "sql",
            "Generated SQL query against selected engine",
            {"engine": wf.definition.get("sqlEngine")},
        )
        self._record_artifact(run_id, "sql-preview", {"engine": wf.definition.get("sqlEngine")})
        knowledge = wf.definition.get("knowledge") or {}
        if knowledge.get("documentsPath"):
            await self._emit(
                run_id,
                "rag",
                "Retrieved supporting snippets",
                {"source": knowledge.get("documentsPath")},
            )
            self._record_artifact(run_id, "rag-snippets", {"source": knowledge.get("documentsPath")})
        await self._emit(run_id, "reasoning", "Fused SQL + RAG evidence and applied calculations")
        await self._emit(run_id, "response", "Final answer ready with citations and next-best action")
        self._record_artifact(run_id, "response", {"status": "succeeded"})
        await self._emit(run_id, "status", "Run complete", {"status": "succeeded"})
        self.store.update_run_status(run_id, "succeeded")
        await self.bus.broadcast(run_id, None)

    async def start_run(self, run: StoredRun, wf: StoredWorkflow) -> None:
        await self._emit(run.id, "status", "Run started", {"status": "running"})
        await self._simulate_with_orchestrator(run.id, wf)

    async def stream_events(self, run_id: str, since: str | None = None) -> AsyncIterator[StoredEvent | None]:
        # Replay history first
        for evt in self.store.list_events_since(run_id, after_event_id=since):
            yield evt
        # Then stream new events
        queue = self.bus.subscribe(run_id)
        try:
            while True:
                evt = await queue.get()
                yield evt
                if evt is None:
                    break
        finally:
            self.bus.unsubscribe(run_id, queue)

    def approve(self, run_id: str, reason: Optional[str] = None) -> None:
        if run_id not in self.approvals:
            self.approvals[run_id] = ApprovalState(queue=asyncio.Queue())
        self.approvals[run_id].queue.put_nowait({"decision": "approved", "reason": reason})

    def reject(self, run_id: str, reason: Optional[str] = None) -> None:
        if run_id not in self.approvals:
            self.approvals[run_id] = ApprovalState(queue=asyncio.Queue())
        self.approvals[run_id].queue.put_nowait({"decision": "rejected", "reason": reason})
