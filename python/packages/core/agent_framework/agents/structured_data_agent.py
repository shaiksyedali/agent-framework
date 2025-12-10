"""Structured Data Agent for database queries with RAG-enhanced SQL generation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

from agent_framework._agents import BaseAgent
from agent_framework._types import (
    AgentRunResponse,
    AgentRunResponseUpdate,
    ChatMessage,
    Role,
    TextContent,
)
from agent_framework.agents.sql import SQLAgent, SQLExample, SQLExecutionResult
from agent_framework.data.connectors import DataConnectorError, SQLConnector

logger = logging.getLogger(__name__)


def _to_string(message: str | ChatMessage | Sequence[str | ChatMessage] | None) -> str:
    """Extract plain text from flexible message inputs."""
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    if isinstance(message, ChatMessage):
        return message.text
    return "\n".join(_to_string(item) for item in message)


@dataclass
class StructuredDataResult:
    """Result from structured data agent execution.

    Attributes:
        sql: The SQL query that was executed
        results: Query results as list of row dictionaries
        raw_results: Raw results if aggregation was detected
        attempts: List of SQL generation/execution attempts
        schema_context: Schema documentation from RAG (if available)
    """
    sql: str | None
    results: list[dict[str, Any]] | None
    raw_results: list[dict[str, Any]] | None
    attempts: list[Any]  # SQLAttempt from sql.py
    schema_context: str = ""


class StructuredDataAgent(BaseAgent):
    """Agent for retrieving structured data from databases with RAG-enhanced query generation.

    This agent generates and executes SQL queries against structured databases
    (SQLite, DuckDB, PostgreSQL). It can optionally consult a RAG agent to
    retrieve schema documentation before generating queries, improving accuracy.

    Features:
        - Schema-aware SQL generation
        - Automatic retry logic (up to 3 attempts)
        - Aggregation detection with raw record retrieval
        - Optional RAG consultation for schema context
        - Write operation protection
        - Row limit enforcement

    Example:
        >>> from agent_framework.data.connectors import SQLiteConnector
        >>> from agent_framework.agents.rag_retrieval_agent import RAGRetrievalAgent
        >>> from agent_framework import ChatAgent
        >>>
        >>> connector = SQLiteConnector(db_path="data.db")
        >>> rag_agent = RAGRetrievalAgent(ingestion_service=ingestion_service)
        >>>
        >>> agent = StructuredDataAgent(
        ...     sql_agent=sql_agent,
        ...     connector=connector,
        ...     rag_agent=rag_agent,
        ...     max_retry_attempts=3
        ... )
        >>> response = await agent.run("What were total sales last quarter?")
        >>> result = response.value  # StructuredDataResult with SQL and results
    """

    def __init__(
        self,
        *,
        sql_agent: SQLAgent,
        connector: SQLConnector,
        rag_agent: BaseAgent | None = None,
        max_retry_attempts: int = 3,
        allow_writes: bool = False,
        row_limit: int = 500,
        fetch_raw_after_aggregation: bool = True,
        name: str | None = "structured_data_agent",
        description: str | None = "Retrieves data from structured databases",
        few_shot_examples: Sequence[SQLExample] | None = None,
    ) -> None:
        """Initialize the Structured Data Agent.

        Args:
            sql_agent: SQLAgent instance for SQL generation and execution
            connector: Database connector (SQLite, DuckDB, or Postgres)
            rag_agent: Optional RAG agent for schema documentation lookup
            max_retry_attempts: Maximum number of retry attempts for SQL generation
            allow_writes: Whether to allow write operations (INSERT, UPDATE, DELETE)
            row_limit: Maximum number of rows to return
            fetch_raw_after_aggregation: Whether to fetch raw rows for aggregations
            name: Agent name
            description: Agent description
            few_shot_examples: Optional list of example queries for few-shot learning
        """
        super().__init__(name=name, description=description)
        self.sql_agent = sql_agent
        self.connector = connector
        self.rag_agent = rag_agent
        self.max_retry_attempts = max_retry_attempts
        self.allow_writes = allow_writes
        self.row_limit = row_limit
        self.fetch_raw_after_aggregation = fetch_raw_after_aggregation
        self.few_shot_examples = list(few_shot_examples or [])

    async def run(
        self,
        messages: str | ChatMessage | Sequence[str | ChatMessage] | None = None,
        *,
        thread=None,
        **kwargs: Any,
    ) -> AgentRunResponse:
        """Execute structured data retrieval query.

        Process:
        1. Extract user query from messages
        2. Get database schema from connector
        3. If RAG agent available, consult it for schema documentation
        4. Generate SQL query using SQLAgent with schema + RAG context
        5. Validate and execute query
        6. Retry on errors (up to max_retry_attempts)
        7. Detect aggregations and fetch raw records if enabled
        8. Return structured results with metadata

        Args:
            messages: User query message(s)
            thread: Optional thread for conversation tracking
            **kwargs: Additional keyword arguments

        Returns:
            AgentRunResponse with:
                - messages: ChatMessage with formatted results
                - value: StructuredDataResult with SQL, results, and metadata
        """
        query = _to_string(messages)

        if not query:
            return self._empty_response(thread)

        logger.info(f"Processing structured data query: {query}")

        # Step 1: Get database schema
        try:
            schema = self.connector.get_schema()
        except Exception as e:
            logger.error(f"Failed to retrieve schema: {e}")
            return self._error_response(
                f"Failed to retrieve database schema: {e}",
                thread
            )

        # Step 2: Consult RAG for schema documentation (if available)
        schema_context = ""
        if self.rag_agent:
            try:
                rag_query = (
                    f"database schema documentation, table descriptions, "
                    f"and column meanings relevant to: {query}"
                )
                rag_result = await self.rag_agent.run(rag_query, top_k=5)
                schema_context = rag_result.text
                logger.info(f"Retrieved schema context from RAG: {len(schema_context)} chars")
            except Exception as e:
                logger.warning(f"RAG consultation failed, continuing without context: {e}")
                schema_context = ""

        # Step 3: Build enhanced schema prompt
        enhanced_schema = self._build_enhanced_schema(schema, schema_context)

        # Step 4: Generate and execute SQL with retry logic
        try:
            sql_result: SQLExecutionResult = await self.sql_agent.generate_and_execute(
                goal=query,
                connector=self.connector,
                schema=enhanced_schema,
                history=self.few_shot_examples,
                max_attempts=self.max_retry_attempts,
                allow_writes=self.allow_writes,
                row_limit=self.row_limit,
                fetch_raw_after_aggregation=self.fetch_raw_after_aggregation,
            )

            # Step 5: Format response
            response_message = self._format_success_response(
                query=query,
                sql_result=sql_result,
                schema_context=schema_context,
            )

            # Notify thread if provided
            if thread is not None:
                await self._notify_thread_of_new_messages(thread, [], [response_message])

            # Build structured result
            result = StructuredDataResult(
                sql=sql_result.sql,
                results=sql_result.rows,
                raw_results=sql_result.raw_rows,
                attempts=sql_result.attempts,
                schema_context=schema_context,
            )

            return AgentRunResponse(messages=[response_message], value=result)

        except DataConnectorError as e:
            logger.error(f"SQL execution failed: {e}")
            return self._error_response(str(e), thread)
        except Exception as e:
            logger.error(f"Unexpected error in structured data agent: {e}")
            return self._error_response(f"Unexpected error: {e}", thread)

    def run_stream(self, *args: Any, **kwargs: Any):
        """Streaming not supported for SQL operations.

        Returns an async generator that yields an empty update.
        """
        async def _run():
            yield AgentRunResponseUpdate(messages=[])

        return _run()

    def _build_enhanced_schema(self, schema: str, schema_context: str) -> str:
        """Build enhanced schema with RAG context.

        Args:
            schema: Base schema from database connector
            schema_context: Additional context from RAG retrieval

        Returns:
            Enhanced schema string
        """
        if not schema_context:
            return schema

        return (
            f"{schema}\n\n"
            f"Additional Context:\n"
            f"{schema_context}"
        )

    def _format_success_response(
        self,
        query: str,
        sql_result: SQLExecutionResult,
        schema_context: str,
    ) -> ChatMessage:
        """Format successful query execution as ChatMessage.

        Args:
            query: Original user query
            sql_result: Result from SQL execution
            schema_context: Schema context from RAG

        Returns:
            ChatMessage with formatted results
        """
        sql = sql_result.sql or "No SQL generated"
        rows = sql_result.rows or []
        raw_rows = sql_result.raw_rows or []

        # Build response text
        parts = [
            f"**Query:** {query}",
            f"\n**SQL:**\n```sql\n{sql}\n```",
            f"\n**Results:** {len(rows)} row(s) returned",
        ]

        if raw_rows:
            parts.append(f"\n**Raw Records:** {len(raw_rows)} row(s) (for aggregation)")

        if len(sql_result.attempts) > 1:
            parts.append(f"\n**Attempts:** {len(sql_result.attempts)} (succeeded on attempt {len(sql_result.attempts)})")

        response_text = "".join(parts)

        return ChatMessage(
            role=Role.ASSISTANT,
            contents=[TextContent(text=response_text)],
            additional_properties={
                "sql": sql,
                "results": rows,
                "raw_results": raw_rows,
                "num_results": len(rows),
                "num_raw_results": len(raw_rows),
                "num_attempts": len(sql_result.attempts),
                "used_rag_context": bool(schema_context),
                "query": query,
            },
        )

    def _empty_response(self, thread) -> AgentRunResponse:
        """Create response for empty query."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            contents=[TextContent(text="No query provided.")],
        )
        return AgentRunResponse(messages=[message], value=None)

    def _error_response(self, error: str, thread) -> AgentRunResponse:
        """Create error response.

        Args:
            error: Error message
            thread: Optional thread for notification

        Returns:
            AgentRunResponse with error message
        """
        message = ChatMessage(
            role=Role.ASSISTANT,
            contents=[TextContent(text=f"**Error:** {error}")],
            additional_properties={"error": error},
        )

        return AgentRunResponse(messages=[message], value=None)
