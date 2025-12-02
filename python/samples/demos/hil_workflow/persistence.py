"""SQLite-backed persistence for the HIL workflow sample API.

This module stores workflow definitions, runs, events, and approvals so the
UI can reconnect, replay history, and maintain durable state beyond the
process lifetime.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime(ISO_FORMAT)


@dataclass
class StoredWorkflow:
    id: str
    definition: Dict[str, Any]


@dataclass
class StoredRun:
    id: str
    workflow_id: str
    workflow_name: str
    started_at: str
    status: str
    engine: str


@dataclass
class StoredEvent:
    id: str
    run_id: str
    type: str
    message: str
    detail: Dict[str, Any]
    timestamp: str


@dataclass
class StoredApproval:
    id: str
    run_id: str
    decision: str
    reason: str | None
    timestamp: str


@dataclass
class StoredDocument:
    id: str
    workflow_id: str
    content: str
    embedding: List[float]
    metadata: Dict[str, Any]
    created_at: str


@dataclass
class StoredArtifact:
    id: str
    run_id: str
    kind: str
    payload: Dict[str, Any]
    created_at: str


class Store:
    """Simple SQLite wrapper with minimal locking for demo purposes."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                definition TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                workflow_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                status TEXT NOT NULL,
                engine TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                detail TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def create_workflow(self, workflow_id: str, definition: Dict[str, Any]) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO workflows (id, definition) VALUES (?, ?)",
            (workflow_id, json.dumps(definition)),
        )
        self._conn.commit()

    def list_workflows(self) -> List[StoredWorkflow]:
        cur = self._conn.cursor()
        rows = cur.execute("SELECT id, definition FROM workflows").fetchall()
        return [StoredWorkflow(id=row[0], definition=json.loads(row[1])) for row in rows]

    def get_workflow(self, workflow_id: str) -> Optional[StoredWorkflow]:
        cur = self._conn.cursor()
        row = cur.execute("SELECT id, definition FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if not row:
            return None
        return StoredWorkflow(id=row[0], definition=json.loads(row[1]))

    def create_run(self, run: StoredRun) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO runs (id, workflow_id, workflow_name, started_at, status, engine) VALUES (?, ?, ?, ?, ?, ?)",
            (run.id, run.workflow_id, run.workflow_name, run.started_at, run.status, run.engine),
        )
        self._conn.commit()

    def update_run_status(self, run_id: str, status: str) -> None:
        cur = self._conn.cursor()
        cur.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
        self._conn.commit()

    def get_run(self, run_id: str) -> Optional[StoredRun]:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT id, workflow_id, workflow_name, started_at, status, engine FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        return StoredRun(*row)

    def list_runs(self) -> List[StoredRun]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT id, workflow_id, workflow_name, started_at, status, engine FROM runs ORDER BY started_at DESC"
        ).fetchall()
        return [StoredRun(*row) for row in rows]

    def insert_event(self, event: StoredEvent) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO events (id, run_id, type, message, detail, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (event.id, event.run_id, event.type, event.message, json.dumps(event.detail or {}), event.timestamp),
        )
        self._conn.commit()

    def list_events(self, run_id: str) -> List[StoredEvent]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT id, run_id, type, message, detail, timestamp FROM events WHERE run_id = ? ORDER BY timestamp ASC",
            (run_id,),
        ).fetchall()
        return [StoredEvent(id=row[0], run_id=row[1], type=row[2], message=row[3], detail=json.loads(row[4]), timestamp=row[5]) for row in rows]

    def list_events_since(self, run_id: str, after_event_id: str | None = None) -> List[StoredEvent]:
        cur = self._conn.cursor()
        if after_event_id:
            anchor = cur.execute("SELECT timestamp FROM events WHERE id = ?", (after_event_id,)).fetchone()
            if anchor is None:
                after_event_id = None
        if after_event_id:
            rows = cur.execute(
                """
                SELECT id, run_id, type, message, detail, timestamp
                FROM events
                WHERE run_id = ? AND timestamp > (SELECT timestamp FROM events WHERE id = ?)
                ORDER BY timestamp ASC
                """,
                (run_id, after_event_id),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT id, run_id, type, message, detail, timestamp FROM events WHERE run_id = ? ORDER BY timestamp ASC",
                (run_id,),
            ).fetchall()

        return [StoredEvent(id=row[0], run_id=row[1], type=row[2], message=row[3], detail=json.loads(row[4]), timestamp=row[5]) for row in rows]

    def record_decision(self, run_id: str, decision: str, reason: str | None) -> None:
        cur = self._conn.cursor()
        approval_id = f"appr_{run_id}_{int(datetime.now().timestamp())}"
        cur.execute(
            "INSERT INTO approvals (id, run_id, decision, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
            (approval_id, run_id, decision, reason, _utc_now()),
        )
        self._conn.commit()

    def list_approvals(self, run_id: str) -> List[StoredApproval]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT id, run_id, decision, reason, timestamp FROM approvals WHERE run_id = ? ORDER BY timestamp ASC",
            (run_id,),
        ).fetchall()
        return [StoredApproval(id=row[0], run_id=row[1], decision=row[2], reason=row[3], timestamp=row[4]) for row in rows]

    def upsert_document(
        self,
        *,
        document_id: str,
        workflow_id: str,
        content: str,
        embedding: List[float],
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO documents (id, workflow_id, content, embedding, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                workflow_id = excluded.workflow_id,
                content = excluded.content,
                embedding = excluded.embedding, metadata = excluded.metadata
            """,
            (
                document_id,
                workflow_id,
                content,
                json.dumps(embedding),
                json.dumps(metadata or {}),
                _utc_now(),
            ),
        )
        self._conn.commit()

    def list_documents(self, workflow_id: str) -> List[StoredDocument]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT id, workflow_id, content, embedding, metadata, created_at FROM documents WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchall()
        docs: List[StoredDocument] = []
        for row in rows:
            docs.append(
                StoredDocument(
                    id=row[0],
                    workflow_id=row[1],
                    content=row[2],
                    embedding=json.loads(row[3]),
                    metadata=json.loads(row[4]),
                    created_at=row[5],
                )
            )
        return docs

    def record_artifact(self, run_id: str, kind: str, payload: Dict[str, Any]) -> str:
        artifact_id = f"art_{run_id}_{int(datetime.now().timestamp()*1000)}"
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO artifacts (id, run_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (artifact_id, run_id, kind, json.dumps(payload), _utc_now()),
        )
        self._conn.commit()
        return artifact_id

    def list_artifacts(self, run_id: str) -> List[StoredArtifact]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT id, run_id, kind, payload, created_at FROM artifacts WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
        artifacts: List[StoredArtifact] = []
        for row in rows:
            artifacts.append(
                StoredArtifact(id=row[0], run_id=row[1], kind=row[2], payload=json.loads(row[3]), created_at=row[4])
            )
        return artifacts

