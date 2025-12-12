#!/usr/bin/env python3
"""
Test script for invoke_mcp Azure Function.
Tests DuckDuckGo Search and Playwright scraping (all FREE, no API keys).
"""
import asyncio
import httpx
import json
import os
from pathlib import Path

# Load environment
env_path = Path(__file__).parent.parent / ".env.azure"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k] = v

AZURE_FUNCTIONS_URL = os.getenv("AZURE_FUNCTIONS_URL", "https://pi12-functions.azurewebsites.net")
AZURE_FUNCTIONS_KEY = os.getenv("AZURE_FUNCTIONS_KEY", "")


async def call_mcp(tool: str, params: dict) -> dict:
    """Call invoke_mcp Azure Function."""
    url = f"{AZURE_FUNCTIONS_URL}/api/invoke_mcp"
    headers = {"Content-Type": "application/json"}
    if AZURE_FUNCTIONS_KEY:
        headers["x-functions-key"] = AZURE_FUNCTIONS_KEY
    
    payload = {"server": "mcp", "tool": tool, "params": params}
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        try:
            return response.json()
        except:
            return {"success": False, "error": response.text[:500]}


async def test_duckduckgo_search():
    """Test DuckDuckGo Web Search (FREE - no API key)."""
    print("\n" + "=" * 60)
    print("TEST 1: DuckDuckGo Web Search (FREE)")
    print("=" * 60)
    
    result = await call_mcp("web_search", {
        "query": "predictive maintenance electric vehicles companies",
        "count": 5
    })
    
    if result.get("success"):
        print(f"✅ SUCCESS - Found {result.get('total_results', 0)} results")
        for i, r in enumerate(result.get("results", [])[:3], 1):
            print(f"\n  {i}. {r.get('title', 'N/A')}")
            print(f"     URL: {r.get('url', 'N/A')}")
            desc = r.get('description', '')[:100]
            if desc:
                print(f"     {desc}...")
    else:
        print(f"❌ FAILED: {result.get('error', 'Unknown error')}")
    
    return result.get("success", False)


async def test_playwright_scrape():
    """Test Playwright scraping (with Steel if configured)."""
    print("\n" + "=" * 60)
    print("TEST 2: Playwright Scrape (uses Steel if STEEL_API_KEY set)")
    print("=" * 60)
    
    result = await call_mcp("playwright_scrape", {
        "url": "https://en.wikipedia.org/wiki/Predictive_maintenance"
    })
    
    if result.get("success"):
        text = result.get("text", "")[:300]
        mode = result.get("execution_mode", "unknown")
        mode_emoji = "🚀" if mode == "steel" else "📡" if mode == "browserless" else "🌐"
        print(f"✅ SUCCESS - Mode: {mode_emoji} {mode}")
        # Show debug info if Steel failed
        if result.get("steel_error"):
            print(f"   ⚠️  Steel failed: {result.get('steel_error')}")
        print(f"   Content Preview: {text}...")
    else:
        print(f"❌ FAILED: {result.get('error', 'Unknown error')}")
    
    return result.get("success", False)


async def main():
    print("=" * 60)
    print("MCP Function Test Suite (All FREE - No API Keys)")
    print("=" * 60)
    print(f"URL: {AZURE_FUNCTIONS_URL}")
    print(f"Key: {'✓ Set' if AZURE_FUNCTIONS_KEY else '✗ Missing'}")
    
    search_ok = await test_duckduckgo_search()
    scrape_ok = await test_playwright_scrape()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"DuckDuckGo Search: {'✅ Working' if search_ok else '❌ Failed'}")
    print(f"Playwright Scrape: {'✅ Working' if scrape_ok else '❌ Failed'}")
    
    if search_ok and scrape_ok:
        print("\n🎉 All tests passed! MCP is ready for web research.")
        print("\nHow it works:")
        print("1. Agent calls web_search('your query') - finds URLs")
        print("2. Agent calls playwright_scrape(url) - gets page content")
        print("3. Agent synthesizes findings into structured response")


if __name__ == "__main__":
    asyncio.run(main())
