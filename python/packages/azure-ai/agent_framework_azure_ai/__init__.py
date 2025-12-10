# Copyright (c) Microsoft. All rights reserved.

import importlib.metadata

from ._chat_client import AzureAIAgentClient
from ._client import AzureAIClient
from ._shared import AzureAISettings, AzureFoundrySettings
from .azure_foundry_agent_adapter import AzureFoundryAgentAdapter, ToolExecutor
from .connectors import AzureSQLConnector

try:
    __version__ = importlib.metadata.version(__name__)
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"  # Fallback for development mode

__all__ = [
    "AzureAIAgentClient",
    "AzureAIClient",
    "AzureAISettings",
    "AzureFoundrySettings",
    "AzureFoundryAgentAdapter",
    "ToolExecutor",
    "AzureSQLConnector",
    "__version__",
]
