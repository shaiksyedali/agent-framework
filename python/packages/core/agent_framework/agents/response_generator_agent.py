"""Response Generator Agent for formatting final workflow responses."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent_framework._agents import ChatAgent
from agent_framework._clients import ChatClientProtocol
from agent_framework._types import AgentRunResponse

logger = logging.getLogger(__name__)


class ResponseGeneratorAgent:
    """Agent that generates final responses from workflow outputs.

    Synthesizes information from multiple workflow steps into a coherent,
    well-structured final response with citations, key findings, and
    follow-up suggestions.

    Example:
        >>> generator = ResponseGeneratorAgent(chat_client=client)
        >>> workflow_outputs = [
        ...     {"step_name": "Query Database", "result": {"sql": "SELECT...", "results": [...]}},
        ...     {"step_name": "Search Documents", "result": {"citations": [...]}}
        ... ]
        >>> response = await generator.generate_response(
        ...     workflow_outputs=workflow_outputs,
        ...     original_query="What were total sales last quarter?"
        ... )
        >>> print(response.text)  # Formatted final response
    """

    def __init__(
        self,
        chat_client: ChatClientProtocol,
        *,
        name: str = "response_generator",
    ):
        """Initialize the Response Generator Agent.

        Args:
            chat_client: Chat client for LLM-powered response generation
            name: Agent name
        """
        self.agent = ChatAgent(
            chat_client=chat_client,
            name=name,
            instructions=self._build_instructions(),
        )

    def _build_instructions(self) -> str:
        """Build instructions for the response generator."""
        return """
You are a response formatter. Your role is to synthesize information from
multiple workflow steps into a comprehensive, well-structured final response.

## Your Responsibilities

1. Synthesize information from multiple workflow steps
2. Create a coherent, well-structured final response
3. Include citations for all data sources (SQL queries, documents)
4. Highlight key findings with markdown formatting
5. Suggest 2-3 relevant follow-up questions
6. Use tables for structured data presentation
7. Maintain professional, concise tone

## Response Format

Structure your response as follows:

### Executive Summary
2-3 sentences summarizing the key findings and answering the original query.

### Main Findings
Present the core insights with supporting evidence. Use bullet points or
numbered lists for clarity. Include citations in square brackets [1], [2], etc.

### Supporting Data
Present any tabular data or visualizations. Format tables using markdown.

### Sources
List all data sources with citations:
- [1] SQL Query: `SELECT ...` - Database query returning X rows
- [2] Document: "Title" - Retrieved from knowledge base

### Follow-Up Questions
Suggest 2-3 relevant questions the user might want to explore next based on
the findings.

## Formatting Guidelines

- Use **bold** for key metrics and important findings
- Use tables for structured data (markdown format)
- Keep executive summary under 100 words
- Cite sources inline with [1], [2] notation
- Make follow-up questions specific and actionable
- Avoid technical jargon unless necessary
"""

    async def generate_response(
        self,
        workflow_outputs: List[Dict[str, Any]],
        original_query: str,
    ) -> AgentRunResponse:
        """Generate final response from workflow outputs.

        Args:
            workflow_outputs: List of outputs from each workflow step
                Each dict should have: {"step_name": str, "result": Any}
            original_query: Original user query

        Returns:
            AgentRunResponse with formatted final response
        """
        logger.info(f"Generating response for query: {original_query}")

        # Build context from all outputs
        context = self._build_context(workflow_outputs)

        # Generate response
        prompt = f"""
Original Query: {original_query}

Workflow Results:
{context}

