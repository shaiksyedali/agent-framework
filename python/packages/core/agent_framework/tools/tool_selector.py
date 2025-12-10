"""
Tool Selection Logic.

Decides whether to use local or cloud tools based on data source configuration.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolConfig:
    """Configuration for a selected tool."""
    name: str
    type: str  # "local" or "cloud"
    deployment: str  # "python_function" or "azure_function"
    url: Optional[str] = None  # For Azure Functions
    function_definitions: List[Dict] = field(default_factory=list)  # Tool definitions for agent
    instance: Optional[Any] = None  # For local tools
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata


class ToolSelector:
    """
    Analyzes data sources and selects appropriate tools.

    Decision logic:
    - .db/.duckdb files → Local SQL tools
    - Azure SQL connection → Cloud SQL tool (Azure Function)
    - .pdf files → Cloud RAG tool (Azure AI Search)
    - MCP server URL → Cloud MCP tool (Azure Function)
    """

    def __init__(self, azure_functions_url: str):
        """
        Initialize tool selector.

        Args:
            azure_functions_url: Base URL for Azure Functions (e.g., https://myapp.azurewebsites.net)
        """
        self.azure_functions_url = azure_functions_url.rstrip('/')
        logger.info(f"ToolSelector initialized with Azure Functions URL: {self.azure_functions_url}")

    def select_tools(self, data_sources: List[Any]) -> Dict[str, List[ToolConfig]]:
        """
        Analyze data sources and select appropriate tools.

        Args:
            data_sources: List of DataSourceConfig objects

        Returns:
            {
                "local_tools": [ToolConfig, ...],
                "cloud_tools": [ToolConfig, ...]
            }
        """
        local_tools = []
        cloud_tools = []

        for ds in data_sources:
            tool_configs = []

            if ds.type == "file":
                tool_configs = self._select_file_tools(ds)
            elif ds.type == "database":
                tool_configs = self._select_database_tools(ds)
            elif ds.type == "mcp_server":
                tool_configs = self._select_mcp_tools(ds)
            else:
                logger.warning(f"Unknown data source type: {ds.type}")
                continue

            # Categorize tools
            for tool_config in tool_configs:
                if tool_config.type == "local":
                    local_tools.append(tool_config)
                    logger.info(f"Selected LOCAL tool: {tool_config.name} for {ds.name}")
                else:
                    cloud_tools.append(tool_config)
                    logger.info(f"Selected CLOUD tool: {tool_config.name} for {ds.name}")

        logger.info(f"Tool selection complete: {len(local_tools)} local, {len(cloud_tools)} cloud")

        return {
            "local_tools": local_tools,
            "cloud_tools": cloud_tools
        }

    def _select_file_tools(self, ds: Any) -> List[ToolConfig]:
        """Select tools for file data sources."""
        tools = []

        if not ds.path:
            logger.warning(f"File data source '{ds.name}' has no path")
            return tools

        ext = ds.path.lower().split('.')[-1]
        logger.debug(f"Processing file: {ds.path} (extension: {ext})")

        if ext in ['pdf', 'docx', 'md', 'txt']:
            # Document files → RAG (Azure AI Search)
            # NOTE: File must be ingested first
            tools.append(ToolConfig(
                name="consult_rag",
                type="cloud",
                deployment="azure_function",
                url=f"{self.azure_functions_url}/api/consult_rag",
                function_definitions=self._get_rag_function_definitions(),
                metadata={
                    "data_source_id": ds.id,
                    "data_source_name": ds.name,
                    "file_path": ds.path,
                    "file_type": ext
                }
            ))
            logger.info(f"Document file '{ds.path}' → Cloud RAG tool")

        elif ext in ['db', 'duckdb']:
            # Database files → Local SQL tools
            from .local_sql_tools import LocalSQLTools, get_local_sql_function_definitions

            instance = LocalSQLTools(ds.path)
            tools.append(ToolConfig(
                name="local_sql",
                type="local",
                deployment="python_function",
                function_definitions=get_local_sql_function_definitions(ds.path),
                instance=instance,
                metadata={
                    "data_source_id": ds.id,
                    "data_source_name": ds.name,
                    "db_path": ds.path,
                    "db_type": ext
                }
            ))
            logger.info(f"Database file '{ds.path}' → Local SQL tool")

        elif ext in ['csv', 'xlsx', 'json']:
            # Structured data files - could go either way
            # For now, treat as local
            logger.info(f"Structured file '{ds.path}' → Local file tool (not implemented yet)")
            # TODO: Implement local file tools or cloud ingestion

        else:
            logger.warning(f"Unsupported file extension: {ext} for {ds.path}")

        return tools

    def _select_database_tools(self, ds: Any) -> List[ToolConfig]:
        """Select tools for database data sources."""
        tools = []

        if not ds.connection_string:
            logger.warning(f"Database data source '{ds.name}' has no connection string")
            return tools

        conn_str = ds.connection_string.lower()
        logger.debug(f"Processing database: {ds.name} (connection: {conn_str[:50]}...)")

        if 'azure' in conn_str or 'sqlserver' in conn_str or 'database.windows.net' in conn_str:
            # Azure SQL → Cloud tool
            tools.append(ToolConfig(
                name="execute_azure_sql",
                type="cloud",
                deployment="azure_function",
                url=f"{self.azure_functions_url}/api/execute_azure_sql",
                function_definitions=self._get_azure_sql_function_definitions(),
                metadata={
                    "data_source_id": ds.id,
                    "data_source_name": ds.name,
                    "database_type": "azure_sql"
                }
            ))
            logger.info(f"Azure SQL database '{ds.name}' → Cloud SQL tool")

        else:
            # Other databases → Local tool (could be PostgreSQL, MySQL, etc.)
            from .local_sql_tools import LocalSQLTools, get_local_sql_function_definitions

            instance = LocalSQLTools(ds.connection_string)
            tools.append(ToolConfig(
                name="local_sql",
                type="local",
                deployment="python_function",
                function_definitions=get_local_sql_function_definitions(ds.connection_string),
                instance=instance,
                metadata={
                    "data_source_id": ds.id,
                    "data_source_name": ds.name,
                    "database_type": "other"
                }
            ))
            logger.info(f"Other database '{ds.name}' → Local SQL tool")

        return tools

    def _select_mcp_tools(self, ds: Any) -> List[ToolConfig]:
        """Select tools for MCP server data sources."""
        tools = []

        if not ds.url:
            logger.warning(f"MCP server data source '{ds.name}' has no URL")
            return tools

        # MCP server with URL → Cloud tool
        tools.append(ToolConfig(
            name="call_mcp_server",
            type="cloud",
            deployment="azure_function",
            url=f"{self.azure_functions_url}/api/call_mcp_server",
            function_definitions=self._get_mcp_function_definitions(ds.url),
            metadata={
                "data_source_id": ds.id,
                "data_source_name": ds.name,
                "mcp_url": ds.url
            }
        ))
        logger.info(f"MCP server '{ds.name}' → Cloud MCP tool")

        return tools

    def _get_rag_function_definitions(self) -> List[Dict]:
        """Get function definitions for RAG tools (Azure AI Search)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "consult_rag",
                    "description": "Search documents using Azure AI Search with semantic and vector search. Use this to find relevant information from ingested documents. Returns top matching documents with scores. **IMPORTANT**: This uses hybrid search (vector + semantic + keyword) for best results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query in natural language (e.g., 'What is the voltage range of PI10?')"
                            },
                            "index": {
                                "type": "string",
                                "description": "Index name (optional, defaults to configured index)",
                                "default": "documents"
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Number of results to return (1-50)",
                                "default": 5
                            },
                            "search_type": {
                                "type": "string",
                                "enum": ["vector", "semantic", "hybrid"],
                                "description": "Type of search (hybrid recommended for best results)",
                                "default": "hybrid"
                            },
                            "filters": {
                                "type": "string",
                                "description": "Optional OData filter expression (e.g., \"source eq 'manual.pdf'\")",
                                "default": ""
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    def _get_azure_sql_function_definitions(self) -> List[Dict]:
        """Get function definitions for Azure SQL tools (cloud)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "execute_sql_query",
                    "description": "Execute SQL query on Azure SQL Database (cloud). Returns query results as JSON. Use this for SELECT queries on cloud databases. **CRITICAL**: Always call get_database_schema FIRST to understand the database structure. For INSERT/UPDATE/DELETE operations, set require_approval=true.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "SQL query to execute (e.g., 'SELECT * FROM users WHERE age > 18')"
                            },
                            "database": {
                                "type": "string",
                                "description": "Database name (e.g., 'production', 'staging')"
                            },
                            "require_approval": {
                                "type": "boolean",
                                "description": "Whether user approval is required before executing (set to true for INSERT/UPDATE/DELETE)",
                                "default": False
                            }
                        },
                        "required": ["query", "database"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_database_schema",
                    "description": "Get complete Azure SQL database schema including all tables and their columns. **CRITICAL**: You MUST call this function FIRST before attempting any SQL queries to understand what tables and columns exist.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "database": {
                                "type": "string",
                                "description": "Database name (e.g., 'production', 'staging')"
                            }
                        },
                        "required": ["database"]
                    }
                }
            }
        ]

    def _get_mcp_function_definitions(self, mcp_url: str) -> List[Dict]:
        """Get function definitions for MCP server tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "call_mcp_server",
                    "description": f"Call MCP server at {mcp_url}. Executes actions on the external MCP server and returns results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "Action to perform on the MCP server"
                            },
                            "params": {
                                "type": "object",
                                "description": "Action parameters as a JSON object",
                                "default": {}
                            }
                        },
                        "required": ["action"]
                    }
                }
            }
        ]
