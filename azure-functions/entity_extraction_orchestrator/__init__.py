"""
Entity Extraction Starter - HTTP Trigger to start Durable Orchestration

This function receives chunks and starts the orchestration workflow.
"""
import azure.functions as func
import azure.durable_functions as df
import json
import logging


async def main(req: func.HttpRequest, starter: str) -> func.HttpResponse:
    """
    HTTP trigger to start the entity extraction orchestrator.
    
    Request body:
    {
        "chunks": [{"content": "...", "chunk_id": "...", "page_number": 1}, ...],
        "workflow_id": "xxx",
        "file_name": "xxx"
    }
    """
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON body"}),
            status_code=400,
            mimetype="application/json"
        )
    
    chunks = body.get("chunks", [])
    workflow_id = body.get("workflow_id", "")
    file_name = body.get("file_name", "unknown")
    
    if not chunks:
        return func.HttpResponse(
            json.dumps({"error": "No chunks provided"}),
            status_code=400,
            mimetype="application/json"
        )
    
    logging.info(f"Starting entity extraction for {len(chunks)} chunks from {file_name}")
    
    # Create durable client
    client = df.DurableOrchestrationClient(starter)
    
    # Start the orchestrator
    instance_id = await client.start_new(
        "EntityExtractionOrchestrator",
        client_input={
            "chunks": chunks,
            "workflow_id": workflow_id,
            "file_name": file_name
        }
    )
    
    logging.info(f"Started orchestration with ID = '{instance_id}'")
    
    # Return status URLs for polling
    response = client.create_check_status_response(req, instance_id)
    return response
