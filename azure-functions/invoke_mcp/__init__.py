"""
Azure Function: invoke_mcp

Executes MCP (Model Context Protocol) tool calls for web intelligence.
Uses:
- Playwright/Browserless for browser automation
- Brave Search API for web search
"""

import azure.functions as func
import json
import logging
import os
import httpx
import re
import base64
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


# =============================================================================
# DUCKDUCKGO SEARCH (FREE - No API Key Required)
# =============================================================================

async def execute_duckduckgo_search(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute DuckDuckGo search - completely FREE, no API key needed.
    Scrapes DuckDuckGo HTML search results.
    """
    query = params.get("query") or params.get("q")
    if not query:
        return {"success": False, "error": "query is required"}
    
    count = min(params.get("count", 10), 20)
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # DuckDuckGo HTML search URL
        search_url = f"https://html.duckduckgo.com/html/?q={query}"
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(search_url, headers=headers)
            response.raise_for_status()
            html = response.text
        
        # Parse search results from HTML
        results = []
        
        # Find all result blocks - DuckDuckGo HTML uses specific class patterns
        # Pattern: <a class="result__a" href="URL">TITLE</a>
        # And: <a class="result__snippet">DESCRIPTION</a>
        
        import re
        
        # Extract result links and titles
        result_pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>'
        snippet_pattern = r'<a[^>]*class="result__snippet"[^>]*>([^<]*(?:<[^>]*>[^<]*</[^>]*>)*[^<]*)</a>'
        
        links = re.findall(result_pattern, html)
        snippets = re.findall(snippet_pattern, html)
        
        # Clean up snippets (remove HTML tags)
        clean_snippets = []
        for s in snippets:
            clean = re.sub(r'<[^>]+>', '', s).strip()
            clean_snippets.append(clean)
        
        # Combine results
        for i, (url, title) in enumerate(links[:count]):
            # DuckDuckGo uses redirect URLs, extract actual URL
            if "uddg=" in url:
                actual_url = re.search(r'uddg=([^&]+)', url)
                if actual_url:
                    from urllib.parse import unquote
                    url = unquote(actual_url.group(1))
            
            result = {
                "title": title.strip(),
                "url": url,
                "description": clean_snippets[i] if i < len(clean_snippets) else ""
            }
            results.append(result)
        
        if not results:
            # Fallback: try DuckDuckGo Instant Answer API (limited but works for some queries)
            api_url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
            response = await client.get(api_url, headers=headers)
            data = response.json()
            
            # Get related topics
            for topic in data.get("RelatedTopics", [])[:count]:
                if isinstance(topic, dict) and topic.get("FirstURL"):
                    results.append({
                        "title": topic.get("Text", "")[:100],
                        "url": topic.get("FirstURL"),
                        "description": topic.get("Text", "")
                    })
        
        return {
            "success": True,
            "query": query,
            "results": results,
            "total_results": len(results),
            "source": "duckduckgo"
        }
        
    except Exception as e:
        logger.error(f"DuckDuckGo Search error: {e}")
        return {"success": False, "error": str(e)}


async def execute_playwright_tool(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute Playwright MCP tools with multiple backend options."""
    try:
        # Priority: Steel > Browserless > HTTP fallback
        steel_key = os.getenv("STEEL_API_KEY")
        browserless_key = os.getenv("BROWSERLESS_API_KEY")
        
        # Debug logging
        logger.info(f"Browser backend selection: steel_key={'SET' if steel_key else 'NOT SET'}, browserless_key={'SET' if browserless_key else 'NOT SET'}")
        
        if steel_key:
            # Use Steel cloud browser (best for AI agents)
            logger.info("Using Steel browser backend")
            result = await execute_with_steel(tool_name, params, steel_key)
            logger.info(f"Steel result mode: {result.get('execution_mode', 'unknown')}")
            return result
        elif browserless_key:
            # Use Browserless.io cloud browser
            logger.info("Using Browserless browser backend")
            return await execute_with_browserless(tool_name, params, browserless_key)
        else:
            # Use basic HTTP fallback (works for static pages)
            logger.info("Using HTTP fallback (no STEEL_API_KEY or BROWSERLESS_API_KEY)")
            return await execute_http_fallback(tool_name, params)
            
    except Exception as e:
        logger.error(f"Playwright tool error: {e}")
        return {"success": False, "error": str(e)}


async def execute_with_steel(tool_name: str, params: Dict[str, Any], api_key: str) -> Dict[str, Any]:
    """
    Execute with Steel cloud browser using official SDK.
    Steel provides: anti-bot detection, CAPTCHA solving, session persistence.
    SDK v0.15+ uses client.scrape(url) directly.
    """
    url = params.get("url")
    if not url:
        return {"success": False, "error": "URL is required"}
    
    try:
        # Import Steel SDK (installed via requirements.txt)
        from steel import AsyncSteel
        
        # AsyncSteel - pass API key explicitly
        client = AsyncSteel(steel_api_key=api_key)
        
        try:
            logger.info(f"Steel scraping: {url}")
            
            # Use client.scrape directly (SDK v0.15+ API)
            # Note: Steel uses 'delay' parameter, not 'wait_for'
            scrape_result = await client.scrape(
                url=url,
                delay=params.get("wait_for", 3.0),  # Delay in seconds for page load
            )
            
            # Get content from result
            # Get content from result - Steel returns nested Content object
            html = ""
            if hasattr(scrape_result, 'content') and scrape_result.content:
                content = scrape_result.content
                # content.html is the raw HTML
                if hasattr(content, 'html') and content.html:
                    html = content.html
                elif hasattr(content, 'cleaned_html') and content.cleaned_html:
                    html = content.cleaned_html
            
            logger.info(f"Steel scraped {len(html)} chars from {url}")
            
            # Extract text content
            text = html
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            
            result = {
                "success": True,
                "url": url,
                "text": text[:15000],
                "execution_mode": "steel"
            }
            
            # Extract links if requested
            if params.get("extract_links"):
                links = re.findall(r'href=["\'](https?://[^"\']+)["\']', html)
                result["links"] = list(set(links))[:100]
            
            return result
            
        finally:
            # Close client
            await client.close()
                
    except ImportError as e:
        logger.warning(f"Steel SDK not available: {e}. Falling back to HTTP.")
        # Return HTTP result but with debug info
        result = await execute_http_fallback(tool_name, params)
        result["steel_error"] = f"ImportError: {e}"
        return result
    except Exception as e:
        logger.error(f"Steel error: {e}")
        # Return HTTP result but with debug info
        result = await execute_http_fallback(tool_name, params)
        result["steel_error"] = f"{type(e).__name__}: {e}"
        return result



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
    """Main Azure Function handler for MCP tool invocation."""
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
    
    # Define valid tools by category
    playwright_tools = [
        "playwright_scrape", "playwright_navigate", "playwright_screenshot",
        "playwright_get_text", "playwright_click_and_get"
    ]
    search_tools = [
        "ddg_web_search", "web_search"  # DuckDuckGo (free, no API key)
    ]
    valid_tools = playwright_tools + search_tools
    
    if tool not in valid_tools:
        return func.HttpResponse(
            json.dumps({"success": False, "error": f"Unknown tool: {tool}. Valid tools: {valid_tools}"}),
            status_code=400,
            mimetype="application/json"
        )
    
    logger.info(f"MCP invoke: tool={tool}")
    
    # Route to appropriate handler
    if tool in search_tools:
        result = await execute_duckduckgo_search(tool, params)
    else:
        result = await execute_playwright_tool(tool, params)
    
    return func.HttpResponse(
        json.dumps(result, default=str),
        status_code=200 if result.get("success") else 500,
        mimetype="application/json"
    )

