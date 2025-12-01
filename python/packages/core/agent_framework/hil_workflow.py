"""Human-in-the-loop workflow scaffolding for multi-agent SQL/RAG orchestration.

This module wires the documented design into a runnable starter that:
- normalizes SQL connectors for DuckDB, SQLite, and Postgres
- exposes schema/query tools with approval gating and optional write blocking
- provides simple retrieval tooling for RAG grounding
- builds Planner → SQL → RAG → Reasoning → Response agents via ``SequentialBuilder``
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Callable, List, Optional, Sequence

try:  # Optional dependency for DuckDB-backed workflows
    import duckdb
except ImportError:  # pragma: no cover - handled at runtime for environments without duckdb
    duckdb = None

try:  # Optional dependency for Postgres-backed workflows
    import psycopg
except ImportError:  # pragma: no cover - handled at runtime for environments without psycopg
    psycopg = None

from pydantic import Field

from agent_framework import ChatAgent, SequentialBuilder, ai_function
from agent_framework.azure import AzureOpenAIChatClient
from openai import AzureOpenAI

WRITE_PATTERN = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|VACUUM|GRANT|REVOKE)\b", re.IGNORECASE)


class Engine(str, Enum):
    """Supported SQL engines for the multi-agent workflow."""

    DUCKDB = "duckdb"
    SQLITE = "sqlite"
    POSTGRES = "postgres"


@dataclass
class WorkflowConfig:
    """Top-level configuration supplied by the UI for building a workflow."""

    workflow_name: str
    persona: str
    sql_engine: Engine
    approval_mode: str = "always_require"
    allow_writes: bool = False
    duckdb_path: str = ":memory:"
    sqlite_path: str = ":memory:"
    postgres_dsn: Optional[str] = None
    retriever_top_k: int = 4
    calculator_tool: Optional[Callable] = None


class SQLConnector:
    """Base connector that exposes schema/query tools for a specific engine."""

    engine: Engine

    def tools(self) -> Sequence[Callable]:
        raise NotImplementedError

    @staticmethod
    def _guard_writes(sql: str, allow_writes: bool) -> None:
        if allow_writes:
            return
        if WRITE_PATTERN.search(sql):
            raise ValueError(
                "Write/DDL statements are disabled for this workflow. Request approval to enable writes."
            )


class DuckDBConnector(SQLConnector):
    """DuckDB connector with schema + query tools."""

    def __init__(self, path: str = ":memory:", approval_mode: str = "always_require", allow_writes: bool = False):
        if duckdb is None:  # pragma: no cover - import guarded at runtime
            raise ImportError("duckdb is not installed; install duckdb to use DuckDBConnector")
        self.engine = Engine.DUCKDB
        self._conn = duckdb.connect(database=path)
        self._approval_mode = approval_mode
        self._allow_writes = allow_writes

    def tools(self) -> Sequence[Callable]:
        @ai_function(name="duckdb_get_schema", description="Return schemas for referenced tables")
        def duckdb_get_schema(table: Annotated[str, Field(description="Table name")]) -> str:
            return self._conn.execute(f"DESCRIBE {table}").fetch_df().to_markdown(index=False)

        @ai_function(
            name="run_duckdb_query",
            description="Execute DuckDB SQL with optional approval",
            approval_mode=self._approval_mode,
        )
        def run_duckdb_query(sql: Annotated[str, Field(description="SQL to execute")]) -> str:
            SQLConnector._guard_writes(sql, self._allow_writes)
            return self._conn.execute(sql).fetch_df(limit=50).to_markdown(index=False)

        return [duckdb_get_schema, run_duckdb_query]


class SQLiteConnector(SQLConnector):
    """SQLite connector with schema + query tools."""

    def __init__(self, path: str = ":memory:", approval_mode: str = "always_require", allow_writes: bool = False):
        self.engine = Engine.SQLITE
        self._conn = sqlite3.connect(path)
        self._approval_mode = approval_mode
        self._allow_writes = allow_writes

    def tools(self) -> Sequence[Callable]:
        @ai_function(name="sqlite_get_schema", description="Return schemas for referenced tables")
        def sqlite_get_schema(table: Annotated[str, Field(description="Table name")]) -> str:
            cursor = self._conn.execute(f"PRAGMA table_info({table})")
            rows = cursor.fetchall()
            header = ["cid", "name", "type", "notnull", "default", "pk"]
            table_rows = [" | ".join(header)] + [" | ".join(str(col) for col in row) for row in rows]
            return "\n".join(table_rows)

        @ai_function(
            name="run_sqlite_query",
            description="Execute SQLite SQL with optional approval",
            approval_mode=self._approval_mode,
        )
        def run_sqlite_query(sql: Annotated[str, Field(description="SQL to execute")]) -> str:
            SQLConnector._guard_writes(sql, self._allow_writes)
            cursor = self._conn.execute(sql)
            rows = cursor.fetchall()
            header = [description[0] for description in cursor.description]
            table_rows = [" | ".join(header)] + [" | ".join(str(col) for col in row) for row in rows[:50]]
            return "\n".join(table_rows)

        return [sqlite_get_schema, run_sqlite_query]


class PostgresConnector(SQLConnector):
    """Postgres connector using psycopg (if available)."""

    def __init__(
        self,
        dsn: str,
        approval_mode: str = "always_require",
        allow_writes: bool = False,
    ):
        if psycopg is None:  # pragma: no cover - import guarded at runtime
            raise ImportError("psycopg is not installed; install psycopg[binary] to use PostgresConnector")
        self.engine = Engine.POSTGRES
        self._dsn = dsn
        self._approval_mode = approval_mode
        self._allow_writes = allow_writes

    def _fetch(self, sql: str) -> List[tuple]:
        SQLConnector._guard_writes(sql, self._allow_writes)
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                # psycopg exposes column names via description
                columns = [desc[0] for desc in cur.description]
        return [tuple(columns)] + rows

    def tools(self) -> Sequence[Callable]:
        @ai_function(name="postgres_get_schema", description="Return schemas for referenced tables")
        def postgres_get_schema(table: Annotated[str, Field(description="Table name")]) -> str:
            rows = self._fetch(
                f"SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = '{table}'"
            )
            return "\n".join(" | ".join(str(col) for col in row) for row in rows)

        @ai_function(
            name="run_postgres_query",
            description="Execute Postgres SQL with optional approval",
            approval_mode=self._approval_mode,
        )
        def run_postgres_query(sql: Annotated[str, Field(description="SQL to execute")]) -> str:
            rows = self._fetch(sql)
            if not rows:
                return "(no rows)"
            header, *body = rows
            table_rows = [" | ".join(str(col) for col in header)] + [" | ".join(str(col) for col in row) for row in body[:50]]
            return "\n".join(table_rows)

        return [postgres_get_schema, run_postgres_query]


class LocalRetriever:
    """Toy retriever that returns cited snippets for RAG grounding."""

    def __init__(self, documents: Optional[List[str]] = None, top_k: int = 4):
        self.documents = documents or []
        self.top_k = top_k

    def tool(self) -> Callable:
        @ai_function(name="retrieve_docs", description="Retrieve cited snippets from local docs")
        def retrieve_docs(question: Annotated[str, Field(description="User question text")]) -> str:
            ranked = [doc for doc in self.documents if question.lower() in doc.lower()][: self.top_k]
            payload = [
                {"doc_id": idx, "snippet": doc, "score": 1.0 - (idx * 0.1)}
                for idx, doc in enumerate(ranked)
            ]
            return str(payload)

        return retrieve_docs


class AzureEmbeddingRetriever:
    """Azure OpenAI-backed retriever that embeds docs and queries for semantic RAG."""

    def __init__(
        self,
        documents: Optional[List[str]] = None,
        top_k: int = 4,
        *,
        embed_deployment: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.documents = documents or []
        self.top_k = top_k
        self.embed_deployment = embed_deployment or os.getenv("AZURE_EMBED_DEPLOYMENT")
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION") or "2025-01-01-preview"

        if not self.embed_deployment:
            raise ValueError("AZURE_EMBED_DEPLOYMENT is required for AzureEmbeddingRetriever")
        if not self.endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT is required for AzureEmbeddingRetriever")
        if not self.api_key:
            raise ValueError("AZURE_OPENAI_API_KEY is required for AzureEmbeddingRetriever")

        self._client = AzureOpenAI(
            api_key=self.api_key,
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
        )
        self._index = [(doc, self._embed(doc)) for doc in self.documents]

    def _embed(self, text: str) -> List[float]:
        response = self._client.embeddings.create(model=self.embed_deployment, input=[text])
        return response.data[0].embedding

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def tool(self) -> Callable:
        @ai_function(name="retrieve_docs", description="Retrieve Azure-embedded snippets with citations")
        def retrieve_docs(question: Annotated[str, Field(description="User question text")]) -> str:
            query_embedding = self._embed(question)
            ranked = sorted(
                self._index,
                key=lambda item: self._cosine_similarity(query_embedding, item[1]),
                reverse=True,
            )[: self.top_k]
            payload = [
                {"doc_id": idx, "snippet": doc, "score": round(self._cosine_similarity(query_embedding, emb), 3)}
                for idx, (doc, emb) in enumerate(ranked)
            ]
            return json.dumps(payload)

        return retrieve_docs


@dataclass
class HilOrchestrator:
    """Builds Planner → SQL → RAG → Reasoning → Response agents for HIL workflows."""

    config: WorkflowConfig
    sql_connector: SQLConnector
    retriever: Optional[LocalRetriever | AzureEmbeddingRetriever] = None
    extra_agents: Sequence[ChatAgent] = field(default_factory=list)
    chat_client_factory: Optional[Callable[[], AzureOpenAIChatClient]] = None
    _chat_client: Optional[AzureOpenAIChatClient] = field(default=None, init=False, repr=False)

    def _ensure_chat_client(self) -> AzureOpenAIChatClient:
        if self.chat_client_factory:
            return self.chat_client_factory()
        if self._chat_client is None:
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            if not endpoint or not api_key:
                raise ValueError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set for Azure chat usage")
            self._chat_client = AzureOpenAIChatClient(
                deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT")
                or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
                or "gpt-4o",
                endpoint=endpoint,
                api_key=api_key,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION") or "2025-01-01-preview",
            )
        return self._chat_client

    def _planner_agent(self) -> ChatAgent:
        instructions = (
            f"Plan the workflow for {self.config.workflow_name}. "
            "Ask for missing inputs before finalizing a plan. Use schema tools to validate tables."
        )
        tools = list(self.sql_connector.tools())
        if self.retriever:
            tools.append(self.retriever.tool())
        return ChatAgent(
            name="Planner",
            chat_client=self._ensure_chat_client(),
            instructions=instructions,
            tools=tools,
        )

    def _sql_agent(self) -> ChatAgent:
        instructions = (
            "Generate and execute SQL using few-shots, schema, and feedback. "
            "Retry on errors up to 3 times and surface raw rows for aggregations."
        )
        return ChatAgent(
            name="SQLAgent",
            chat_client=self._ensure_chat_client(),
            instructions=instructions,
            tools=list(self.sql_connector.tools()),
        )

    def _rag_agent(self) -> Optional[ChatAgent]:
        if not self.retriever:
            return None
        return ChatAgent(
            name="RAGAgent",
            chat_client=self._ensure_chat_client(),
            instructions="Answer with cited snippets from retrieved docs.",
            tools=[self.retriever.tool()],
        )

    def _reasoner_agent(self) -> ChatAgent:
        base_instructions = (
            "Fuse SQL and RAG evidence. If the draft includes math, call a calculator tool when provided. "
            "Return concise findings and note confidence."
        )
        tools: List[Callable] = []
        if self.config.calculator_tool:
            tools.append(self.config.calculator_tool)
        return ChatAgent(
            name="Reasoner",
            chat_client=self._ensure_chat_client(),
            instructions=base_instructions,
            tools=tools,
        )

    def _response_agent(self) -> ChatAgent:
        instructions = (
            f"You are the response formatter for {self.config.persona}. "
            "Summarize the workflow outcome with citations and suggest a follow-up question."
        )
        return ChatAgent(
            name="Responder",
            chat_client=self._ensure_chat_client(),
            instructions=instructions,
        )

    def build(self):
        participants: List[ChatAgent] = [self._planner_agent(), self._sql_agent()]
        rag_agent = self._rag_agent()
        if rag_agent:
            participants.append(rag_agent)
        participants.append(self._reasoner_agent())
        participants.append(self._response_agent())
        participants.extend(self.extra_agents)
        return SequentialBuilder().participants(participants).build()
