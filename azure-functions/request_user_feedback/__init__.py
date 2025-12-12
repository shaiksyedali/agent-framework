"""
Azure Function: request_user_feedback

Signals that the workflow requires user input before proceeding.
Updates job status to 'waiting_for_user' and stores the pending request.

This is used by executor_agent for Human-in-the-Loop (HIL) integration.
"""

import azure.functions as func
import logging
import json
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import Cosmos DB for direct job updates
try:
    from azure.cosmos.aio import CosmosClient
    from azure.identity.aio import DefaultAzureCredential
    HAS_COSMOS = True
except ImportError:
    HAS_COSMOS = False


async def update_job_status_cosmos(job_id: str, workflow_id: str, feedback_request: dict) -> bool:
    """Update job status in Cosmos DB to waiting_for_user."""
    cosmos_endpoint = os.environ.get("COSMOS_DB_ENDPOINT")
    cosmos_database = os.environ.get("COSMOS_DB_DATABASE", "hil-workflows")
    
    if not cosmos_endpoint or not HAS_COSMOS:
        logger.warning("Cosmos DB not configured for HIL feedback")
        return False
    
    try:
        credential = DefaultAzureCredential()
        client = CosmosClient(cosmos_endpoint, credential=credential)
        
        database = client.get_database_client(cosmos_database)
        container = database.get_container_client("jobs")
        
        # Get existing job
        job = await container.read_item(job_id, partition_key=workflow_id)
        
        # Update status
        job["status"] = "waiting_for_user"
        job["pending_feedback"] = feedback_request
        job["updated_at"] = datetime.utcnow().isoformat()
        job["logs"].append(f"[{datetime.utcnow().isoformat()}] Waiting for user feedback: {feedback_request.get('prompt', '')}")
        
        await container.replace_item(job_id, job)
        
        await credential.close()
        await client.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to update job status: {e}")
        return False


async def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Request user feedback for a workflow step.
    
    Expected input:
    {
        "step_result": {
            "step_id": "1",
            "step_name": "Query Database",
            "output": "...",
            "success": true
        },
        "job_id": "optional-job-id",
        "workflow_id": "optional-workflow-id",
        "prompt": "optional prompt for user",
        "options": ["proceed", "rerun", "abort"]  // optional
    }
    
    Returns signal that executor should pause and wait.
    The UI polls job status and shows feedback dialog when status = waiting_for_user.
    """
    logger.info("request_user_feedback triggered")
    
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json"
        )
    
    step_result = body.get("step_result", {})
    job_id = body.get("job_id")
    workflow_id = body.get("workflow_id")
    prompt = body.get("prompt", "Please review the step result and choose how to proceed.")
    options = body.get("options", ["proceed", "rerun", "abort"])
    
    step_id = step_result.get("step_id", "unknown")
    step_name = step_result.get("step_name", "Step")
    step_output = step_result.get("output", "")
    step_success = step_result.get("success", True)
    
    # Build feedback request
    feedback_request = {
        "type": "step_feedback",
        "step_id": step_id,
        "step_name": step_name,
        "step_output_preview": str(step_output)[:500],  # Limit preview
        "step_success": step_success,
        "prompt": prompt,
        "options": options,
        "requested_at": datetime.utcnow().isoformat()
    }
    
    result = {
        "success": True,
        "action": "wait_for_user",
        "feedback_request": feedback_request,
        "message": f"Waiting for user feedback on step '{step_name}'"
    }
    
    # Update job status in Cosmos DB if configured
    if job_id and workflow_id:
        cosmos_updated = await update_job_status_cosmos(job_id, workflow_id, feedback_request)
        result["cosmos_updated"] = cosmos_updated
        if cosmos_updated:
            result["message"] = f"Job {job_id} status updated to 'waiting_for_user'"
    else:
        result["cosmos_updated"] = False
        result["note"] = "job_id and workflow_id not provided - job status not updated in Cosmos DB"
    
    return func.HttpResponse(
        json.dumps(result, default=str),
        status_code=200,
        mimetype="application/json"
    )
