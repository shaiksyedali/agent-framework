"""
Azure Function: invoke_agent
Delegates a task to another specialized agent.
ACTS AS A PURE DISPATCHER: Makes HTTP calls to other Azure Functions for tool execution.
"""

import azure.functions as func
import logging
import json
import os
import asyncio
import sys
import httpx # Async HTTP client
from pathlib import Path

# Use standard OpenAI library
from openai import AsyncAzureOpenAI

# Path Setup
site_packages = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.python_packages', 'lib', 'site-packages')
if site_packages not in sys.path:
    sys.path.append(site_packages)

# -------------------------------------------------------------------------
# HTTP TOOL DISPATCHER
# -------------------------------------------------------------------------
async def call_cloud_function(function_name: str, payload: dict) -> str:
    """
    Calls a sibling Azure Function via HTTP.
    """
    base_url = os.environ.get("AZURE_FUNCTIONS_URL")
    function_key = os.environ.get("AZURE_FUNCTIONS_KEY")
    
    if not base_url:
        # Fallback to local if running locally, or try to construct from hostname
        base_url = f"https://{os.environ.get('WEBSITE_HOSTNAME', 'localhost:7071')}"
        if "localhost" not in base_url and "http" not in base_url:
             base_url = f"https://{base_url}"

    target_url = f"{base_url}/api/{function_name}"
    
    headers = {
        "Content-Type": "application/json"
    }
    if function_key:
        headers["x-functions-key"] = function_key

    logging.info(f"DISPATCH: Calling {target_url} with payload keys: {list(payload.keys())}")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(target_url, json=payload, headers=headers)
            response.raise_for_status()
            
            # Try to return pretty JSON, else string
            try:
                data = response.json()
                # If specific known keys exist, simplify output? 
                # No, raw is better for the generic agent.
                return json.dumps(data)
            except:
                return response.text
                
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP Error {e.response.status_code} calling {function_name}: {e.response.text}"
            logging.error(error_msg)
            return json.dumps({"error": error_msg})
        except Exception as e:
            error_msg = f"Connection Error calling {function_name}: {str(e)}"
            logging.error(error_msg)
            return json.dumps({"error": error_msg})

async def handle_tool_call(tool_call):
    """
    Dispatches tool call to the appropriate Azure Function.
    """
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except:
        args = {}
        
    logging.info(f"Handling Tool Call: {name}")
    
    # MAP TOOL NAMES TO FUNCTION NAMES
    # Tool Name -> Azure Function Name
    # (Some might match exactly, others might need mapping)
    
    if name == "invoke_agent":
        # Recursion: Call THIS function again
        return await call_cloud_function("invoke_agent", args)
        
    elif name == "list_available_agents":
        return await call_cloud_function("list_available_agents", args)
        
    elif name == "validate_data_source":
        return await call_cloud_function("validate_data_source", args)
        
    elif name == "execute_sql_query" or name == "get_database_schema":
        # Mapped to execute_azure_sql (or separate get_schema if exists)
        # We have 'execute_azure_sql' and 'get_azure_sql_schema' dirs?
        
        # Let's check directory structure availability...
        # Assuming 'execute_azure_sql' handles execution.
        if name == "execute_sql_query":
            return await call_cloud_function("execute_azure_sql", args)
        elif name == "get_database_schema":
            # Map to specific schema function if it exists, or let SQL agent resolve it.
            # We see 'get_azure_sql_schema' directory in previous file listing!
            return await call_cloud_function("get_azure_sql_schema", args)

    elif name == "consult_rag":
        return await call_cloud_function("consult_rag", args)
        
    elif name == "extract_citations":
        return await call_cloud_function("extract_citations", args)
        
    elif name == "generate_followup_questions":
        return await call_cloud_function("generate_followup_questions", args)
        
    # Executor tools (might not stay in cloud if they are UI interaction?)
    # For now, let's assume they return a simple success string or we map to a logger
    elif name == "execute_step" or name == "request_user_feedback" or name == "format_output":
        return json.dumps({"status": "executed", "details": f"Tool {name} processed by Orchestrator."})

    else:
        return f"Error: No Cloud Function mapped for tool '{name}'."


# -------------------------------------------------------------------------
# CORE LOGIC
# -------------------------------------------------------------------------

async def run_agent_loop(client, thread_id, assistant_id):
    """
    Manages the run loop: checks status, handles tool calls, submits outputs.
    """
    run = await client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id
    )
    
    while True:
        await asyncio.sleep(1)
        run = await client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        
        logging.info(f"Run status: {run.status}")

        if run.status == "completed":
            messages = await client.beta.threads.messages.list(thread_id=thread_id)
            for msg in messages.data:
                if msg.role == "assistant":
                     for content in msg.content:
                         if hasattr(content, 'text'):
                             return content.text.value
            return "No response content."
            
        elif run.status == "requires_action":
            tool_outputs = []
            for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                output = await handle_tool_call(tool_call)
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": str(output)
                })
            
            await client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
            
        elif run.status in ["failed", "cancelled", "expired"]:
            return f"Run failed: {run.last_error}"

async def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('invoke_agent triggered via HTTP')
    try:
        try:
            req_body = req.get_json()
        except:
             return func.HttpResponse(json.dumps({"error": "Invalid JSON"}), status_code=400)
             
        agent_name = req_body.get('agent_name')
        message_text = req_body.get('message')
        thread_id = req_body.get('thread_id')

        if not agent_name or not message_text:
             return func.HttpResponse(json.dumps({"error": "Missing inputs"}), status_code=400)

        # 1. Load Config
        config_path = Path(__file__).parent.parent / "azure_agents_config.json"
        if not config_path.exists():
            return func.HttpResponse(json.dumps({"error": "Config missing"}), status_code=500)
            
        with open(config_path) as f:
            config = json.load(f)

        # 2. Find Agent
        target_agent = None
        for key, data in config.get("agents", {}).items():
            if data.get("name") == agent_name or key == agent_name:
                target_agent = data
                break
        
        if not target_agent:
             return func.HttpResponse(json.dumps({"error": f"Agent {agent_name} not found"}), status_code=404)

        # 3. Setup Client
        client = AsyncAzureOpenAI(
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
        )

        if not thread_id:
            thread = await client.beta.threads.create()
            thread_id = thread.id

        await client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message_text
        )

        # 4. Run Loop (With HTTP dispatching)
        response_text = await run_agent_loop(client, thread_id, target_agent["id"])

        return func.HttpResponse(
            json.dumps({
                "response": response_text,
                "thread_id": thread_id,
                "agent": agent_name
            }),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"API Error: {e}", exc_info=True)
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500)
