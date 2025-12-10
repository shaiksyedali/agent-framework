"""
Azure Tools Integration Module

Integrates local and cloud tools with Azure Foundry agents.
Provides factory functions to create configured agent adapters with the appropriate tools.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from agent_framework.tools import LocalSQLTools, ToolConfig, ToolSelector

logger = logging.getLogger(__name__)


class AzureToolsIntegration:
    """
    Integrates tools (local and cloud) with Azure Foundry agents.

    Handles:
    - Local SQL tools (.db, .duckdb files) → Direct Python execution
    - Cloud SQL tools (Azure SQL) → Azure Functions
    - Cloud RAG tools (documents) → Azure Functions + Azure AI Search
    - Cloud MCP tools (MCP servers) → Azure Functions

    Example:
        ```python
        from azure.ai.projects.aio import AIProjectClient
        from azure.identity.aio import DefaultAzureCredential

        # Initialize Azure client
        credential = DefaultAzureCredential()
        project_client = AIProjectClient(
            credential=credential,
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"]
        )

        # Create integration
        integration = AzureToolsIntegration(
            agents_client=project_client.agents,
            azure_functions_url="https://myapp.azurewebsites.net"
        )

        # Setup tools for data sources
        tool_executor = integration.create_tool_executor(data_sources)

        # Create agent adapter with tools
        from agent_framework_azure_ai import AzureFoundryAgentAdapter
        adapter = AzureFoundryAgentAdapter(
            agents_client=project_client.agents,
            agent_id="agent-xyz",
            agent_name="sql_agent",
            tool_executor=tool_executor
        )
        ```
    """

    def __init__(
        self,
        agents_client: Any,
        azure_functions_url: str,
        api_key: Optional[str] = None,
    ):
        """
        Initialize Azure Tools Integration.

        Args:
            agents_client: Azure AgentsClient instance
            azure_functions_url: Base URL for Azure Functions
            api_key: Optional API key for Azure Functions authentication
        """
        self.agents_client = agents_client
        self.azure_functions_url = azure_functions_url.rstrip('/')
        self.api_key = api_key
        self.tool_selector = ToolSelector(azure_functions_url)

        logger.info(f"AzureToolsIntegration initialized with Azure Functions: {self.azure_functions_url}")

    def create_tool_executor(
        self,
        data_sources: List[Any],
    ) -> "ToolExecutor":
        """
        Create a ToolExecutor with registered tools based on data sources.

        Args:
            data_sources: List of DataSourceConfig objects

        Returns:
            ToolExecutor with all local and cloud tools registered

        Example:
            >>> executor = integration.create_tool_executor(data_sources)
            >>> executor.list_tools()
            ['query_database', 'get_database_schema', 'execute_azure_sql', 'consult_rag']
        """
        # Import here to avoid circular dependency
        from agent_framework_azure_ai import ToolExecutor

        executor = ToolExecutor()

        # Select tools based on data sources
        tools = self.tool_selector.select_tools(data_sources)

        # Register local tools
        for tool_config in tools["local_tools"]:
            self._register_local_tool(executor, tool_config)

        # Register cloud tools (as HTTP calls)
        for tool_config in tools["cloud_tools"]:
            self._register_cloud_tool(executor, tool_config)

        logger.info(
            f"Created ToolExecutor with {len(tools['local_tools'])} local tools "
            f"and {len(tools['cloud_tools'])} cloud tools"
        )

        return executor

    def _register_local_tool(
        self,
        executor: "ToolExecutor",
        tool_config: ToolConfig,
    ):
        """Register a local tool with the executor."""

        if tool_config.name == "local_sql":
            # Local SQL tools - register all methods
            instance = tool_config.instance

            if not instance:
                logger.error(f"No instance found for local SQL tool")
                return

            # Register execute_sql_query (matches agent tool definition)
            executor.register("execute_sql_query", instance.execute_sql_query)
            logger.debug(f"Registered local tool: execute_sql_query")

            # Register get_database_schema (matches agent tool definition)
            executor.register("get_database_schema", instance.get_database_schema)
            logger.debug(f"Registered local tool: get_database_schema")

            # Register list_tables (additional helper, not in agent definition)
            executor.register("list_tables", instance.list_tables)
            logger.debug(f"Registered local tool: list_tables")

            # Register describe_table (additional helper, not in agent definition)
            executor.register("describe_table", instance.describe_table)
            logger.debug(f"Registered local tool: describe_table")

        else:
            logger.warning(f"Unknown local tool type: {tool_config.name}")

    def _register_cloud_tool(
        self,
        executor: "ToolExecutor",
        tool_config: ToolConfig,
    ):
        """Register a cloud tool (Azure Function) as an HTTP-calling handler."""

        if tool_config.name == "consult_rag":
            # RAG tool - Azure AI Search
            async def consult_rag(
                query: str,
                index: str = "documents",
                top_k: int = 5,
                search_type: str = "hybrid",
                filters: str = "",
            ) -> Dict[str, Any]:
                """Search documents using Azure AI Search."""
                return await self._call_azure_function(
                    url=tool_config.url,
                    payload={
                        "query": query,
                        "index": index,
                        "top_k": top_k,
                        "search_type": search_type,
                        "filters": filters,
                    },
                )

            executor.register("consult_rag", consult_rag)
            logger.debug(f"Registered cloud tool: consult_rag")

        elif tool_config.name == "execute_azure_sql":
            # Azure SQL tool - register with agent-expected names
            async def execute_sql_query(
                query: str,
                database: str,
                require_approval: bool = False,
            ) -> Dict[str, Any]:
                """Execute SQL query on Azure SQL Database."""
                return await self._call_azure_function(
                    url=tool_config.url,
                    payload={
                        "query": query,
                        "database": database,
                        "require_approval": require_approval,
                    },
                )

            # Register with agent-expected name: execute_sql_query (not execute_azure_sql)
            executor.register("execute_sql_query", execute_sql_query)
            logger.debug(f"Registered cloud tool: execute_sql_query (Azure SQL)")

            # Also register get_database_schema (not get_azure_sql_schema)
            async def get_database_schema(
                database: str,
            ) -> Dict[str, Any]:
                """Get Azure SQL database schema."""
                schema_url = f"{self.azure_functions_url}/api/get_azure_sql_schema"
                return await self._call_azure_function(
                    url=schema_url,
                    payload={"database": database},
                )

            executor.register("get_database_schema", get_database_schema)
            logger.debug(f"Registered cloud tool: get_database_schema (Azure SQL)")

        elif tool_config.name == "call_mcp_server":
            # MCP server tool
            async def call_mcp_server(
                action: str,
                params: Optional[Dict[str, Any]] = None,
            ) -> Dict[str, Any]:
                """Call MCP server."""
                return await self._call_azure_function(
                    url=tool_config.url,
                    payload={
                        "action": action,
                        "params": params or {},
                        "mcp_url": tool_config.metadata.get("mcp_url"),
                    },
                )

            executor.register("call_mcp_server", call_mcp_server)
            logger.debug(f"Registered cloud tool: call_mcp_server")

        else:
            logger.warning(f"Unknown cloud tool type: {tool_config.name}")

    def register_agent_specific_tools(
        self,
        executor: "ToolExecutor",
        agent_name: str,
    ):
        """Register specific Azure Function tools based on agent role."""
        
        # 1. Supervisor Tools
        if "supervisor" in agent_name:
            # invoke_agent
            async def invoke_agent(
                agent_name: str,
                message: str,
            ) -> Dict[str, Any]:
                """Delegate task to another agent."""
                return await self._call_azure_function(
                    url=f"{self.azure_functions_url}/api/invoke_agent",
                    payload={"agent_name": agent_name, "message": message},
                )
            executor.register("invoke_agent", invoke_agent)
            
            # list_available_agents (shared)
            self._register_list_agents(executor)

        # 2. Planner Tools
        if "planner" in agent_name:
            # validate_data_source
            async def validate_data_source(
                source_type: str,
            ) -> Dict[str, Any]:
                """Validate data source availability."""
                return await self._call_azure_function(
                    url=f"{self.azure_functions_url}/api/validate_data_source",
                    payload={"source_type": source_type},
                )
            executor.register("validate_data_source", validate_data_source)
            
            # list_available_agents (shared)
            self._register_list_agents(executor)

        # 3. Response Generator Tools
        if "response" in agent_name: # response_generator
            # extract_citations
            async def extract_citations(
                outputs: List[Any],
            ) -> Dict[str, Any]:
                """Extract citations from outputs."""
                return await self._call_azure_function(
                    url=f"{self.azure_functions_url}/api/extract_citations",
                    payload={"outputs": outputs},
                )
            executor.register("extract_citations", extract_citations)
            
            # generate_followup_questions
            async def generate_followup_questions(
                context: Dict[str, Any],
                count: int = 3,
            ) -> Dict[str, Any]:
                """Generate follow-up questions."""
                return await self._call_azure_function(
                    url=f"{self.azure_functions_url}/api/generate_followup_questions",
                    payload={"context": context, "count": count},
                )
            executor.register("generate_followup_questions", generate_followup_questions)

    def _register_list_agents(self, executor: "ToolExecutor"):
        """Helper to register list_available_agents tool."""
        async def list_available_agents() -> Dict[str, Any]:
            """List all available agents."""
            return await self._call_azure_function(
                url=f"{self.azure_functions_url}/api/list_available_agents",
                payload={},
            )
        # Register with the name the agent expects
        executor.register("list_available_agents", list_available_agents)

    async def _call_azure_function(
        self,
        url: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Make HTTP call to Azure Function.

        Args:
            url: Azure Function URL
            payload: Request payload

        Returns:
            Function response as dictionary

        Raises:
            httpx.HTTPError: If request fails
        """
        headers = {"Content-Type": "application/json"}

        # Add API key if configured
        if self.api_key:
            headers["x-functions-key"] = self.api_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                logger.debug(f"Calling Azure Function: {url}")
                logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                )

                response.raise_for_status()
                result = response.json()

                logger.debug(f"Azure Function response: {json.dumps(result, indent=2)[:500]}")

                return result

            except httpx.HTTPError as e:
                logger.error(f"Azure Function call failed: {e}")
                logger.error(f"URL: {url}")
                logger.error(f"Payload: {json.dumps(payload, indent=2)}")

                # Return error response
                return {
                    "success": False,
                    "error": f"Azure Function call failed: {str(e)}",
                    "error_type": type(e).__name__,
                }

    def get_tool_definitions_for_agent(
        self,
        agent_type: str,
        data_sources: List[Any],
    ) -> List[Dict[str, Any]]:
        """
        Get tool function definitions for agent creation/update.

        Args:
            agent_type: Type of agent (e.g., "sql_agent", "rag_agent")
            data_sources: List of data sources

        Returns:
            List of tool function definitions in Azure Agents format

        Example:
            >>> definitions = integration.get_tool_definitions_for_agent(
            ...     agent_type="sql_agent",
            ...     data_sources=[db_datasource]
            ... )
            >>> # Use when updating agent tools
            >>> await agents_client.update_agent(
            ...     agent_id=sql_agent_id,
            ...     tools=definitions
            ... )
        """
        tools = self.tool_selector.select_tools(data_sources)

        # Collect all function definitions
        all_definitions = []

        # Add local tool definitions
        for tool_config in tools["local_tools"]:
            all_definitions.extend(tool_config.function_definitions)

        # Add cloud tool definitions
        for tool_config in tools["cloud_tools"]:
            all_definitions.extend(tool_config.function_definitions)

        logger.info(
            f"Generated {len(all_definitions)} tool definitions for agent type: {agent_type}"
        )

        return all_definitions


