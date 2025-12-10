from typing import List, Optional
from sqlalchemy import create_engine, Column, String, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import json
from .schema import WorkflowConfig, JobStatus

Base = declarative_base()

class WorkflowModel(Base):
    __tablename__ = "workflows"
    id = Column(String, primary_key=True)
    name = Column(String)
    description = Column(Text)
    config_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class JobModel(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    workflow_id = Column(String)
    status = Column(String)
    data_json = Column(JSON) # Stores the full JobStatus object
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class WorkflowRegistry:
    def __init__(self, db_url="sqlite:///./framework.db"):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def save_workflow(self, workflow: WorkflowConfig) -> WorkflowConfig:
        session = self.Session()
        try:
            print(f"DEBUG: Saving workflow. ID={workflow.id}, Name={workflow.name}")
            self._validate_step_chaining(workflow)
            # Check if exists
            existing = session.query(WorkflowModel).filter_by(id=workflow.id).first()
            if existing:
                print(f"DEBUG: Found existing workflow {existing.id}. Updating.")
                existing.name = workflow.name
                existing.description = workflow.description
                existing.config_json = workflow.model_dump(mode='json')
            else:
                new_wf = WorkflowModel(
                    id=workflow.id,
                    name=workflow.name,
                    description=workflow.description,
                    config_json=workflow.model_dump(mode='json')
                )
                session.add(new_wf)
            session.commit()
            return workflow
        finally:
            session.close()

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowConfig]:
        session = self.Session()
        try:
            wf = session.query(WorkflowModel).filter_by(id=workflow_id).first()
            if wf:
                return WorkflowConfig(**wf.config_json)
            return None
        finally:
            session.close()

    def delete_workflow(self, workflow_id: str) -> bool:
        session = self.Session()
        try:
            wf = session.query(WorkflowModel).filter_by(id=workflow_id).first()
            if wf:
                session.delete(wf)
                session.commit()
                return True
            return False
        finally:
            session.close()

    def list_workflows(self) -> List[WorkflowConfig]:
        session = self.Session()
        try:
            wfs = session.query(WorkflowModel).all()
            return [WorkflowConfig(**wf.config_json) for wf in wfs]
        finally:
            session.close()

    def _validate_step_chaining(self, workflow: WorkflowConfig):
        """
        Ensure each step after the first references at least one previous step's output_key in its input_template.
        This prevents disconnected steps and enforces context chaining.
        """
        steps = workflow.steps or []
        if len(steps) < 2:
            return
        prior_outputs = []
        for idx, step in enumerate(steps):
            if hasattr(step, "output_key") and getattr(step, "output_key", None):
                prior_outputs.append(step.output_key)
            if idx == 0:
                continue
            template = getattr(step, "input_template", "") or ""
            if not template:
                raise ValueError(f"Step '{step.name}' is missing input_template; cannot chain context.")
            # Require at least one reference to an earlier output_key
            if not any(f"{{{ok}}}" in template for ok in prior_outputs):
                raise ValueError(
                    f"Step '{step.name}' does not reference any previous step outputs in input_template. "
                    f"Include one of: {prior_outputs}"
                )

    def save_job(self, job: JobStatus):
        session = self.Session()
        try:
            existing = session.query(JobModel).filter_by(id=job.id).first()
            if existing:
                existing.status = job.status
                existing.data_json = job.model_dump(mode='json')
            else:
                new_job = JobModel(
                    id=job.id,
                    workflow_id=job.workflow_id,
                    status=job.status,
                    data_json=job.model_dump(mode='json')
                )
                session.add(new_job)
            session.commit()
        finally:
            session.close()

    def get_job(self, job_id: str) -> Optional[JobStatus]:
        session = self.Session()
        try:
            job = session.query(JobModel).filter_by(id=job_id).first()
            if job:
                return JobStatus(**job.data_json)
            return None
        finally:
            session.close()
