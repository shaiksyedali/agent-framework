"""
Azure Function: execute_step
Executes a single workflow step by invoking agents or tools directly.
Uses AgentsClient for Azure AI Foundry agents.
"""

import azure.functions as func
import logging
import json
import os
import asyncio
import httpx
from pathlib import Path

# Azure AI Agents SDK
from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential

logger = logging.getLogger(__name__)


async def execute_tool(tool_name: str, args: dict) -> dict:
    """
    Execute a tool by calling the appropriate Azure Function.
    """
    base_url = os.environ.get("AZURE_FUNCTIONS_URL")
    function_key = os.environ.get("AZURE_FUNCTIONS_KEY")
    
    if not base_url:
        base_url = f"https://{os.environ.get('WEBSITE_HOSTNAME', 'localhost:7071')}"
    
    # Map tool names to functions
    tool_function_map = {
        "execute_sql_query": "execute_azure_sql",
        "get_database_schema": "get_azure_sql_schema",
        "consult_rag": "consult_rag",
        "get_document_summary": "get_document_summary",
        "graph_query": "graph_query",
        "invoke_mcp": "invoke_mcp",
        # Playwright tools
        "playwright_scrape": "invoke_mcp",
        "playwright_navigate": "invoke_mcp",
        "playwright_screenshot": "invoke_mcp",
        # DuckDuckGo Search tools (FREE - no API key)
        "ddg_web_search": "invoke_mcp",
        "web_search": "invoke_mcp",
    }
    
    function_name = tool_function_map.get(tool_name, tool_name)
    target_url = f"{base_url}/api/{function_name}"
    
    headers = {"Content-Type": "application/json"}
    if function_key:
        headers["x-functions-key"] = function_key
    
    # For MCP tools (playwright_, ddg_, web_search), wrap in proper format
    if tool_name.startswith("playwright_") or tool_name.startswith("ddg_") or tool_name == "web_search":
        args = {"server": "mcp", "tool": tool_name, "params": args}
    
    
    logger.info(f"Executing tool: {tool_name} -> {function_name}")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(target_url, json=args, headers=headers)
            response.raise_for_status()
            return {"success": True, "result": response.json()}
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {"success": False, "error": str(e)}


async def run_agent_with_client(client: AgentsClient, agent_id: str, prompt: str) -> dict:
    """
    Run an agent directly using AgentsClient.
    Returns the agent's response.
    """
    try:
        # Create thread and message
        thread = await client.threads.create()
        await client.messages.create(
            thread_id=thread.id,
            role="user",
            content=prompt
        )
        
        # Create run
        run = await client.runs.create(thread_id=thread.id, agent_id=agent_id)
        
        # Poll for completion (simplified - no tool handling for sub-agents)
        while True:
            await asyncio.sleep(1)
            run = await client.runs.get(thread_id=thread.id, run_id=run.id)
            logger.info(f"Sub-agent run status: {run.status}")
            
            if run.status == "completed":
                # messages.list() returns AsyncItemPaged - iterate, don't await
                messages = client.messages.list(thread_id=thread.id)
                async for msg in messages:
                    if msg.role == "assistant":
                        for content in msg.content:
                            if hasattr(content, 'text'):
                                return {"success": True, "result": content.text.value}
                return {"success": True, "result": "No response content."}
                
            elif run.status == "requires_action":
                # For sub-agents, we handle tool calls inline
                if run.required_action and run.required_action.submit_tool_outputs:
                    tool_outputs = []
                    for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                        name = tool_call.function.name
                        try:
                            args = json.loads(tool_call.function.arguments)
                        except:
                            args = {}
                        
                        logger.info(f"Sub-agent tool call: {name}")
                        tool_result = await execute_tool(name, args)
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(tool_result)
                        })
                    
                    await client.runs.submit_tool_outputs(
                        thread_id=thread.id,
                        run_id=run.id,
                        tool_outputs=tool_outputs
                    )
                    
            elif run.status in ["failed", "cancelled", "expired"]:
                error_msg = run.last_error if hasattr(run, 'last_error') else "Unknown error"
                return {"success": False, "error": f"Run failed: {run.status}. {error_msg}"}
                
    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        return {"success": False, "error": str(e)}


