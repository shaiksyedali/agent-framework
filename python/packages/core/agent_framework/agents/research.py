"""Composable agents for retrieval, reasoning, and response generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

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
    """Structured record returned by :class:`RetrievalAgent`."""

    snippet: str
    metadata: Mapping[str, Any]
    citation: CitationAnnotation


class RetrievalAgent(BaseAgent):
    """Retrieve relevant chunks with inline citation metadata."""

    def __init__(
        self,
        *,
        ingestion_service: DocumentIngestionService,
        top_k: int = 3,
        name: str | None = "Retrieval",
        description: str | None = "Finds relevant passages and returns citations",
        tool_name: str = "retrieval",
    ) -> None:
        super().__init__(name=name, description=description)
        self._ingestion_service = ingestion_service
        self._top_k = top_k
        self._tool_name = tool_name

    async def run(
        self,
        messages: str | ChatMessage | Sequence[str | ChatMessage] | None = None,
        *,
        thread=None,
        **_: Any,
    ) -> AgentRunResponse:
        query = _to_string(messages)
        results = self._ingestion_service.search(query, top_k=self._top_k)

        evidence: list[RetrievedEvidence] = []
        contents: list[TextContent] = []
        for index, chunk in enumerate(results, start=1):
            citation = self._to_citation(chunk, index)
            text = chunk.text.strip()
            evidence.append(RetrievedEvidence(snippet=text, metadata=chunk.metadata, citation=citation))
            contents.append(TextContent(text=f"[{index}] {text}", annotations=[citation]))

        response_message = ChatMessage(
            role=Role.ASSISTANT,
            contents=contents,
            additional_properties={
                "citations": [item.citation.to_dict() for item in evidence],
                "retrieval_query": query,
            },
        )

        if thread is not None:
            await self._notify_thread_of_new_messages(thread, [], [response_message])

        return AgentRunResponse(messages=[response_message], value=evidence)

    def run_stream(self, *args: Any, **kwargs: Any):  # pragma: no cover - not needed for tests
        async def _run():
            yield AgentRunResponseUpdate(messages=[])

        return _run()

    def _to_citation(self, chunk: DocumentChunk, index: int) -> CitationAnnotation:
        metadata = chunk.metadata or {}
        return CitationAnnotation(
            title=str(metadata.get("title", metadata.get("source", f"Result {index}"))),
            url=str(metadata.get("url", "")) or None,
            file_id=str(metadata.get("file_id", metadata.get("id", ""))) or None,
            tool_name=self._tool_name,
            snippet=chunk.text.strip(),
            additional_properties={"rank": index, **metadata},
        )


class ReasoningAgent(BaseAgent):
    """Combine retrieved evidence, detect math, and structure findings."""

    def __init__(
        self,
        *,
        name: str | None = "Reasoning",
        description: str | None = "Synthesizes evidence and spots quantitative work",
    ) -> None:
        super().__init__(name=name, description=description)

    async def run(
        self,
        messages: str | ChatMessage | Sequence[str | ChatMessage] | None = None,
        *,
        evidence: Iterable[RetrievedEvidence] | None = None,
        thread=None,
        **_: Any,
    ) -> AgentRunResponse:
        query = _to_string(messages)
        evidence_list = list(evidence or [])
        merged_text = "\n".join(item.snippet for item in evidence_list) or query
        math_required = self._contains_math_signal(query, merged_text)

        insights = [f"• {item.snippet}" for item in evidence_list] or [f"• {query}" if query else ""]
        summary = "\n".join(insights).strip()

        value = {
            "summary": summary,
            "math_required": math_required,
            "citations": [item.citation.to_dict() for item in evidence_list],
            "structured_evidence": [
                {"snippet": item.snippet, "metadata": dict(item.metadata)} for item in evidence_list
            ],
        }

        response_message = ChatMessage(
            role=Role.ASSISTANT,
            text=self._render_summary(summary, math_required),
            additional_properties={"analysis": value},
        )

        if thread is not None:
            await self._notify_thread_of_new_messages(thread, [], [response_message])

        return AgentRunResponse(messages=[response_message], value=value)

    def run_stream(self, *args: Any, **kwargs: Any):  # pragma: no cover - not needed for tests
        async def _run():
            yield AgentRunResponseUpdate(messages=[])

        return _run()

    @staticmethod
    def _contains_math_signal(query: str, merged_text: str) -> bool:
        signals = {"+", "-", "*", "/", "%", "sum", "average", "total", "ratio", "percent"}
        haystack = f"{query} {merged_text}".lower()
        return any(signal in haystack for signal in signals) or any(char.isdigit() for char in haystack)

    @staticmethod
    def _render_summary(summary: str, math_required: bool) -> str:
        if not summary:
            return "No evidence available yet."
        math_note = "(math likely needed)" if math_required else "(no math detected)"
        return f"Findings {math_note}:\n{summary}"


class ResponseGenerator(BaseAgent):
    """Format findings for UI consumption while keeping conversation context."""

    def __init__(
        self,
        *,
        conversation_history: list[ChatMessage] | None = None,
        name: str | None = "Response Generator",
        description: str | None = "Formats final answers and lightweight visuals",
    ) -> None:
        super().__init__(name=name, description=description)
        self._conversation_history = conversation_history or []

    async def run(
        self,
        messages: str | ChatMessage | Sequence[str | ChatMessage] | None = None,
        *,
        findings: Mapping[str, Any] | None = None,
        thread=None,
        **_: Any,
    ) -> AgentRunResponse:
        reasoning = findings or {}
        summary = reasoning.get("summary") or _to_string(messages)
        math_required = reasoning.get("math_required", False)
        citations = reasoning.get("citations", [])

        visualization = self._render_visualization(math_required, citations)
        formatted_text = self._format_response(summary, visualization)

        response_message = ChatMessage(
            role=Role.ASSISTANT,
            contents=[TextContent(text=formatted_text)],
            additional_properties={"visualization": visualization, "citations": citations},
        )

        self._conversation_history.append(response_message)
        if thread is not None:
            await self._notify_thread_of_new_messages(thread, [], [response_message])

        return AgentRunResponse(messages=[response_message], value={"history": self._conversation_history})

    def run_stream(self, *args: Any, **kwargs: Any):  # pragma: no cover - not needed for tests
        async def _run():
            yield AgentRunResponseUpdate(messages=[])

        return _run()

    @staticmethod
    def _render_visualization(math_required: bool, citations: Sequence[Mapping[str, Any]]) -> str:
        citation_count = len(citations)
        indicator = "■" * min(citation_count, 10)
        math_flag = "Math" if math_required else "General"
        return f"[{math_flag}] Evidence count: {citation_count} {indicator}"

    @staticmethod
    def _format_response(summary: str, visualization: str) -> str:
        parts = [summary.strip()] if summary else []
        if visualization:
            parts.append(visualization)
        return "\n\n".join(parts)

