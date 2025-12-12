"""
Azure Function: invoke_agent
Delegates a task to another specialized agent using Azure AI Foundry AgentsClient.
ACTS AS A PURE DISPATCHER: Makes HTTP calls to other Azure Functions for tool execution.
"""

import azure.functions as func
import logging
import json
import os
import asyncio
import sys
import httpx
from pathlib import Path

# Azure AI Agents SDK
from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential

logger = logging.getLogger(__name__)

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
        base_url = f"https://{os.environ.get('WEBSITE_HOSTNAME', 'localhost:7071')}"
        if "localhost" not in base_url and "http" not in base_url:
             base_url = f"https://{base_url}"

    target_url = f"{base_url}/api/{function_name}"
    
    headers = {"Content-Type": "application/json"}
    if function_key:
        headers["x-functions-key"] = function_key

    logger.info(f"DISPATCH: Calling {target_url} with payload keys: {list(payload.keys())}")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(target_url, json=payload, headers=headers)
            response.raise_for_status()
            try:
                data = response.json()
                return json.dumps(data)
            except:
                return response.text
                
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP Error {e.response.status_code} calling {function_name}: {e.response.text}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})
        except Exception as e:
            error_msg = f"Connection Error calling {function_name}: {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})


async def handle_tool_call(tool_call) -> str:
    """
    Dispatches tool call to the appropriate Azure Function.
    """
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except:
        args = {}
        
    logger.info(f"Handling Tool Call: {name}")
    
    # MAP TOOL NAMES TO FUNCTION NAMES
    tool_function_map = {
        "invoke_agent": "invoke_agent",
        "list_available_agents": "list_available_agents",
        "validate_data_source": "validate_data_source",
        "execute_sql_query": "execute_azure_sql",
        "get_database_schema": "get_azure_sql_schema",
        "consult_rag": "consult_rag",
        "extract_citations": "extract_citations",
        "generate_followup_questions": "generate_followup_questions",
        # Executor agent tools
        "execute_step": "execute_step",
        "format_output": "format_output",
        "request_user_feedback": "request_user_feedback",
        # MCP/Playwright tools
        "playwright_scrape": "invoke_mcp",
        "playwright_navigate": "invoke_mcp",
        "playwright_screenshot": "invoke_mcp",
    }
    
    function_name = tool_function_map.get(name)
    
    if not function_name:
        return json.dumps({"error": f"Unknown tool: {name}"})
    
    # Wrap MCP tools
    if name.startswith("playwright_"):
        args = {"server": "playwright", "tool": name, "params": args}
    
    return await call_cloud_function(function_name, args)


# -------------------------------------------------------------------------
# CORE LOGIC - Using AgentsClient
# -------------------------------------------------------------------------

async def run_agent_loop(client: AgentsClient, thread_id: str, agent_id: str) -> str:
    """
    Manages the run loop: checks status, handles tool calls, submits outputs.
    Uses Azure AI Foundry AgentsClient API.
    """
    # Create a run
    run = await client.runs.create(thread_id=thread_id, agent_id=agent_id)
    
    while True:
        await asyncio.sleep(1)
        run = await client.runs.get(thread_id=thread_id, run_id=run.id)
        
        logger.info(f"Run status: {run.status}")

        if run.status == "completed":
            # messages.list() returns AsyncItemPaged - iterate, don't await
            messages = client.messages.list(thread_id=thread_id)
            async for msg in messages:
                if msg.role == "assistant":
                    for content in msg.content:
                        if hasattr(content, 'text'):
                            return content.text.value
            return "No response content."
            
        elif run.status == "requires_action":
            tool_outputs = []
            if run.required_action and run.required_action.submit_tool_outputs:
                for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                    output = await handle_tool_call(tool_call)
                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": str(output)
                    })
                
                await client.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs
                )
                
        elif run.status in ["failed", "cancelled", "expired"]:
            error_msg = run.last_error if hasattr(run, 'last_error') else "Unknown error"
            return f"Run failed with status: {run.status}. Error: {error_msg}"


# -------------------------------------------------------------------------
# AZURE FUNCTION ENTRY POINT
# -------------------------------------------------------------------------

async def main_async(req: func.HttpRequest) -> func.HttpResponse:
    """Main async handler"""
    try:
        req_body = req.get_json()
    except ValueError:
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

    # 2. Find Agent - match by key, name, or id
    target_agent = None
    for key, data in config.get("agents", {}).items():
        # Match by key (e.g., "rag_agent"), name, or id (e.g., "asst_...")
        if data.get("name") == agent_name or key == agent_name or data.get("id") == agent_name:
            target_agent = data
            logger.info(f"Found agent: key={key}, id={data.get('id')}")
            break
    
    if not target_agent:
         return func.HttpResponse(json.dumps({"error": f"Agent {agent_name} not found"}), status_code=404)

    # 3. Setup AgentsClient (Azure AI Foundry)
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    if not endpoint:
        return func.HttpResponse(
            json.dumps({"error": "AZURE_AI_PROJECT_ENDPOINT not configured"}),
            status_code=500
        )
    
    credential = DefaultAzureCredential()
    client = AgentsClient(endpoint=endpoint, credential=credential)

    try:
        # 4. Create thread and message
        if not thread_id:
            thread = await client.threads.create()
            thread_id = thread.id

        await client.messages.create(
            thread_id=thread_id,
            role="user",
            content=message_text
        )

        # 5. Run Loop (With HTTP dispatching for tools)
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
    finally:
        await credential.close()
        await client.close()


def main(req: func.HttpRequest) -> func.HttpResponse:
    """Azure Function entry point"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(main_async(req))
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )
