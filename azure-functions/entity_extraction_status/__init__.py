"""
Entity Extraction Status - Check orchestration status

Returns the current status and result of an entity extraction job.
"""
import azure.functions as func
import azure.durable_functions as df
import json


async def main(req: func.HttpRequest, starter: str) -> func.HttpResponse:
    """
    Get the status of an entity extraction orchestration.
    
    Route: GET /api/entity_extraction_status/{instance_id}
    """
    instance_id = req.route_params.get("instance_id")
    
    if not instance_id:
        return func.HttpResponse(
            json.dumps({"error": "instance_id required"}),
            status_code=400,
            mimetype="application/json"
        )
    
    client = df.DurableOrchestrationClient(starter)
    status = await client.get_status(instance_id)
    
    if not status:
        return func.HttpResponse(
            json.dumps({"error": "Instance not found"}),
            status_code=404,
            mimetype="application/json"
        )
    
    # Build response
    response_data = {
        "instance_id": status.instance_id,
        "runtime_status": status.runtime_status.name if status.runtime_status else "Unknown",
        "created_time": status.created_time.isoformat() if status.created_time else None,
        "last_updated_time": status.last_updated_time.isoformat() if status.last_updated_time else None,
    }
    
    # Include output only if completed
    if status.runtime_status and status.runtime_status.name == "Completed":
        response_data["output"] = status.output
    elif status.runtime_status and status.runtime_status.name == "Failed":
        response_data["error"] = str(status.output) if status.output else "Unknown error"
    
    return func.HttpResponse(
        json.dumps(response_data),
        mimetype="application/json"
    )
