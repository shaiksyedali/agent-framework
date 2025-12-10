"""Azure integration for agent framework."""

from ._chat_client import AzureOpenAIChatClient
from .azure_tools_integration import (
    AzureToolsIntegration,
    create_agent_with_tools,
    create_multi_agent_system,
)

__all__ = [
    "AzureOpenAIChatClient",
    "AzureToolsIntegration",
    "create_agent_with_tools",
    "create_multi_agent_system",
]
