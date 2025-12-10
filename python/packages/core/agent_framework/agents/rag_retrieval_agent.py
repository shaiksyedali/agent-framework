"""RAG Retrieval Agent for semantic document search with configurable retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from agent_framework._agents import BaseAgent
from agent_framework._types import (
    AgentRunResponse,
    AgentRunResponseUpdate,
    ChatMessage,
    CitationAnnotation,
    Role,
    TextContent,
)
from agent_framework.data.vector_store import DocumentChunk, DocumentIngestionService


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
class RetrievedEvidence:
    """Structured record returned by RAGRetrievalAgent.

    Attributes:
        snippet: The text snippet retrieved from the document
        metadata: Metadata associated with the document chunk
        citation: Citation annotation with source information
    """
    snippet: str
    metadata: Mapping[str, Any]
    citation: CitationAnnotation


class RAGRetrievalAgent(BaseAgent):
    """Agent for retrieving unstructured data via semantic search.

    This agent performs semantic search over a vector store and returns
    relevant document chunks with citations. The number of documents
    retrieved is configurable (default: 20).

    Example:
        >>> from agent_framework.data.vector_store import InMemoryVectorStore, DocumentIngestionService
        >>> vector_store = InMemoryVectorStore()
        >>> ingestion_service = DocumentIngestionService(vector_store)
        >>> agent = RAGRetrievalAgent(
        ...     ingestion_service=ingestion_service,
        ...     top_k=20,
        ...     name="rag_retrieval_agent"
        ... )
        >>> response = await agent.run("What is the company's revenue policy?")
        >>> evidence = response.value  # List of RetrievedEvidence objects
    """

    def __init__(
        self,
        *,
        ingestion_service: DocumentIngestionService,
        top_k: int = 20,
        name: str | None = "rag_retrieval_agent",
        description: str | None = "Retrieves relevant documents via semantic search",
        tool_name: str = "rag_retrieval",
    ) -> None:
        """Initialize the RAG Retrieval Agent.

        Args:
            ingestion_service: Document ingestion service with vector store
            top_k: Number of documents to retrieve (default: 20)
            name: Agent name
            description: Agent description
            tool_name: Tool name used in citations
        """
        super().__init__(name=name, description=description)
        self._ingestion_service = ingestion_service
        self._top_k = top_k
        self._tool_name = tool_name

    async def run(
        self,
        messages: str | ChatMessage | Sequence[str | ChatMessage] | None = None,
        *,
        thread=None,
        top_k: int | None = None,
        **_: Any,
    ) -> AgentRunResponse:
        """Retrieve relevant documents based on the query.

        Args:
            messages: Query message(s) to search for
            thread: Optional thread for conversation tracking
            top_k: Override the default top_k for this run
            **_: Additional keyword arguments (ignored)

        Returns:
            AgentRunResponse with:
                - messages: ChatMessage with formatted results and citations
                - value: List of RetrievedEvidence objects
        """
        query = _to_string(messages)

        # Use runtime top_k if provided, otherwise use instance default
        k = top_k if top_k is not None else self._top_k

        # Search vector store
        results = self._ingestion_service.search(query, top_k=k)

        # Format results with citations
        evidence: list[RetrievedEvidence] = []
        contents: list[TextContent] = []

        for index, chunk in enumerate(results, start=1):
            citation = self._to_citation(chunk, index)
            text = chunk.text.strip()

            evidence.append(
                RetrievedEvidence(
                    snippet=text,
                    metadata=chunk.metadata,
                    citation=citation,
                )
            )

            contents.append(
                TextContent(
                    text=f"[{index}] {text}",
                    annotations=[citation],
                )
            )

        # Create response message
        response_message = ChatMessage(
            role=Role.ASSISTANT,
            contents=contents,
            additional_properties={
                "citations": [item.citation.to_dict() for item in evidence],
                "retrieval_query": query,
                "num_results": len(evidence),
                "requested_top_k": k,
            },
        )

        # Notify thread if provided
        if thread is not None:
            await self._notify_thread_of_new_messages(thread, [], [response_message])

        return AgentRunResponse(messages=[response_message], value=evidence)

    def run_stream(self, *args: Any, **kwargs: Any):
        """Streaming not supported for retrieval operations.

        Returns an async generator that yields an empty update.
        """
        async def _run():
            yield AgentRunResponseUpdate(messages=[])

        return _run()

    def _to_citation(self, chunk: DocumentChunk, index: int) -> CitationAnnotation:
        """Create citation annotation from document chunk.

        Args:
            chunk: Document chunk with text and metadata
            index: Index/rank of this result

        Returns:
            CitationAnnotation with source information
        """
        metadata = chunk.metadata or {}

        return CitationAnnotation(
            title=str(
                metadata.get("title", metadata.get("source", f"Result {index}"))
            ),
            url=str(metadata.get("url", "")) or None,
            file_id=str(metadata.get("file_id", metadata.get("id", ""))) or None,
            tool_name=self._tool_name,
            snippet=chunk.text.strip()[:200],  # Limit snippet to 200 chars
            additional_properties={"rank": index, **metadata},
        )
