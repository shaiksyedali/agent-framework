import sqlite3

import pytest

from agent_framework.data import (
    DataConnectorError,
    DocumentIngestionService,
    DuckDBConnector,
    PostgresConnector,
    SQLApprovalPolicy,
    SQLiteConnector,
)
from agent_framework.orchestrator.context import OrchestrationContext


@pytest.fixture
def sqlite_db(tmp_path):
    db_path = tmp_path / "test.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    connection.executemany("INSERT INTO items (name) VALUES (?)", [("alpha",), ("bravo",)])
    connection.commit()
    connection.close()
    return str(db_path)


def test_sqlite_connector_schema_and_query(sqlite_db):
    connector = SQLiteConnector(database=sqlite_db)

    schema = connector.get_schema()
    assert "items" in schema
    assert "name" in schema

    rows = connector.run_query("SELECT name FROM items ORDER BY id")
    assert [row["name"] for row in rows] == ["alpha", "bravo"]


def test_duckdb_connector_runs_when_available(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    db_path = tmp_path / "test.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute("CREATE TABLE items (id INTEGER, name TEXT)")
    connection.execute("INSERT INTO items VALUES (1, 'alpha'), (2, 'bravo')")
    connection.close()

    connector = DuckDBConnector(database=str(db_path))
    schema = connector.get_schema()
    assert "items" in schema

    results = connector.run_query("SELECT name FROM items ORDER BY id")
    assert [row["name"] for row in results] == ["alpha", "bravo"]


def test_postgres_connector_requires_psycopg():
    connector = PostgresConnector(connection_string="postgresql://localhost:5432/dev")
    with pytest.raises(DataConnectorError):
        connector.get_schema()


def test_document_ingestion_and_retrieval():
    service = DocumentIngestionService()
    service.ingest(["The quick brown fox", "Azure agents manage workflows"], metadata={"source": "unit"})

    results = service.search("brown fox", top_k=1)
    assert len(results) == 1
    assert "fox" in results[0].text
    assert results[0].metadata["source"] == "unit"


def test_orchestration_context_surfaces_connectors(sqlite_db):
    context = OrchestrationContext()
    updated = context.with_connector("orders_db", SQLiteConnector(database=sqlite_db))

    assert "orders_db" not in context.connectors
    assert updated.get_connector("orders_db") is updated.connectors["orders_db"]
    assert updated.workflow_metadata == context.workflow_metadata


def test_sql_approval_policy_detects_risky_queries():
    policy = SQLApprovalPolicy(approval_required=False, engine="sqlite")

    assert policy.is_risky("DROP TABLE items")
    assert policy.should_request_approval("DELETE FROM users")
    assert "sqlite" in policy.summarize("DELETE FROM users")
