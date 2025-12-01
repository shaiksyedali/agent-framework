"""SQL connector implementations for popular databases."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from agent_framework.orchestrator.approvals import ApprovalType


class DataConnectorError(RuntimeError):
    """Raised when a connector cannot perform an operation."""


@dataclass
class SQLApprovalPolicy:
    """Controls when SQL execution should trigger an approval gate."""

    approval_required: bool = True
    preview_limit: int = 120
    summary_prefix: str = "Execute SQL query"
    engine: str = "generic"
    risky_statements: tuple[str, ...] = (
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "truncate",
        "replace",
    )

    def should_request_approval(self, query: str) -> bool:
        """Return whether approval should be requested for the given query."""

        normalized = query.strip()
        return bool(normalized) and (self.approval_required or self.is_risky(normalized))

    def is_risky(self, query: str) -> bool:
        """Detect potentially destructive statements such as DDL/DML."""

        lowered = query.lower()
        return any(re.search(rf"\b{keyword}\b", lowered) for keyword in self.risky_statements)

    def summarize(self, query: str) -> str:
        """Provide a concise summary to show when requesting approval."""

        normalized = " ".join(query.strip().split())
        if len(normalized) > self.preview_limit:
            normalized = f"{normalized[: self.preview_limit - 3]}..."
        return f"{self.summary_prefix} ({self.engine}): {normalized}" if normalized else self.summary_prefix


class SQLConnector:
    """Base class for SQL connectors used by agents."""

    def __init__(self, *, approval_policy: SQLApprovalPolicy | None = None) -> None:
        self.approval_policy = approval_policy or SQLApprovalPolicy()

    def get_schema(self) -> str:
        """Return a human-readable schema description for the data source."""

        raise NotImplementedError

    def run_query(self, query: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        """Run the query and return rows as dictionaries."""

        raise NotImplementedError

    @property
    def approval_type(self) -> ApprovalType:
        return ApprovalType.SQL


class SQLiteConnector(SQLConnector):
    """Lightweight connector for SQLite databases."""

    def __init__(self, database: str = ":memory:", *, approval_policy: SQLApprovalPolicy | None = None) -> None:
        super().__init__(approval_policy=approval_policy)
        self.approval_policy.engine = self.approval_policy.engine or "sqlite"
        self._database = database

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database)

    def get_schema(self) -> str:
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                schema_parts: list[str] = []
                for table_row in tables:
                    table_name = table_row["name"]
                    columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
                    column_descriptions = ", ".join(
                        f"{col['name']} ({col['type']})" for col in columns
                    )
                    schema_parts.append(f"{table_name}: {column_descriptions}")
                return "\n".join(schema_parts)
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise DataConnectorError(f"Failed to read SQLite schema: {exc}") from exc

    def run_query(self, query: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(query, params or [])
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise DataConnectorError(f"Failed to execute SQLite query: {exc}") from exc


class DuckDBConnector(SQLConnector):
    """Connector for DuckDB databases."""

    def __init__(self, database: str = ":memory:", *, read_only: bool = False, approval_policy: SQLApprovalPolicy | None = None) -> None:
        super().__init__(approval_policy=approval_policy)
        self.approval_policy.engine = self.approval_policy.engine or "duckdb"
        self._database = database
        self._read_only = read_only

    def _connect(self):  # pragma: no cover - thin wrapper
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - environment specific
            raise DataConnectorError(
                "duckdb is required to use DuckDBConnector. Install with `pip install duckdb`."
            ) from exc
        return duckdb.connect(self._database, read_only=self._read_only)

    def get_schema(self) -> str:
        connection = self._connect()
        try:
            tables = connection.execute("SHOW TABLES").fetchall()
            schema_parts: list[str] = []
            for (table_name,) in tables:
                columns = connection.execute(f"DESCRIBE {table_name}").fetchall()
                column_descriptions = ", ".join(f"{col[0]} ({col[1]})" for col in columns)
                schema_parts.append(f"{table_name}: {column_descriptions}")
            return "\n".join(schema_parts)
        except Exception as exc:  # pragma: no cover - defensive
            raise DataConnectorError(f"Failed to read DuckDB schema: {exc}") from exc
        finally:
            connection.close()

    def run_query(self, query: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            result = connection.execute(query, params)
            description = [col[0] for col in result.description]
            return [dict(zip(description, row)) for row in result.fetchall()]
        except Exception as exc:
            raise DataConnectorError(f"Failed to execute DuckDB query: {exc}") from exc
        finally:
            connection.close()


class PostgresConnector(SQLConnector):
    """Connector for Postgres databases using psycopg."""

    def __init__(
        self,
        connection_factory: Callable[[], Any] | None = None,
        *,
        connection_string: str | None = None,
        approval_policy: SQLApprovalPolicy | None = None,
    ) -> None:
        super().__init__(approval_policy=approval_policy)
        self.approval_policy.engine = self.approval_policy.engine or "postgres"
        self._connection_factory = connection_factory
        self._connection_string = connection_string

    def _open_connection(self):
        try:
            return self._connect()
        except Exception as exc:  # pragma: no cover - defensive
            raise DataConnectorError(f"Failed to open Postgres connection: {exc}") from exc

    def _connect(self):
        if self._connection_factory:
            return self._connection_factory()
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - environment specific
            raise DataConnectorError(
                "psycopg is required to use PostgresConnector. Install with `pip install psycopg[binary]`."
            ) from exc
        if not self._connection_string:
            raise DataConnectorError("connection_string is required when no connection_factory is provided")
        return psycopg.connect(self._connection_string)

    def get_schema(self) -> str:
        connection = self._open_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    ORDER BY table_name, ordinal_position
                    """
                )
                schema_parts: dict[str, list[str]] = {}
                for table_name, column_name, data_type in cursor.fetchall():
                    schema_parts.setdefault(table_name, []).append(f"{column_name} ({data_type})")
                return "\n".join(f"{table}: {', '.join(columns)}" for table, columns in schema_parts.items())
        except Exception as exc:
            raise DataConnectorError(f"Failed to read Postgres schema: {exc}") from exc
        finally:
            connection.close()

    def run_query(self, query: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        connection = self._open_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, params or [])
                description = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if description else []
                return [dict(zip(description, row)) for row in rows]
        except Exception as exc:
            raise DataConnectorError(f"Failed to execute Postgres query: {exc}") from exc
        finally:
            connection.close()