def create_agent_with_tools(
    agents_client: Any,
    agent_id: str,
    agent_name: str,
    data_sources: List[Any],
    azure_functions_url: str,
    api_key: Optional[str] = None,
    description: Optional[str] = None,
) -> "AzureFoundryAgentAdapter":
    """
    Factory function to create an Azure Foundry agent adapter with tools.

    Args:
        agents_client: Azure AgentsClient instance
        agent_id: ID of the agent in Azure Foundry
        agent_name: Name of the agent
        data_sources: List of data sources to create tools for
        azure_functions_url: Base URL for Azure Functions
        api_key: Optional API key for Azure Functions
        description: Optional agent description

    Returns:
        Configured AzureFoundryAgentAdapter ready for use

    Example:
        ```python
        from azure.ai.projects.aio import AIProjectClient
        from azure.identity.aio import DefaultAzureCredential

        credential = DefaultAzureCredential()
        project_client = AIProjectClient(
            credential=credential,
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"]
        )

        # Create SQL agent with tools
        sql_agent = create_agent_with_tools(
            agents_client=project_client.agents,
            agent_id="asst_WyXNFtXxcLqqUQKrlwkr3g3U",
            agent_name="sql_agent",
            data_sources=[db_datasource],
            azure_functions_url="https://myapp.azurewebsites.net"
        )

        # Use the agent
        result = await sql_agent.run("What are the top 10 customers?")
        ```
    """
    from agent_framework_azure_ai import AzureFoundryAgentAdapter

    # Create integration
    integration = AzureToolsIntegration(
        agents_client=agents_client,
        azure_functions_url=azure_functions_url,
        api_key=api_key,
    )

    # Create tool executor with all tools
    tool_executor = integration.create_tool_executor(data_sources)

    # Create agent adapter
    adapter = AzureFoundryAgentAdapter(
        agents_client=agents_client,
        agent_id=agent_id,
        agent_name=agent_name,
        description=description,
        tool_executor=tool_executor,
    )

    logger.info(
        f"Created agent '{agent_name}' with {len(tool_executor.list_tools())} tools (before agent-specific)"
    )

    # Register specific tools for this agent role
    integration.register_agent_specific_tools(tool_executor, agent_name)

    logger.info(
        f"Finalized agent '{agent_name}' with {len(tool_executor.list_tools())} tools"
    )

    return adapter


