"""
Azure Function: invoke_mcp

Executes MCP (Model Context Protocol) tool calls for web intelligence.
Uses Playwright for browser automation (free, open source).
"""

import azure.functions as func
import json
import logging
import os
import httpx
import re
import base64
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def execute_playwright_tool(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Playwright MCP tools."""
    try:
        # Check if Browserless is configured for cloud execution
        browserless_key = os.getenv("BROWSERLESS_API_KEY")
        
        if browserless_key:
            # Use Browserless.io cloud browser
            return await execute_with_browserless(tool_name, params, browserless_key)
        else:
            # Use basic HTTP fallback (works for most static pages)
            return await execute_http_fallback(tool_name, params)
            
    except Exception as e:
        logger.error(f"Playwright tool error: {e}")
        return {"success": False, "error": str(e)}


async def execute_http_fallback(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback to basic HTTP when Browserless not available."""
    url = params.get("url")
    
    if not url:
        return {"success": False, "error": "URL is required"}
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            html = response.text
            
            # Extract text content
            text = html
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            
            result = {
                "success": True,
                "url": url,
                "text": text[:15000],  # Limit to 15k chars
                "execution_mode": "http_fallback"
            }
            
            # Extract links if requested
            if params.get("extract_links"):
                links = re.findall(r'href=["\']([^"\']+)["\']', html)
                result["links"] = list(set(links))[:100]
            
            return result
            
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}


async def execute_with_browserless(tool_name: str, params: Dict[str, Any], api_key: str) -> Dict[str, Any]:
    """Execute with Browserless.io cloud browser."""
    url = params.get("url")
    
    if not url:
        return {"success": False, "error": "URL is required"}
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            
            if tool_name == "playwright_screenshot":
                # Screenshot endpoint
                full_page = params.get("full_page", False)
                response = await client.post(
                    f"https://chrome.browserless.io/screenshot?token={api_key}",
                    json={
                        "url": url,
                        "options": {"fullPage": full_page, "type": "png"}
                    }
                )
                response.raise_for_status()
                
                return {
                    "success": True,
                    "url": url,
                    "screenshot_base64": base64.b64encode(response.content).decode("utf-8"),
                    "format": "png",
                    "execution_mode": "browserless"
                }
            
            else:
                # Content endpoint for scrape/navigate/get_text
                wait_for = params.get("wait_for", "body")
                response = await client.post(
                    f"https://chrome.browserless.io/content?token={api_key}",
                    json={
                        "url": url,
                        "waitForSelector": wait_for
                    }
                )
                response.raise_for_status()
                
                html = response.text
                
                # Extract text
                text = html
                text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                
                result = {
                    "success": True,
                    "url": url,
                    "text": text[:15000],
                    "execution_mode": "browserless"
                }
                
                if params.get("extract_links"):
                    links = re.findall(r'href=["\']([^"\']+)["\']', html)
                    result["links"] = list(set(links))[:100]
                
                return result
                
    except Exception as e:
        logger.error(f"Browserless error: {e}")
        # Fall back to HTTP if Browserless fails
        return await execute_http_fallback(tool_name, params)


async def main(req: func.HttpRequest) -> func.HttpResponse:
    """Main Azure Function handler for MCP tool invocation (Playwright only)."""
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"success": False, "error": "Invalid JSON body"}),
            status_code=400,
            mimetype="application/json"
        )
    
    tool = body.get("tool")
    params = body.get("params", {})
    
    if not tool:
        return func.HttpResponse(
            json.dumps({"success": False, "error": "tool is required"}),
            status_code=400,
            mimetype="application/json"
        )
    
    # Validate tool name
    valid_tools = [
        "playwright_scrape", "playwright_navigate", "playwright_screenshot",
        "playwright_get_text", "playwright_click_and_get"
    ]
    if tool not in valid_tools:
        return func.HttpResponse(
            json.dumps({"success": False, "error": f"Unknown tool: {tool}. Valid tools: {valid_tools}"}),
            status_code=400,
            mimetype="application/json"
        )
    
    logger.info(f"MCP invoke: tool={tool}")
    
    result = await execute_playwright_tool(tool, params)
    
    return func.HttpResponse(
        json.dumps(result, default=str),
        status_code=200 if result.get("success") else 500,
        mimetype="application/json"
    )
