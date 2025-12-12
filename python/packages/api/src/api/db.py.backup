"""
Database module for workflow storage using SQLite.
Simple file-based storage for workflows and jobs.
"""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from .models import WorkflowConfig, JobStatus


class Database:
    """Simple SQLite database for workflows and jobs"""

    def __init__(self, db_path: str = "data/workflows.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Workflows table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                user_intent TEXT,
                config TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                thread_id TEXT,
                status TEXT NOT NULL,
                current_step_index INTEGER DEFAULT 0,
                logs TEXT,
                context TEXT,
                step_outputs TEXT,
                pending_tool_call TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (workflow_id) REFERENCES workflows (id)
            )
        """)

        conn.commit()
        conn.close()

    # ===== WORKFLOWS =====

    def create_workflow(self, workflow: WorkflowConfig) -> str:
        """Create a new workflow"""
        if not workflow.id:
            workflow.id = str(uuid.uuid4())

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO workflows (id, name, description, user_intent, config, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            workflow.id,
            workflow.name,
            workflow.description,
            workflow.user_intent,
            workflow.model_dump_json()
        ))

        conn.commit()
        conn.close()

        return workflow.id

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowConfig]:
        """Get a workflow by ID"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT config FROM workflows WHERE id = ?", (workflow_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return WorkflowConfig.model_validate_json(row[0])
        return None

    def list_workflows(self) -> List[WorkflowConfig]:
        """List all workflows"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT config FROM workflows ORDER BY updated_at DESC")
        rows = cursor.fetchall()
        conn.close()

        return [WorkflowConfig.model_validate_json(row[0]) for row in rows]

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()

        return deleted

    # ===== JOBS =====

    def create_job(self, workflow_id: str, thread_id: Optional[str] = None) -> str:
        """Create a new job"""
        job_id = str(uuid.uuid4())

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO jobs (id, workflow_id, thread_id, status, logs, context, step_outputs)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id,
            workflow_id,
            thread_id,
            "running",
            json.dumps([]),
            json.dumps({}),
            json.dumps({})
        ))

        conn.commit()
        conn.close()

        return job_id

    def get_job(self, job_id: str) -> Optional[JobStatus]:
        """Get a job by ID"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, workflow_id, thread_id, status, current_step_index,
                   logs, context, step_outputs, pending_tool_call, error
            FROM jobs WHERE id = ?
        """, (job_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return JobStatus(
                id=row[0],
                workflow_id=row[1],
                thread_id=row[2],
                status=row[3],
                current_step_index=row[4],
                logs=json.loads(row[5]) if row[5] else [],
                context=json.loads(row[6]) if row[6] else {},
                step_outputs=json.loads(row[7]) if row[7] else {},
                pending_tool_call=json.loads(row[8]) if row[8] else None,
                error=row[9]
            )
        return None

    def update_job(self, job: JobStatus):
        """Update a job"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE jobs SET
                status = ?,
                current_step_index = ?,
                logs = ?,
                context = ?,
                step_outputs = ?,
                pending_tool_call = ?,
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            job.status,
            job.current_step_index,
            json.dumps(job.logs),
            json.dumps(job.context),
            json.dumps({k: v.model_dump() for k, v in job.step_outputs.items()}),
            json.dumps(job.pending_tool_call) if job.pending_tool_call else None,
            job.error,
            job.id
        ))

        conn.commit()
        conn.close()


# Global database instance
db = Database()
