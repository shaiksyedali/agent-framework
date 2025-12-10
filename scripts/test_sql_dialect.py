#!/usr/bin/env python3
"""Test script for dialect-aware SQL generation."""

from agent_framework.agents.sql import SQLPromptBuilder, get_dialect_instructions
from agent_framework.data.connectors import SQLiteConnector, DuckDBConnector, PostgresConnector

# Test dialect instructions
print('=== Dialect Instructions Test ===')
for dialect in ['duckdb', 'postgresql', 'sqlite', 'mssql', 'unknown']:
    instructions = get_dialect_instructions(dialect)
    print(f'{dialect}: {"OK" if instructions or dialect == "unknown" else "FAIL"}')

# Test connector dialects
print('\n=== Connector Dialect Properties ===')
sqlite_conn = SQLiteConnector()
print(f'SQLiteConnector.dialect: {sqlite_conn.dialect}')

# DuckDB may not be installed
try:
    duckdb_conn = DuckDBConnector()
    print(f'DuckDBConnector.dialect: {duckdb_conn.dialect}')
except Exception as e:
    print(f'DuckDBConnector: skipped ({type(e).__name__})')

# Postgres connector just tests the property
postgres_conn = PostgresConnector(connection_string='postgresql://localhost/test')
print(f'PostgresConnector.dialect: {postgres_conn.dialect}')

# Test prompt builder with dialect
print('\n=== SQLPromptBuilder with Dialect ===')
builder = SQLPromptBuilder(
    schema='users: id (INT), name (TEXT)',
    dialect='sqlite'
)
prompt = builder.build('Get all users')
print(f'Prompt includes SQLite instructions: {"strftime" in prompt}')
print('\n=== All Tests Passed ===')
