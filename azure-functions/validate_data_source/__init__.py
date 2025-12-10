"""
Azure Function: validate_data_source
Check if a specific data source type is available and configured.
"""

import azure.functions as func
import json
import logging
from pathlib import Path

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('validate_data_source triggered')

    try:
        try:
            req_body = req.get_json()
        except ValueError:
             return func.HttpResponse(
                json.dumps({"error": "Invalid JSON body"}),
                mimetype="application/json",
                status_code=400
            )

        source_type = req_body.get('source_type')
        if not source_type:
            return func.HttpResponse(
                json.dumps({"error": "source_type is required"}),
                mimetype="application/json",
                status_code=400
            )

        # Load Agent Config to see what agents are registered
        # Presence of sql_agent implies database support
        # Presence of rag_agent implies documents support
        config_path = Path(__file__).parent.parent / "azure_agents_config.json"
        
        has_sql = False
        has_rag = False
        
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
            agents = config.get("agents", {})
            has_sql = "sql_agent" in agents
            has_rag = "rag_agent" in agents
        else:
            # Fallback defaults for testing
            has_sql = True
            has_rag = True

        valid = False
        message = ""

        if source_type == "database":
            valid = has_sql
            message = "SQL Agent is configured" if valid else "SQL Agent is missing"
        elif source_type == "documents":
            valid = has_rag
            message = "RAG Agent is configured" if valid else "RAG Agent is missing"
        elif source_type == "api":
            valid = True # APIs are generically supported via tools
            message = "API support is enabled"
        else:
            valid = False
            message = f"Unknown source type: {source_type}"

        return func.HttpResponse(
            json.dumps({
                "valid": valid,
                "message": message,
                "source_type": source_type
            }),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Error in validate_data_source: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )
