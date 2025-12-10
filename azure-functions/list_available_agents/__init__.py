"""
Azure Function: list_available_agents
List all available agents and their capabilities.
"""

import azure.functions as func
import json
import logging
import os
from pathlib import Path

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('list_available_agents triggered')

    try:
        # Load Agent Config
        config_path = Path(__file__).parent.parent / "azure_agents_config.json"
        
        # Hardcoded descriptions since they aren't in the config file
        # These match the system prompt descriptions
        descriptions = {
            "supervisor_agent": "Orchestrates multi-agent workflows",
            "planner_agent": "Creates structured workflow plans with dependencies",
            "executor_agent": "Executes workflows step-by-step with user feedback",
            "sql_agent": "Queries structured databases (SQL)",
            "rag_agent": "Searches documents and knowledge bases",
            "response_generator": "Formats final responses with citations"
        }

        agents_list = []
        
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
            
            agents_config = config.get("agents", {})
            for key, agent_data in agents_config.items():
                name = agent_data.get("name")
                # Normalize name key lookup
                desc = descriptions.get(name, "Specialized agent")
                agents_list.append({
                    "name": name,
                    "description": desc,
                    "id": agent_data.get("id")
                })
        else:
            # Fallback if config is missing (e.g. unit testing or misconfiguration)
            # return at least the hardcoded list so it doesn't break completely
             for name, desc in descriptions.items():
                agents_list.append({
                    "name": name,
                    "description": desc,
                    "status": "config_missing"
                })

        return func.HttpResponse(
            json.dumps({"agents": agents_list}),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Error in list_available_agents: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )
