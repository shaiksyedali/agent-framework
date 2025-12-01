"""Lightweight document ingestion and retrieval utilities."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableSequence, Protocol, Sequence


class EmbeddingModel(Protocol):
    """Protocol for embedding models used by the ingestion service."""

    def embed(self, text: str) -> list[float]:
        """Convert text into a dense vector representation."""


class VectorStore(Protocol):
    """Protocol for storage backends that support vector similarity search."""

    def add(self, chunk: "DocumentChunk") -> None:
        ...

    def similarity_search(self, query_embedding: Sequence[float], top_k: int = 5) -> list[tuple["DocumentChunk", float]]:
        ...


@dataclass
class DocumentChunk:
    """Represents a piece of ingested content tracked in the vector store."""

    text: str
    embedding: list[float]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


class SimpleEmbeddingModel:
    """Deterministic embedding model suitable for tests and demos."""

    def __init__(self, dimensions: int = 8) -> None:
        self._dimensions = dimensions

    def embed(self, text: str) -> list[float]:  # pragma: no cover - trivial math
        tokens = text.lower().split()
        vector = [0.0 for _ in range(self._dimensions)]
        for token in tokens:
            bucket = hash(token) % self._dimensions
            vector[bucket] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]


class InMemoryVectorStore:
    """Naive in-memory vector store with cosine similarity."""

    def __init__(self) -> None:
        self._chunks: MutableSequence[DocumentChunk] = []

    def add(self, chunk: DocumentChunk) -> None:
        self._chunks.append(chunk)

    def similarity_search(self, query_embedding: Sequence[float], top_k: int = 5) -> list[tuple[DocumentChunk, float]]:
        scored: list[tuple[DocumentChunk, float]] = []
        for chunk in self._chunks:
            score = self._cosine_similarity(query_embedding, chunk.embedding)
            scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:  # pragma: no cover - trivial math
        if not a or not b:
            return 0.0
        numerator = sum(x * y for x, y in zip(a, b))
        denom_a = math.sqrt(sum(x * x for x in a))
        denom_b = math.sqrt(sum(y * y for y in b))
        if denom_a == 0 or denom_b == 0:
            return 0.0
        return numerator / (denom_a * denom_b)


class DocumentIngestionService:
    """Coordinates embedding and storage of unstructured content."""

    def __init__(
        self,
        *,
        embedding_model: EmbeddingModel | None = None,
        vector_store: VectorStore | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None:
        self._embedding_model = embedding_model or SimpleEmbeddingModel()
        self._vector_store = vector_store or InMemoryVectorStore()
        self._chunk_size = max(chunk_size, 1)
        self._chunk_overlap = max(min(chunk_overlap, self._chunk_size - 1), 0)

    @property
    def embedding_model(self) -> EmbeddingModel:
        return self._embedding_model

    @property
    def vector_store(self) -> VectorStore:
        return self._vector_store

    def ingest(
        self,
        documents: Sequence[str | Mapping[str, Any]],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Embed and persist documents, returning stored IDs for each chunk."""

        stored_ids: list[str] = []
        base_metadata = metadata or {}
        for idx, doc in enumerate(documents):
            if isinstance(doc, Mapping):
                text = str(doc.get("text", ""))
                doc_meta = {**base_metadata, **{k: v for k, v in doc.items() if k != "text"}}
                source_id = doc_meta.get("id") or doc_meta.get("source") or f"doc-{idx}"
            else:
                text = str(doc)
                doc_meta = dict(base_metadata)
                source_id = doc_meta.get("id") or f"doc-{idx}"

            for chunk_index, chunk_text in enumerate(self._chunk_text(text)):
                embedding = self._embedding_model.embed(chunk_text)
                combined_meta = {
                    **doc_meta,
                    "chunk_index": chunk_index,
                    "source_id": source_id,
                }
                chunk = DocumentChunk(text=chunk_text, embedding=embedding, metadata=combined_meta)
                self._vector_store.add(chunk)
                stored_ids.append(chunk.id)
        return stored_ids

    def search(self, query: str, *, top_k: int = 5) -> list[DocumentChunk]:
        """Retrieve the most similar ingested content for the query."""

        embedding = self._embedding_model.embed(query)
        return [chunk for chunk, _ in self._vector_store.similarity_search(embedding, top_k=top_k)]

    def _chunk_text(self, text: str) -> list[str]:
        cleaned = (text or "").strip()
        if not cleaned:
            return []
        if len(cleaned) <= self._chunk_size:
            return [cleaned]

        chunks: list[str] = []
        start = 0
        while start < len(cleaned):
            end = min(start + self._chunk_size, len(cleaned))
            chunks.append(cleaned[start:end].strip())
            if end == len(cleaned):
                break
            start = max(end - self._chunk_overlap, 0)
        return [chunk for chunk in chunks if chunk]
