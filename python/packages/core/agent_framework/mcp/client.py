"""
MCP Client Base Class

Provides base functionality for connecting to MCP (Model Context Protocol) servers.
"""

import os
import logging
import subprocess
import json
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class MCPClient(ABC):
    """Base class for MCP server clients."""
    
    def __init__(self, server_name: str):
        self.server_name = server_name
        self.connected = False
        self._process: Optional[subprocess.Popen] = None
    
    @abstractmethod
    def get_tools(self) -> List[Dict[str, Any]]:
        """Return list of available tools for this server."""
        pass
    
    @abstractmethod
    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call on this server."""
        pass
    
    def is_connected(self) -> bool:
        """Check if client is connected to server."""
        return self.connected


class MCPServerRegistry:
    """Registry for managing MCP server connections."""
    
    _servers: Dict[str, MCPClient] = {}
    
    @classmethod
    def register(cls, name: str, client: MCPClient):
        """Register an MCP server client."""
        cls._servers[name] = client
        logger.info(f"Registered MCP server: {name}")
    
    @classmethod
    def get(cls, name: str) -> Optional[MCPClient]:
        """Get a registered MCP server client."""
        return cls._servers.get(name)
    
    @classmethod
    def list_servers(cls) -> List[str]:
        """List all registered servers."""
        return list(cls._servers.keys())
    
    @classmethod
    def get_all_tools(cls) -> List[Dict[str, Any]]:
        """Get all tools from all registered servers."""
        tools = []
        for name, client in cls._servers.items():
            for tool in client.get_tools():
                # Prefix tool name with server name
                tool_copy = tool.copy()
                tool_copy["server"] = name
                tools.append(tool_copy)
        return tools


async def execute_mcp_tool(server_name: str, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute an MCP tool call.
    
    Args:
        server_name: Name of the MCP server (bright_data, playwright)
        tool_name: Name of the tool to call
        params: Tool parameters
        
    Returns:
        Tool execution result
    """
    client = MCPServerRegistry.get(server_name)
    if not client:
        return {
            "success": False,
            "error": f"MCP server '{server_name}' not registered"
        }
    
    try:
        result = await client.call_tool(tool_name, params)
        return {
            "success": True,
            "server": server_name,
            "tool": tool_name,
            "result": result
        }
    except Exception as e:
        logger.error(f"MCP tool call failed: {server_name}.{tool_name} - {e}")
        return {
            "success": False,
            "error": str(e),
            "server": server_name,
            "tool": tool_name
        }
