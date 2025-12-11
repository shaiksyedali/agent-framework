"""
Playwright MCP Server Client

Provides browser automation capabilities.
https://playwright.dev/
"""

import os
import logging
import base64
from typing import Dict, Any, List, Optional

from ..client import MCPClient

logger = logging.getLogger(__name__)

# Lazy import to avoid requiring playwright when not used
playwright = None
async_playwright = None


def _import_playwright():
    """Lazy import playwright."""
    global playwright, async_playwright
    if playwright is None:
        try:
            from playwright.async_api import async_playwright as ap
            async_playwright = ap
            return True
        except ImportError:
            logger.warning("Playwright not installed. Install with: pip install playwright && playwright install")
            return False
    return True


class PlaywrightClient(MCPClient):
    """
    Playwright MCP client for browser automation.
    
    Environment Variables:
        BROWSERLESS_API_KEY: (Optional) API key for browserless.io cloud execution
        PLAYWRIGHT_HEADLESS: Whether to run in headless mode (default: true)
    """
    
    def __init__(self):
        super().__init__("playwright")
        self.browserless_key = os.getenv("BROWSERLESS_API_KEY")
        self.headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
        self._browser = None
        self._playwright = None
        
        # Check if playwright is available
        if _import_playwright():
            self.connected = True
            logger.info("Playwright client initialized")
        else:
            logger.warning("Playwright not available")
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Return available Playwright tools."""
        return [
            {
                "name": "navigate",
                "description": "Navigate to a URL and get page content",
                "parameters": {
                    "url": {"type": "string", "required": True},
                    "wait_for": {"type": "string", "required": False, "description": "CSS selector to wait for"},
                    "timeout": {"type": "integer", "default": 30000}
                }
            },
            {
                "name": "screenshot",
                "description": "Take a screenshot of a webpage",
                "parameters": {
                    "url": {"type": "string", "required": True},
                    "full_page": {"type": "boolean", "default": False},
                    "selector": {"type": "string", "required": False, "description": "CSS selector to screenshot"}
                }
            },
            {
                "name": "get_text",
                "description": "Get text content from a webpage",
                "parameters": {
                    "url": {"type": "string", "required": True},
                    "selector": {"type": "string", "required": False, "description": "CSS selector to extract"},
                    "wait_for": {"type": "string", "required": False}
                }
            },
            {
                "name": "click_and_get",
                "description": "Click an element and get resulting page content",
                "parameters": {
                    "url": {"type": "string", "required": True},
                    "click_selector": {"type": "string", "required": True},
                    "wait_for": {"type": "string", "required": False}
                }
            }
        ]
    
    async def _ensure_browser(self):
        """Ensure browser is launched."""
        if self._browser is None:
            if not _import_playwright():
                raise RuntimeError("Playwright not available")
            
            self._playwright = await async_playwright().start()
            
            if self.browserless_key:
                # Use browserless.io for cloud execution
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    f"wss://chrome.browserless.io?token={self.browserless_key}"
                )
            else:
                # Local browser
                self._browser = await self._playwright.chromium.launch(headless=self.headless)
        
        return self._browser
    
    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a Playwright tool."""
        if not self.connected:
            return {"error": "Playwright client not available"}
        
        try:
            if tool_name == "navigate":
                return await self._navigate(params)
            elif tool_name == "screenshot":
                return await self._screenshot(params)
            elif tool_name == "get_text":
                return await self._get_text(params)
            elif tool_name == "click_and_get":
                return await self._click_and_get(params)
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Playwright tool failed: {e}")
            return {"error": str(e)}
    
    async def _navigate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Navigate to URL and get page info."""
        url = params.get("url")
        wait_for = params.get("wait_for")
        timeout = params.get("timeout", 30000)
        
        browser = await self._ensure_browser()
        page = await browser.new_page()
        
        try:
            await page.goto(url, timeout=timeout)
            
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=timeout)
            
            title = await page.title()
            content = await page.content()
            
            # Get accessibility tree for better content understanding
            accessibility = await page.accessibility.snapshot()
            
            return {
                "url": url,
                "title": title,
                "content_length": len(content),
                "accessibility_snapshot": accessibility
            }
        finally:
            await page.close()
    
    async def _screenshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Take a screenshot."""
        url = params.get("url")
        full_page = params.get("full_page", False)
        selector = params.get("selector")
        
        browser = await self._ensure_browser()
        page = await browser.new_page()
        
        try:
            await page.goto(url, wait_until="networkidle")
            
            if selector:
                element = await page.query_selector(selector)
                if element:
                    screenshot = await element.screenshot()
                else:
                    return {"error": f"Selector not found: {selector}"}
            else:
                screenshot = await page.screenshot(full_page=full_page)
            
            # Return base64 encoded image
            return {
                "url": url,
                "screenshot_base64": base64.b64encode(screenshot).decode("utf-8"),
                "format": "png"
            }
        finally:
            await page.close()
    
    async def _get_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get text content from page."""
        url = params.get("url")
        selector = params.get("selector")
        wait_for = params.get("wait_for")
        
        browser = await self._ensure_browser()
        page = await browser.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded")
            
            if wait_for:
                await page.wait_for_selector(wait_for)
            
            if selector:
                elements = await page.query_selector_all(selector)
                texts = []
                for el in elements[:20]:  # Limit to 20 elements
                    text = await el.inner_text()
                    texts.append(text)
                return {"url": url, "selector": selector, "texts": texts}
            else:
                # Get all visible text
                text = await page.inner_text("body")
                return {"url": url, "text": text[:10000]}  # Limit to 10k chars
        finally:
            await page.close()
    
    async def _click_and_get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Click an element and get resulting content."""
        url = params.get("url")
        click_selector = params.get("click_selector")
        wait_for = params.get("wait_for")
        
        browser = await self._ensure_browser()
        page = await browser.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded")
            
            # Click the element
            await page.click(click_selector)
            
            # Wait for navigation or content change
            if wait_for:
                await page.wait_for_selector(wait_for)
            else:
                await page.wait_for_load_state("networkidle")
            
            # Get resulting content
            title = await page.title()
            current_url = page.url
            text = await page.inner_text("body")
            
            return {
                "original_url": url,
                "current_url": current_url,
                "title": title,
                "text": text[:10000],
                "clicked": click_selector
            }
        finally:
            await page.close()
    
    async def close(self):
        """Close browser and cleanup."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
