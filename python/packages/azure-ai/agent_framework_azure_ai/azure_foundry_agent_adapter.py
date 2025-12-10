"""
Azure Foundry Agent Adapter

Wraps Azure AI Foundry agents to implement the local AgentProtocol interface,
enabling seamless integration with the existing agent framework orchestration.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from agent_framework._threads import AgentThread
from agent_framework._types import (
    AgentRunResponse,
    AgentRunResponseUpdate,
    ChatMessage,
    Role,
)

try:
    from azure.ai.agents.aio import AgentsClient
    from azure.ai.agents.models import Agent, AgentStreamEvent
except ImportError:
    raise ImportError(
        "Azure AI Agents package not installed. "
        "Install with: pip install azure-ai-agents"
    )

logger = logging.getLogger(__name__)


class AzureFoundryAgentAdapter:
    """
    Adapter that wraps Azure Foundry agents to implement local AgentProtocol.

    This adapter bridges Azure-hosted agents with the local orchestration framework,
    handling message conversion, thread management, tool execution, and event streaming.

    Example:
        ```python
        from azure.ai.projects.aio import AIProjectClient
        from azure.identity.aio import DefaultAzureCredential

        # Initialize Azure clients
        credential = DefaultAzureCredential()
        project_client = AIProjectClient(
            credential=credential,
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"]
        )

        # Create adapter
        adapter = AzureFoundryAgentAdapter(
            agents_client=project_client.agents,
            agent_id="agent-xyz",
            agent_name="supervisor_agent",
            tool_executor=tool_executor
        )

        # Use like any other agent
        response = await adapter.run("Analyze sales data")
        ```
    """

    def __init__(
        self,
        agents_client: AgentsClient,
        agent_id: str,
        agent_name: str,
        description: str | None = None,
        tool_executor: ToolExecutor | None = None,
    ):
        """
        Initialize the Azure Foundry Agent Adapter.

        Args:
            agents_client: Azure AgentsClient instance
            agent_id: ID of the agent in Azure Foundry
            agent_name: Name of the agent
            description: Optional description
            tool_executor: Optional ToolExecutor for handling tool calls
        """
        self.agents_client = agents_client
        self.agent_id = agent_id
        self._name = agent_name
        self._description = description
        self.tool_executor = tool_executor

    @property
    def id(self) -> str:
        """Agent ID"""
        return self.agent_id

    @property
    def name(self) -> str | None:
        """Agent name"""
        return self._name

    @property
    def display_name(self) -> str:
        """Display name for the agent"""
        return self._name or self.agent_id

    @property
    def description(self) -> str | None:
        """Agent description"""
        return self._description

    async def run(
        self,
        messages: str | ChatMessage | list[ChatMessage] | None = None,
        *,
        thread: AgentThread | None = None,
        **kwargs: Any,
    ) -> AgentRunResponse:
        """
        Execute agent and return final response.

        Args:
            messages: Input message(s) - can be string, ChatMessage, or list
            thread: Optional AgentThread for conversation continuity
            **kwargs: Additional arguments (ignored)

        Returns:
            AgentRunResponse with the agent's response

        Raises:
            ValueError: If tool execution fails or agent errors
        """
        # Normalize input to string
        user_message = self._normalize_message(messages)
        logger.debug(f"Running agent {self.agent_id} with message: {user_message[:100]}...")

        # Create or reuse thread
        thread_id = await self._get_or_create_thread(thread)

        try:
            # Add user message
            await self.agents_client.create_message(
                thread_id=thread_id, role="user", content=user_message
            )

            # Run agent
            run = await self.agents_client.create_run(
                thread_id=thread_id, agent_id=self.agent_id
            )

            # Wait for completion and handle tool calls
            while run.status in ["queued", "in_progress", "requires_action"]:
                if run.status == "requires_action":
                    logger.debug(f"Agent requires action: executing tools")
                    # Execute tool calls
                    tool_outputs = await self._execute_tools(
                        run.required_action.submit_tool_outputs.tool_calls
                    )

                    # Submit tool outputs
                    run = await self.agents_client.submit_tool_outputs(
                        thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs
                    )
                else:
                    # Poll for updates
                    await asyncio.sleep(0.5)
                    run = await self.agents_client.get_run(thread_id, run.id)

            # Check final status
            if run.status == "failed":
                error_msg = getattr(run, "last_error", {}).get("message", "Unknown error")
                raise ValueError(f"Agent run failed: {error_msg}")

            # Get messages
            messages_response = await self.agents_client.list_messages(thread_id)

            # Convert to AgentRunResponse
            return self._convert_to_agent_response(messages_response, thread_id)

        except Exception as e:
            logger.error(f"Error running agent {self.agent_id}: {e}")
            raise

    async def run_stream(
        self,
        messages: str | ChatMessage | list[ChatMessage] | None = None,
        *,
        thread: AgentThread | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[AgentRunResponseUpdate]:
        """
        Execute agent with streaming responses.

        Args:
            messages: Input message(s)
            thread: Optional AgentThread
            **kwargs: Additional arguments

        Yields:
            AgentRunResponseUpdate: Streaming updates from the agent
        """
        user_message = self._normalize_message(messages)
        thread_id = await self._get_or_create_thread(thread)

        logger.debug(f"Streaming agent {self.agent_id}...")

        try:
            await self.agents_client.create_message(
                thread_id=thread_id, role="user", content=user_message
            )

            # Stream run
            async with self.agents_client.create_run_stream(
                thread_id=thread_id, agent_id=self.agent_id
            ) as stream:
                async for event in stream:
                    # Convert Azure events to AgentRunResponseUpdate
                    update = self._convert_event_to_update(event)
                    if update:
                        yield update

                    # Handle tool calls in streaming
                    if event.event == "thread.run.requires_action":
                        logger.debug("Executing tools in stream...")
                        tool_outputs = await self._execute_tools(
                            event.data.required_action.submit_tool_outputs.tool_calls
                        )
                        await stream.submit_tool_outputs(tool_outputs)

        except Exception as e:
            logger.error(f"Error streaming agent {self.agent_id}: {e}")
            raise

    def get_new_thread(self, **kwargs: Any) -> AgentThread:
        """
        Create new thread for agent.

        Args:
            **kwargs: Additional thread arguments

        Returns:
            New AgentThread instance
        """
        return AgentThread(**kwargs)

    async def _get_or_create_thread(self, thread: AgentThread | None) -> str:
        """Get existing thread ID or create new thread"""
        if thread and thread.service_thread_id:
            return thread.service_thread_id

        # Create new thread
        azure_thread = await self.agents_client.create_thread()
        return azure_thread.id

    async def _execute_tools(self, tool_calls) -> list[dict]:
        """Execute tool calls using registered tool executor"""
        if not self.tool_executor:
            logger.warning("No tool executor configured, skipping tool calls")
            return []

        outputs = []
        for tool_call in tool_calls:
            try:
                logger.debug(f"Executing tool: {tool_call.function.name}")
                result = await self.tool_executor.execute(
                    tool_call.function.name,
                    json.loads(tool_call.function.arguments),
                )
                outputs.append(
                    {"tool_call_id": tool_call.id, "output": json.dumps(result)}
                )
            except Exception as e:
                logger.error(f"Tool execution failed: {e}")
                outputs.append(
                    {
                        "tool_call_id": tool_call.id,
                        "output": json.dumps({"error": str(e)}),
                    }
                )

        return outputs

    def _normalize_message(self, messages) -> str:
        """Convert various message formats to string"""
        if isinstance(messages, str):
            return messages
        elif isinstance(messages, ChatMessage):
            return messages.text or ""
        elif isinstance(messages, list):
            return "\n".join(
                m.text if isinstance(m, ChatMessage) else str(m) for m in messages
            )
        return str(messages) if messages else ""

    def _convert_to_agent_response(
        self, messages_response, thread_id: str
    ) -> AgentRunResponse:
        """Convert Azure messages to AgentRunResponse"""
        # Get latest assistant message
        assistant_messages = [m for m in messages_response.data if m.role == "assistant"]
        if not assistant_messages:
            raise ValueError("No assistant response found")

        latest = assistant_messages[0]

        # Extract text content
        text_content = ""
        for content in latest.content:
            if hasattr(content, "text"):
                text_content += content.text.value

        return AgentRunResponse(
            messages=[ChatMessage(role=Role.ASSISTANT, text=text_content)],
            response_id=latest.id,
            value={"thread_id": thread_id},
            additional_properties={"azure_message_id": latest.id},
        )

    def _convert_event_to_update(
        self, event: AgentStreamEvent
    ) -> AgentRunResponseUpdate | None:
        """Convert Azure stream event to AgentRunResponseUpdate"""
        if event.event == "thread.message.delta":
            # Text delta
            if hasattr(event.data.delta, "content"):
                for content in event.data.delta.content:
                    if hasattr(content, "text"):
                        return AgentRunResponseUpdate(
                            contents=content.text.value, role=Role.ASSISTANT
                        )

        return None


class ToolExecutor:
    """
    Executes tool calls for Azure agents by mapping to local implementations.

    Manages a registry of tool handlers and routes tool calls to the appropriate
    handler function, supporting both sync and async handlers.

    Example:
        ```python
        executor = ToolExecutor()

        # Register synchronous tool
        def get_schema(database: str) -> str:
            return connector.get_schema()

        executor.register("get_database_schema", get_schema)

        # Register asynchronous tool
        async def execute_query(query: str, database: str):
            return await connector.run_query_async(query)

        executor.register("execute_sql_query", execute_query)

        # Execute tools
        result = await executor.execute("get_database_schema", {"database": "sales"})
        ```
    """

    def __init__(self):
        """Initialize the ToolExecutor with empty handler registry"""
        self.handlers: dict[str, Any] = {}

    def register(self, tool_name: str, handler):
        """
        Register a tool handler.

        Args:
            tool_name: Name of the tool (must match Azure agent tool definition)
            handler: Function or coroutine to handle tool calls
        """
        self.handlers[tool_name] = handler
        logger.debug(f"Registered tool handler: {tool_name}")

    def unregister(self, tool_name: str) -> bool:
        """
        Unregister a tool handler.

        Args:
            tool_name: Name of the tool to unregister

        Returns:
            True if tool was unregistered, False if not found
        """
        if tool_name in self.handlers:
            del self.handlers[tool_name]
            logger.debug(f"Unregistered tool handler: {tool_name}")
            return True
        return False

    async def execute(self, tool_name: str, arguments: dict) -> Any:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            arguments: Dictionary of arguments to pass to the tool

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool is not registered
        """
        if tool_name not in self.handlers:
            raise ValueError(f"Unknown tool: {tool_name}")

        handler = self.handlers[tool_name]

        # Handle both sync and async handlers
        try:
            if asyncio.iscoroutinefunction(handler):
                return await handler(**arguments)
            else:
                return handler(**arguments)
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            raise

    def list_tools(self) -> list[str]:
        """
        List all registered tool names.

        Returns:
            List of registered tool names
        """
        return list(self.handlers.keys())

    def has_tool(self, tool_name: str) -> bool:
        """
        Check if a tool is registered.

        Args:
            tool_name: Name of the tool

        Returns:
            True if tool is registered
        """
        return tool_name in self.handlers