def create_multi_agent_system(
    agents_client: Any,
    agent_configs: Dict[str, Dict[str, Any]],
    data_sources: List[Any],
    azure_functions_url: str,
    api_key: Optional[str] = None,
) -> Dict[str, "AzureFoundryAgentAdapter"]:
    """
    Create multiple agents with appropriate tools based on their roles.

    Args:
        agents_client: Azure AgentsClient instance
        agent_configs: Dictionary mapping agent names to their configs
            Example: {
                "sql_agent": {"id": "asst_xyz", "description": "SQL expert"},
                "rag_agent": {"id": "asst_abc", "description": "RAG expert"}
            }
        data_sources: List of data sources
        azure_functions_url: Base URL for Azure Functions
        api_key: Optional API key for Azure Functions

    Returns:
        Dictionary mapping agent names to configured adapters

    Example:
        ```python
        agent_configs = {
            "supervisor": {"id": "asst_m2QXNBwm581MG07JNMpEWrjp"},
            "sql_agent": {"id": "asst_WyXNFtXxcLqqUQKrlwkr3g3U"},
            "rag_agent": {"id": "asst_gt2ZvhKg1w23w5MVp4IlvGQ6"},
        }

        agents = create_multi_agent_system(
            agents_client=project_client.agents,
            agent_configs=agent_configs,
            data_sources=data_sources,
            azure_functions_url="https://myapp.azurewebsites.net"
        )

        # Use agents
        sql_result = await agents["sql_agent"].run("Query the database")
        rag_result = await agents["rag_agent"].run("Search documents")
        ```
    """
    agents = {}

    for agent_name, config in agent_configs.items():
        agent = create_agent_with_tools(
            agents_client=agents_client,
            agent_id=config["id"],
            agent_name=agent_name,
            data_sources=data_sources,
            azure_functions_url=azure_functions_url,
            api_key=api_key,
            description=config.get("description"),
        )

        agents[agent_name] = agent

    logger.info(f"Created multi-agent system with {len(agents)} agents")

    return agents
