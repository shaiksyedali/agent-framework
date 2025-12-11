# MCP (Model Context Protocol) Module
"""
MCP client infrastructure for connecting agents to external tools and data sources.

Supported Servers:
- Bright Data: Web scraping and data extraction
- Playwright: Browser automation
"""

from .client import MCPClient

__all__ = ["MCPClient"]
