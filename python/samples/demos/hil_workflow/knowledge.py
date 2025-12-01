"""Vector-store style ingestion and retrieval helpers for the HIL sample API."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Annotated, Iterable, List, Optional, Sequence

from agent_framework import ai_function
from agent_framework.hil_workflow import AzureEmbeddingRetriever
from openai import AzureOpenAI
from pydantic import Field

from .persistence import Store

logger = logging.getLogger(__name__)


def _hash_to_vector(text: str, dims: int = 32) -> List[float]:
    """Deterministic embedding fallback so retrieval works offline."""

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # repeat the digest to cover requested dims
    values = list(digest) * ((dims // len(digest)) + 1)
    return [v / 255.0 for v in values[:dims]]


class EmbeddingBackend:
    """Embeds text using Azure OpenAI when configured, otherwise hashes.

    The goal is to support environments without network access while preferring
    Azure embeddings when credentials are available.
    """

    def __init__(self, *, embed_deployment: Optional[str] = None):
        self.embed_deployment = embed_deployment or os.getenv("AZURE_EMBED_DEPLOYMENT")
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION") or "2025-01-01-preview"
        self.dim = int(os.getenv("AZURE_EMBED_DIM", "1536"))
        self._client: AzureOpenAI | None = None

    @property
    def uses_azure(self) -> bool:
        return bool(self.embed_deployment and self.endpoint and self.api_key)

    def _ensure_client(self) -> AzureOpenAI:
        if not self.uses_azure:
            raise RuntimeError("Azure embedding credentials not configured")
        if self._client is None:
            self._client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version,
            )
        return self._client

    def embed(self, text: str) -> List[float]:
        if not text:
            return [0.0] * min(self.dim, 32)
        if self.uses_azure:
            try:
                response = self._ensure_client().embeddings.create(
                    model=self.embed_deployment,
                    input=[text],
                )
                return response.data[0].embedding
            except Exception as exc:  # pragma: no cover - network/credential failures
                logger.warning("Falling back to hash embedding: %s", exc)
        # deterministic fallback
        dims = min(self.dim, 64)
        return _hash_to_vector(text, dims=dims)


@dataclass
class IngestDocument:
    id: str
    text: str
    metadata: dict | None = None


class LocalVectorRetriever:
    """Cosine-similarity retriever for pre-computed embeddings."""

    def __init__(self, documents: Sequence[str], embeddings: Sequence[Sequence[float]], top_k: int = 4):
        self.documents = list(documents)
        self.embeddings = [list(vec) for vec in embeddings]
        self.top_k = top_k

    @staticmethod
    def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def tool(self):
        @ai_function(name="retrieve_docs", description="Retrieve vector-ranked snippets with citations")
        def retrieve_docs(question: Annotated[str, Field(description="User question text")]) -> str:  # type: ignore[name-defined]
            query_vec = _hash_to_vector(question, dims=len(self.embeddings[0]) if self.embeddings else 32)
            ranked = sorted(
                enumerate(self.embeddings),
                key=lambda pair: self._cosine_similarity(query_vec, pair[1]),
                reverse=True,
            )[: self.top_k]
            payload = [
                {"doc_id": idx, "snippet": self.documents[idx], "score": round(self._cosine_similarity(query_vec, emb), 3)}
                for idx, emb in ranked
            ]
            return json.dumps(payload)

        return retrieve_docs


class VectorStore:
    """Coordinates document ingestion, persistence, and retriever creation."""

    def __init__(self, store: Store, *, backend: Optional[EmbeddingBackend] = None):
        self.store = store
        self.backend = backend or EmbeddingBackend()

    def ingest(self, workflow_id: str, documents: Iterable[IngestDocument]) -> int:
        count = 0
        for doc in documents:
            embedding = self.backend.embed(doc.text)
            self.store.upsert_document(
                document_id=doc.id,
                workflow_id=workflow_id,
                content=doc.text,
                embedding=embedding,
                metadata=doc.metadata or {},
            )
            count += 1
        return count

    def retriever_for(self, workflow_id: str):
        docs = self.store.list_documents(workflow_id)
        if not docs:
            return None
        texts = [doc.content for doc in docs]
        embeddings = [doc.embedding for doc in docs]
        if self.backend.uses_azure:
            try:
                return AzureEmbeddingRetriever(documents=texts, precomputed_embeddings=embeddings)
            except Exception as exc:  # pragma: no cover - azure client failures
                logger.warning("Azure retriever unavailable, using local vector retriever: %s", exc)
        return LocalVectorRetriever(texts, embeddings)