async def main_async(req: func.HttpRequest) -> func.HttpResponse:
    """
    Execute a workflow step.
    
    Request body:
    {
        "step": {
            "step_id": "1",
            "name": "Step Name",
            "description": "What to do",
            "agent": "agent_id or agent_name",
            "tool": "optional_direct_tool",
            "tool_args": {}
        },
        "context": {
            "user_request": "Original user request",
            "previous_outputs": {}
        }
    }
    """
    logger.info("execute_step triggered")
    
    try:
        body = req.get_json()
        logger.info(f"execute_step received: {json.dumps(body, default=str)[:500]}")
    except ValueError:
        return func.HttpResponse(
            json.dumps({"success": False, "error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json"
        )
    
    # Flexible parsing: step can be at top level or nested
    step = body.get("step", {})
    context = body.get("context", {})
    
    # If step is empty, try to extract from top-level fields
    if not step:
        if body.get("agent") or body.get("name") or body.get("step_id") or body.get("description"):
            step = body
            logger.info("Using top-level body as step definition")
        else:
            logger.warning(f"Missing step definition. Received keys: {list(body.keys())}")
            return func.HttpResponse(
                json.dumps({
                    "success": False, 
                    "error": "Missing step definition",
                    "received_keys": list(body.keys()),
                    "hint": "Expected 'step' object with 'agent' or 'name' field"
                }),
                status_code=400,
                mimetype="application/json"
            )
    
    step_id = step.get("step_id", step.get("id", "unknown"))
    step_name = step.get("name", step.get("step_name", "Unnamed Step"))
    agent_id = step.get("agent", step.get("agent_id", step.get("agent_name")))
    tool_name = step.get("tool", step.get("tool_name"))
    tool_args = step.get("tool_args", step.get("arguments", {}))
    description = step.get("description", "")
    
    logger.info(f"Executing step {step_id}: {step_name}, agent={agent_id}, tool={tool_name}")
    
    result = {
        "step_id": step_id,
        "step_name": step_name,
        "success": False,
        "output": None,
        "error": None
    }
    
    try:
        # Option 1: Direct tool execution
        if tool_name:
            logger.info(f"Direct tool execution: {tool_name}")
            tool_result = await execute_tool(tool_name, tool_args)
            result["success"] = tool_result.get("success", False)
            result["output"] = tool_result.get("result", tool_result.get("error"))
            result["error"] = tool_result.get("error")
        
        # Option 2: Agent invocation using AgentsClient directly
        elif agent_id:
            logger.info(f"Agent invocation: {agent_id}")
            
            endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
            if not endpoint:
                result["error"] = "AZURE_AI_PROJECT_ENDPOINT not configured"
                return func.HttpResponse(
                    json.dumps(result),
                    status_code=500,
                    mimetype="application/json"
                )
            
            # Build agent prompt from context and step
            user_request = context.get("user_request", "")
            previous_outputs = context.get("previous_outputs", {})
            
            agent_prompt = f"""Execute this step:

## Step: {step_name}
{description}

## User Request
{user_request}

## Previous Step Outputs
{json.dumps(previous_outputs, indent=2) if previous_outputs else "None"}

## OUTPUT FORMATTING
Format your response for readability:
- Use **bold** for key terms and values
- Use bullet points for lists
- Use tables for structured data
- Use clear headings if organizing multiple topics
- Cite sources when applicable

Process this step and return a well-formatted result."""

            # Use AgentsClient directly
            credential = DefaultAzureCredential()
            client = AgentsClient(endpoint=endpoint, credential=credential)
            
            try:
                agent_result = await run_agent_with_client(client, agent_id, agent_prompt)
                
                if agent_result.get("success"):
                    result["success"] = True
                    result["output"] = agent_result.get("result")
                else:
                    result["success"] = False
                    result["error"] = agent_result.get("error")
            finally:
                await credential.close()
                await client.close()
        
        else:
            result["error"] = "No agent or tool specified in step"
            
    except Exception as e:
        logger.error(f"Step execution failed: {e}", exc_info=True)
        result["error"] = str(e)
    
    status_code = 200 if result["success"] else 500
    return func.HttpResponse(
        json.dumps(result),
        status_code=status_code,
        mimetype="application/json"
    )


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
