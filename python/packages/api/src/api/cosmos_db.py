"""
Cosmos DB module for job state persistence.
Provides cloud-ready storage with local SQLite fallback.

Features:
- Cosmos DB for production (multi-instance, persistent, queryable)
- SQLite fallback for local development
- Same interface as existing db.py
"""

import json
import logging
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# Try to import Cosmos DB client
try:
    from azure.cosmos.aio import CosmosClient
    from azure.cosmos import PartitionKey
    from azure.identity.aio import DefaultAzureCredential
    HAS_COSMOS = True
except ImportError:
    HAS_COSMOS = False
    logger.warning("azure-cosmos not installed. Install with: pip install azure-cosmos")


class CosmosJobStore:
    """
    Cosmos DB storage for job state.
    Falls back to in-memory if Cosmos DB is not configured.
    """
    
    def __init__(self):
        self.cosmos_endpoint = os.environ.get("COSMOS_DB_ENDPOINT")
        self.cosmos_key = os.environ.get("COSMOS_DB_KEY")  # API Key (optional)
        self.cosmos_database = os.environ.get("COSMOS_DB_DATABASE", "hil-workflows")
        self.jobs_container_name = "jobs"
        self.workflows_container_name = "workflows"
        
        self._client = None
        self._database = None
        self._jobs_container = None
        self._workflows_container = None
        self._credential = None
        
        # In-memory fallback for local development
        self._fallback_jobs: Dict[str, Dict[str, Any]] = {}
        self._fallback_workflows: Dict[str, Dict[str, Any]] = {}
        
        self._use_cosmos = bool(self.cosmos_endpoint and HAS_COSMOS)
        
        if self._use_cosmos:
            logger.info(f"Cosmos DB configured: {self.cosmos_endpoint}")
        else:
            logger.warning("Cosmos DB not configured. Using in-memory fallback.")
    
    async def initialize(self):
        """Initialize Cosmos DB connection (call on startup)."""
        if not self._use_cosmos:
            return
        
        try:
            # Use API key if provided, otherwise use DefaultAzureCredential
            if self.cosmos_key:
                logger.info("Using Cosmos DB API key authentication")
                self._client = CosmosClient(self.cosmos_endpoint, credential=self.cosmos_key)
            else:
                logger.info("Using DefaultAzureCredential for Cosmos DB")
                self._credential = DefaultAzureCredential()
                self._client = CosmosClient(self.cosmos_endpoint, credential=self._credential)
            
            # Get or create database
            self._database = await self._client.create_database_if_not_exists(self.cosmos_database)
            
            # Get or create containers with partition keys
            # Note: Serverless doesn't use offer_throughput
            try:
                self._jobs_container = await self._database.create_container_if_not_exists(
                    id=self.jobs_container_name,
                    partition_key=PartitionKey(path="/workflow_id")
                )
            except Exception:
                # Container might already exist
                self._jobs_container = self._database.get_container_client(self.jobs_container_name)
            
            try:
                self._workflows_container = await self._database.create_container_if_not_exists(
                    id=self.workflows_container_name,
                    partition_key=PartitionKey(path="/id")
                )
            except Exception:
                self._workflows_container = self._database.get_container_client(self.workflows_container_name)
            
            logger.info("Cosmos DB initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Cosmos DB: {e}")
            self._use_cosmos = False
            logger.warning("Falling back to in-memory storage")
    
    async def cleanup(self):
        """Cleanup connections."""
        if self._credential:
            await self._credential.close()
        if self._client:
            await self._client.close()
    
    # ===== JOBS =====
    
    async def create_job(self, workflow_id: str, thread_id: Optional[str] = None) -> str:
        """Create a new job and return its ID."""
        job_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        job_doc = {
            "id": job_id,
            "workflow_id": workflow_id,
            "thread_id": thread_id,
            "status": "running",
            "current_step_index": 0,
            "logs": [],
            "context": {},
            "step_outputs": {},
            "pending_tool_call": None,
            "error": None,
            "created_at": now,
            "updated_at": now
        }
        
        if self._use_cosmos and self._jobs_container:
            try:
                await self._jobs_container.create_item(job_doc)
            except Exception as e:
                logger.error(f"Failed to create job in Cosmos DB: {e}")
                self._fallback_jobs[job_id] = job_doc
        else:
            self._fallback_jobs[job_id] = job_doc
        
        return job_id
    
    async def get_job(self, job_id: str, workflow_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a job by ID."""
        if self._use_cosmos and self._jobs_container:
            try:
                # If we don't know workflow_id, query for it
                if not workflow_id:
                    query = "SELECT * FROM c WHERE c.id = @id"
                    items = [item async for item in self._jobs_container.query_items(
                        query=query,
                        parameters=[{"name": "@id", "value": job_id}]
                    )]
                    return items[0] if items else None
                else:
                    return await self._jobs_container.read_item(job_id, partition_key=workflow_id)
            except Exception as e:
                logger.error(f"Failed to get job from Cosmos DB: {e}")
                return self._fallback_jobs.get(job_id)
        else:
            return self._fallback_jobs.get(job_id)
    
    async def update_job(self, job_id: str, updates: Dict[str, Any], workflow_id: Optional[str] = None) -> bool:
        """Update a job with the given fields."""
        updates["updated_at"] = datetime.utcnow().isoformat()
        
        if self._use_cosmos and self._jobs_container:
            try:
                # Get existing job to get workflow_id for partition key
                existing = await self.get_job(job_id, workflow_id)
                if not existing:
                    return False
                
                # Merge updates
                existing.update(updates)
                
                await self._jobs_container.replace_item(job_id, existing)
                return True
            except Exception as e:
                logger.error(f"Failed to update job in Cosmos DB: {e}")
                if job_id in self._fallback_jobs:
                    self._fallback_jobs[job_id].update(updates)
                    return True
                return False
        else:
            if job_id in self._fallback_jobs:
                self._fallback_jobs[job_id].update(updates)
                return True
            return False
    
    async def list_jobs(self, workflow_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List jobs, optionally filtered by workflow."""
        if self._use_cosmos and self._jobs_container:
            try:
                if workflow_id:
                    query = "SELECT * FROM c WHERE c.workflow_id = @wid ORDER BY c.created_at DESC OFFSET 0 LIMIT @limit"
                    params = [
                        {"name": "@wid", "value": workflow_id},
                        {"name": "@limit", "value": limit}
                    ]
                else:
                    query = "SELECT * FROM c ORDER BY c.created_at DESC OFFSET 0 LIMIT @limit"
                    params = [{"name": "@limit", "value": limit}]
                
                return [item async for item in self._jobs_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True
                )]
            except Exception as e:
                logger.error(f"Failed to list jobs from Cosmos DB: {e}")
                return list(self._fallback_jobs.values())[:limit]
        else:
            jobs = list(self._fallback_jobs.values())
            if workflow_id:
                jobs = [j for j in jobs if j.get("workflow_id") == workflow_id]
            return jobs[:limit]
    
    # ===== WORKFLOWS =====
    
    async def create_workflow(self, workflow: Dict[str, Any]) -> str:
        """Create or update a workflow."""
        if not workflow.get("id"):
            workflow["id"] = str(uuid.uuid4())
        
        workflow["updated_at"] = datetime.utcnow().isoformat()
        
        if self._use_cosmos and self._workflows_container:
            try:
                await self._workflows_container.upsert_item(workflow)
            except Exception as e:
                logger.error(f"Failed to create workflow in Cosmos DB: {e}")
                self._fallback_workflows[workflow["id"]] = workflow
        else:
            self._fallback_workflows[workflow["id"]] = workflow
        
        return workflow["id"]
    
    async def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get a workflow by ID."""
        if self._use_cosmos and self._workflows_container:
            try:
                return await self._workflows_container.read_item(workflow_id, partition_key=workflow_id)
            except Exception as e:
                logger.debug(f"Workflow not found in Cosmos DB: {e}")
                return self._fallback_workflows.get(workflow_id)
        else:
            return self._fallback_workflows.get(workflow_id)
    
    async def list_workflows(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all workflows."""
        if self._use_cosmos and self._workflows_container:
            try:
                query = "SELECT * FROM c ORDER BY c.updated_at DESC OFFSET 0 LIMIT @limit"
                return [item async for item in self._workflows_container.query_items(
                    query=query,
                    parameters=[{"name": "@limit", "value": limit}],
                    enable_cross_partition_query=True
                )]
            except Exception as e:
                logger.error(f"Failed to list workflows from Cosmos DB: {e}")
                return list(self._fallback_workflows.values())[:limit]
        else:
            return list(self._fallback_workflows.values())[:limit]
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow."""
        if self._use_cosmos and self._workflows_container:
            try:
                await self._workflows_container.delete_item(workflow_id, partition_key=workflow_id)
                return True
            except Exception as e:
                logger.error(f"Failed to delete workflow from Cosmos DB: {e}")
                if workflow_id in self._fallback_workflows:
                    del self._fallback_workflows[workflow_id]
                    return True
                return False
        else:
            if workflow_id in self._fallback_workflows:
                del self._fallback_workflows[workflow_id]
                return True
            return False


# Global instance
cosmos_job_store = CosmosJobStore()