Generate a comprehensive final response following the format specified in your
instructions. Include executive summary, main findings, supporting data, sources,
and follow-up questions.
"""

        response = await self.agent.run(prompt)

        # Add metadata
        if response.messages:
            response.messages[0].additional_properties = {
                "workflow_outputs": workflow_outputs,
                "original_query": original_query,
                "num_steps": len(workflow_outputs),
            }

        logger.info("Response generated successfully")

        return response

    def _build_context(self, outputs: List[Dict[str, Any]]) -> str:
        """Build context string from workflow outputs.

        Args:
            outputs: List of workflow step outputs

        Returns:
            Formatted context string
        """
        if not outputs:
            return "No workflow outputs available"

        context_parts = []

        for i, output in enumerate(outputs, 1):
            step_name = output.get("step_name", f"Step {i}")
            result = output.get("result")

            context_parts.append(f"## {step_name}")
            context_parts.append("")

            # Format based on result type
            if result is None:
                context_parts.append("No result")
            elif isinstance(result, dict):
                context_parts.append(self._format_dict_result(result))
            elif hasattr(result, "text"):
                # AgentRunResponse or similar
                context_parts.append(f"**Response:** {result.text}")
                if hasattr(result, "value") and result.value:
                    context_parts.append(f"\n**Metadata:** {result.value}")
            elif hasattr(result, "__dict__"):
                # Dataclass or object
                context_parts.append(self._format_object_result(result))
            else:
                # Fallback: string representation
                context_parts.append(str(result))

            context_parts.append("")  # Blank line

        return "\n".join(context_parts)

    def _format_dict_result(self, result: Dict[str, Any]) -> str:
        """Format dictionary result.

        Args:
            result: Result dictionary

        Returns:
            Formatted string
        """
        parts = []

        # Check for SQL results
        if "sql" in result:
            parts.append(f"**SQL Query:**\n```sql\n{result['sql']}\n```")

        if "results" in result and isinstance(result["results"], list):
            num_results = len(result["results"])
            parts.append(f"**Results:** {num_results} row(s)")

            # Show sample data
            if num_results > 0 and isinstance(result["results"][0], dict):
                parts.append("\nSample data:")
                sample = result["results"][:3]
                for row in sample:
                    parts.append(f"- {row}")

        # Check for citations
        if "citations" in result:
            num_citations = len(result["citations"])
            parts.append(f"**Sources:** {num_citations} document(s)")

        # Check for RAG evidence
        if "retrieval_query" in result:
            parts.append(f"**Search Query:** {result['retrieval_query']}")

        # Add any other keys
        for key, value in result.items():
            if key not in ["sql", "results", "citations", "retrieval_query", "raw_results"]:
                if isinstance(value, (str, int, float, bool)):
                    parts.append(f"**{key.replace('_', ' ').title()}:** {value}")

        return "\n".join(parts) if parts else str(result)

    def _format_object_result(self, result: Any) -> str:
        """Format object result.

        Args:
            result: Object with __dict__

        Returns:
            Formatted string
        """
        parts = []

        result_dict = vars(result) if hasattr(result, "__dict__") else {}

        for key, value in result_dict.items():
            if not key.startswith("_"):
                if isinstance(value, (str, int, float, bool)):
                    parts.append(f"**{key.replace('_', ' ').title()}:** {value}")
                elif isinstance(value, list) and value:
                    parts.append(f"**{key.replace('_', ' ').title()}:** {len(value)} item(s)")

        return "\n".join(parts) if parts else str(result)


def create_default_response(
    workflow_outputs: List[Dict[str, Any]],
    original_query: str,
) -> str:
    """Create a default response when response generator is not available.

    Args:
        workflow_outputs: List of workflow step outputs
        original_query: Original user query

    Returns:
        Simple formatted response string
    """
    parts = [
        f"# Workflow Results",
        "",
        f"**Query:** {original_query}",
        "",
        "## Steps Completed",
        "",
    ]

    for i, output in enumerate(workflow_outputs, 1):
        step_name = output.get("step_name", f"Step {i}")
        result = output.get("result")

        parts.append(f"### {i}. {step_name}")

        if result:
            if isinstance(result, dict):
                if "sql" in result:
                    parts.append(f"- SQL: `{result['sql']}`")
                if "results" in result:
                    parts.append(f"- Results: {len(result['results'])} row(s)")
            elif hasattr(result, "text"):
                parts.append(f"- Response: {result.text[:200]}")

        parts.append("")

    return "\n".join(parts)
