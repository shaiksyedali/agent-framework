# Azure Foundry Tools Implementation - SQL & RAG

## Architecture Overview

This document provides complete implementation for SQL and RAG tools supporting both local and cloud deployments for Azure Foundry agents.

### Tool Matrix

| Data Source Type | Tool Type | Execution Location | Tool Implementation |
|------------------|-----------|-------------------|---------------------|
| .db / .duckdb files | SQL | Local (Python) | `LocalSQLTools` class |
| Azure SQL Database | SQL | Cloud (Azure Function) | `execute_azure_sql` function |
| Local PDFs | RAG | Local + Azure AI Search | Hybrid: Ingest → Cloud search |
| Azure Blob PDFs | RAG | Cloud (Azure Function) | `consult_rag` function |
| Azure AI Search Index | RAG | Cloud (Azure Function) | `consult_rag` function |

### Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                    AZURE AI FOUNDRY AGENTS                             │
│  - RAG Agent (asst_gt2ZvhKg1w23w5MVp4IlvGQ6)                           │
│  - SQL Agent (asst_WyXNFtXxcLqqUQKrlwkr3g3U)                           │
└────────────────────────┬───────────────────────────────────────────────┘
                         │
                         │ Tool Calls (function_call)
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    TOOL ROUTER / ORCHESTRATOR                          │
│  Decides: Local tool or Cloud tool?                                   │
└────────┬───────────────────────────────────────────┬───────────────────┘
         │ Local Path                                 │ Cloud Path
         ▼                                            ▼
┌─────────────────────────┐              ┌───────────────────────────────┐
│   LOCAL TOOLS           │              │   AZURE FUNCTIONS             │
│   (Python on Backend)   │              │   (Serverless)                │
│                         │              │                               │
│ ┌─────────────────────┐ │              │ ┌───────────────────────────┐ │
│ │ LocalSQLTools       │ │              │ │ execute_azure_sql         │ │
│ │ - query_database()  │ │              │ │ (HTTP Trigger)            │ │
│ │ - get_schema()      │ │              │ │                           │ │
│ │ - list_tables()     │ │              │ │ Uses:                     │ │
│ └─────────┬───────────┘ │              │ │ - Managed Identity        │ │
│           │             │              │ │ - Key Vault (conn str)    │ │
│           ▼             │              │ └───────────┬───────────────┘ │
│ ┌─────────────────────┐ │              │             │                 │
│ │ test.db (SQLite)    │ │              │             ▼                 │
│ │ data.duckdb         │ │              │ ┌───────────────────────────┐ │
│ └─────────────────────┘ │              │ │ Azure SQL Database        │ │
│                         │              │ │ (Cloud)                   │ │
│                         │              │ └───────────────────────────┘ │
│                         │              │                               │
│                         │              │ ┌───────────────────────────┐ │
│                         │              │ │ consult_rag               │ │
│                         │              │ │ (HTTP Trigger)            │ │
│                         │              │ │                           │ │
│                         │              │ │ Uses:                     │ │
│                         │              │ │ - Managed Identity        │ │
│                         │              │ │ - Azure AI Search SDK     │ │
│                         │              │ └───────────┬───────────────┘ │
│                         │              │             │                 │
│                         │              │             ▼                 │
│                         │              │ ┌───────────────────────────┐ │
│                         │              │ │ Azure AI Search           │ │
│                         │              │ │ (Vector Store)            │ │
│                         │              │ └───────────────────────────┘ │
└─────────────────────────┘              └───────────────────────────────┘
```

---

## Part 1: Local SQL Tools

### File Structure
```
python/packages/core/agent_framework/tools/
├── __init__.py
├── local_sql_tools.py         # NEW: Local DB tools
└── azure_function_client.py   # NEW: Client for Azure Functions
```

### Implementation: `local_sql_tools.py`

```python
"""
Local SQL Tools for .db and .duckdb files
Runs on the backend server (not in Azure Functions)
"""

import sqlite3
import duckdb
from typing import List, Dict, Any, Optional
import json
from pathlib import Path


class LocalSQLTools:
    """
    SQL tools for local database files (.db, .duckdb)
    Used when data is on local filesystem or not accessible from cloud
    """

    def __init__(self, db_path: str):
        """
        Initialize local SQL tools

        Args:
            db_path: Path to database file (sqlite:///path/to/file.db or duckdb:///path/to/file.duckdb)
        """
        self.db_path = db_path
        self.db_type = self._detect_db_type(db_path)

    def _detect_db_type(self, db_path: str) -> str:
        """Detect database type from path"""
        if db_path.startswith("duckdb://"):
            return "duckdb"
        elif db_path.startswith("sqlite://"):
            return "sqlite"
        elif db_path.endswith(".duckdb"):
            return "duckdb"
        elif db_path.endswith(".db"):
            return "sqlite"
        else:
            return "sqlite"  # Default

    def _get_file_path(self) -> str:
        """Extract file path from connection string"""
        if "://" in self.db_path:
            return self.db_path.split("://")[1]
        return self.db_path

    async def query_database(
        self,
        query: str,
        parameters: Optional[List[Any]] = None
    ) -> str:
        """
        Execute SQL query on local database

        Args:
            query: SQL query to execute
            parameters: Optional query parameters (for parameterized queries)

        Returns:
            JSON string with query results

        Example:
            result = await tools.query_database("SELECT * FROM users WHERE age > ?", [18])
        """
        file_path = self._get_file_path()

        try:
            if self.db_type == "duckdb":
                conn = duckdb.connect(file_path, read_only=True)
                result = conn.execute(query, parameters or []).fetchall()
                columns = [desc[0] for desc in conn.description] if conn.description else []
                conn.close()
            else:  # sqlite
                conn = sqlite3.connect(file_path)
                cursor = conn.cursor()
                cursor.execute(query, parameters or [])
                result = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                conn.close()

            # Convert to list of dicts
            rows = [dict(zip(columns, row)) for row in result]

            return json.dumps({
                "success": True,
                "rows": rows,
                "row_count": len(rows),
                "columns": columns
            }, default=str)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            })

    async def get_database_schema(self) -> str:
        """
        Get database schema (tables and columns)

        Returns:
            JSON string with schema information

        Example:
            schema = await tools.get_database_schema()
        """
        file_path = self._get_file_path()

        try:
            if self.db_type == "duckdb":
                conn = duckdb.connect(file_path, read_only=True)

                # Get tables
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()

                schema = {}
                for (table_name,) in tables:
                    # Get columns for each table
                    columns = conn.execute(
                        f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table_name}'"
                    ).fetchall()
                    schema[table_name] = [
                        {"name": col[0], "type": col[1]} for col in columns
                    ]

                conn.close()

            else:  # sqlite
                conn = sqlite3.connect(file_path)
                cursor = conn.cursor()

                # Get tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()

                schema = {}
                for (table_name,) in tables:
                    # Get columns for each table
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = cursor.fetchall()
                    schema[table_name] = [
                        {"name": col[1], "type": col[2]} for col in columns
                    ]

                conn.close()

            return json.dumps({
                "success": True,
                "database": file_path,
                "database_type": self.db_type,
                "tables": schema,
                "table_count": len(schema)
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            })

    async def list_tables(self) -> str:
        """
        List all tables in database

        Returns:
            JSON string with table names
        """
        file_path = self._get_file_path()

        try:
            if self.db_type == "duckdb":
                conn = duckdb.connect(file_path, read_only=True)
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
                conn.close()
            else:  # sqlite
                conn = sqlite3.connect(file_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                conn.close()

            table_names = [t[0] for t in tables]

            return json.dumps({
                "success": True,
                "tables": table_names,
                "table_count": len(table_names)
            })

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            })

    async def describe_table(self, table_name: str) -> str:
        """
        Get detailed information about a specific table

        Args:
            table_name: Name of the table

        Returns:
            JSON string with table structure and sample data
        """
        file_path = self._get_file_path()

        try:
            if self.db_type == "duckdb":
                conn = duckdb.connect(file_path, read_only=True)

                # Get columns
                columns = conn.execute(
                    f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table_name}'"
                ).fetchall()

                # Get row count
                row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

                # Get sample data (first 5 rows)
                sample = conn.execute(f"SELECT * FROM {table_name} LIMIT 5").fetchall()
                col_names = [desc[0] for desc in conn.description]
                sample_data = [dict(zip(col_names, row)) for row in sample]

                conn.close()

            else:  # sqlite
                conn = sqlite3.connect(file_path)
                cursor = conn.cursor()

                # Get columns
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns_info = cursor.fetchall()
                columns = [(col[1], col[2]) for col in columns_info]

                # Get row count
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = cursor.fetchone()[0]

                # Get sample data
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
                sample = cursor.fetchall()
                col_names = [desc[0] for desc in cursor.description]
                sample_data = [dict(zip(col_names, row)) for row in sample]

                conn.close()

            return json.dumps({
                "success": True,
                "table_name": table_name,
                "columns": [{"name": col[0], "type": col[1]} for col in columns],
                "row_count": row_count,
                "sample_data": sample_data
            }, indent=2, default=str)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            })


# Function definitions for Azure Agents SDK
# These are the function definitions that will be registered with Azure agents

def get_local_sql_function_definitions(db_path: str) -> list:
    """
    Get function definitions for local SQL tools
    These will be passed to Azure agents as available tools
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "query_database",
                "description": f"Execute SQL query on local database: {db_path}. Returns query results as JSON. Use this for SELECT queries to retrieve data.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SQL query to execute (e.g., 'SELECT * FROM users WHERE age > 18')"
                        },
                        "parameters": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional query parameters for parameterized queries",
                            "default": []
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_database_schema",
                "description": "Get complete database schema including all tables and their columns. Use this FIRST before writing any queries to understand the database structure.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_tables",
                "description": "List all tables in the database. Quick way to see available tables.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "describe_table",
                "description": "Get detailed information about a specific table including columns, data types, row count, and sample data. Use this to understand a table's structure before querying it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table_name": {
                            "type": "string",
                            "description": "Name of the table to describe"
                        }
                    },
                    "required": ["table_name"]
                }
            }
        }
    ]
```

---

## Part 2: Azure Function - SQL Tool (Azure SQL)

### File Structure
```
azure-functions/
├── execute_azure_sql/
│   ├── __init__.py
│   └── function.json
├── host.json
└── requirements.txt
```

### Implementation: `azure-functions/execute_azure_sql/__init__.py`

```python
"""
Azure Function: SQL Tool for Azure SQL Database
Executes on Azure Functions (serverless)
Uses Managed Identity for secure authentication
"""

import azure.functions as func
import json
import logging
import os
import pyodbc
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from typing import Optional


async def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Execute SQL query on Azure SQL Database

    Request Body:
        {
            "query": "SELECT * FROM users",
            "database": "mydb",  // optional, defaults to configured database
            "parameters": []     // optional, for parameterized queries
        }

    Response:
        {
            "success": true,
            "rows": [...],
            "row_count": 10,
            "columns": ["id", "name", "email"]
        }
    """
    logging.info('Azure SQL Function triggered')

    try:
        # Parse request
        req_body = req.get_json()
        query = req_body.get('query')
        database = req_body.get('database', 'default')
        parameters = req_body.get('parameters', [])

        if not query:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Query is required"}),
                mimetype="application/json",
                status_code=400
            )

        logging.info(f"Executing query on {database}: {query[:100]}...")

        # Get connection string from Key Vault using Managed Identity
        vault_url = os.environ.get("KEY_VAULT_URL")
        if not vault_url:
            raise ValueError("KEY_VAULT_URL environment variable not set")

        credential = DefaultAzureCredential()
        secret_client = SecretClient(vault_url=vault_url, credential=credential)

        # Retrieve connection string securely
        # Secret name format: "{database}-connection-string"
        secret_name = f"{database}-connection-string"
        secret = secret_client.get_secret(secret_name)
        conn_string = secret.value

        # Connect to Azure SQL (can use private endpoint)
        conn = pyodbc.connect(conn_string)
        cursor = conn.cursor()

        # Execute query with parameters
        if parameters:
            cursor.execute(query, parameters)
        else:
            cursor.execute(query)

        # Fetch results
        if cursor.description:  # SELECT query
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            # Convert to list of dicts
            result_rows = [
                dict(zip(columns, [str(value) if value is not None else None for value in row]))
                for row in rows
            ]

            response = {
                "success": True,
                "rows": result_rows,
                "row_count": len(result_rows),
                "columns": columns
            }
        else:  # INSERT/UPDATE/DELETE
            conn.commit()
            response = {
                "success": True,
                "rows_affected": cursor.rowcount,
                "message": f"Query executed successfully. {cursor.rowcount} rows affected."
            }

        conn.close()

        logging.info(f"Query executed successfully. Row count: {response.get('row_count', 0)}")

        return func.HttpResponse(
            json.dumps(response, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except KeyError as e:
        logging.error(f"Missing required field: {str(e)}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": f"Missing required field: {str(e)}",
                "error_type": "KeyError"
            }),
            mimetype="application/json",
            status_code=400
        )

    except Exception as e:
        logging.error(f"Error executing SQL: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            mimetype="application/json",
            status_code=500
        )


# Helper function for schema retrieval
async def get_azure_sql_schema(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get schema for Azure SQL Database
    Can be deployed as separate function or endpoint
    """
    try:
        req_body = req.get_json()
        database = req_body.get('database', 'default')

        # Same Key Vault retrieval as above
        vault_url = os.environ.get("KEY_VAULT_URL")
        credential = DefaultAzureCredential()
        secret_client = SecretClient(vault_url=vault_url, credential=credential)
        secret_name = f"{database}-connection-string"
        secret = secret_client.get_secret(secret_name)
        conn_string = secret.value

        conn = pyodbc.connect(conn_string)
        cursor = conn.cursor()

        # Get schema information
        schema_query = """
        SELECT
            t.TABLE_NAME,
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.IS_NULLABLE
        FROM INFORMATION_SCHEMA.TABLES t
        JOIN INFORMATION_SCHEMA.COLUMNS c
            ON t.TABLE_NAME = c.TABLE_NAME
        WHERE t.TABLE_TYPE = 'BASE TABLE'
        ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION
        """

        cursor.execute(schema_query)
        rows = cursor.fetchall()

        # Group by table
        schema = {}
        for row in rows:
            table_name = row[0]
            if table_name not in schema:
                schema[table_name] = []
            schema[table_name].append({
                "name": row[1],
                "type": row[2],
                "nullable": row[3] == 'YES'
            })

        conn.close()

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "database": database,
                "database_type": "azure_sql",
                "tables": schema,
                "table_count": len(schema)
            }, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            mimetype="application/json",
            status_code=500
        )
```

### Azure Function Configuration: `function.json`

```json
{
  "scriptFile": "__init__.py",
  "bindings": [
    {
      "authLevel": "function",
      "type": "httpTrigger",
      "direction": "in",
      "name": "req",
      "methods": [
        "post"
      ]
    },
    {
      "type": "http",
      "direction": "out",
      "name": "$return"
    }
  ]
}
```

### Function definitions for Azure agents

```python
def get_azure_sql_function_definitions(function_app_url: str) -> list:
    """
    Get function definitions for Azure SQL tools (cloud)
    These will be passed to Azure agents
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "execute_azure_sql",
                "description": "Execute SQL query on Azure SQL Database (cloud). Returns query results as JSON. Use this for SELECT queries on cloud databases.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SQL query to execute"
                        },
                        "database": {
                            "type": "string",
                            "description": "Database name (optional, defaults to configured database)",
                            "default": "default"
                        },
                        "parameters": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional query parameters",
                            "default": []
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_azure_sql_schema",
                "description": "Get complete Azure SQL database schema. Use this FIRST before writing queries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "database": {
                            "type": "string",
                            "description": "Database name",
                            "default": "default"
                        }
                    },
                    "required": []
                }
            }
        }
    ]
```

---

## Part 3: Azure Function - RAG Tool (Azure AI Search)

### Implementation: `azure-functions/consult_rag/__init__.py`

```python
"""
Azure Function: RAG Tool using Azure AI Search
Executes semantic search on vector store
Uses Managed Identity for secure authentication
"""

import azure.functions as func
import json
import logging
import os
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.identity.aio import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential


async def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Search documents using Azure AI Search (vector + semantic search)

    Request Body:
        {
            "query": "What is the voltage range?",
            "index": "pi10-documents",  // optional, defaults to configured index
            "top_k": 5,                 // optional, number of results
            "search_type": "hybrid",    // "vector", "semantic", or "hybrid"
            "filters": ""               // optional, OData filter expression
        }

    Response:
        {
            "success": true,
            "documents": [
                {
                    "id": "doc1",
                    "title": "PI10 Specifications",
                    "content": "...",
                    "score": 0.95,
                    "reranker_score": 0.98,
                    "metadata": {...}
                }
            ],
            "result_count": 5
        }
    """
    logging.info('RAG Function triggered')

    try:
        # Parse request
        req_body = req.get_json()
        query = req_body.get('query')
        index_name = req_body.get('index', os.environ.get('AZURE_SEARCH_INDEX', 'documents'))
        top_k = req_body.get('top_k', 5)
        search_type = req_body.get('search_type', 'hybrid')
        filters = req_body.get('filters', '')

        if not query:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Query is required"}),
                mimetype="application/json",
                status_code=400
            )

        logging.info(f"Searching '{query}' in index '{index_name}' (top_k={top_k}, type={search_type})")

        # Get Azure AI Search endpoint
        search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
        if not search_endpoint:
            raise ValueError("AZURE_SEARCH_ENDPOINT environment variable not set")

        # Authenticate using Managed Identity (recommended) or API key (fallback)
        search_key = os.environ.get("AZURE_SEARCH_API_KEY")
        if search_key:
            credential = AzureKeyCredential(search_key)
        else:
            credential = DefaultAzureCredential()

        # Create search client
        async with SearchClient(
            endpoint=search_endpoint,
            index_name=index_name,
            credential=credential
        ) as search_client:

            # Perform search based on type
            if search_type == "vector":
                # Vector-only search (requires embedding generation)
                # Generate embedding for query
                query_vector = await generate_embedding(query)

                vector_query = VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=top_k,
                    fields="content_vector"  # Adjust based on your index schema
                )

                results = await search_client.search(
                    search_text=None,
                    vector_queries=[vector_query],
                    top=top_k,
                    filter=filters if filters else None
                )

            elif search_type == "semantic":
                # Semantic search only (requires semantic configuration)
                results = await search_client.search(
                    search_text=query,
                    top=top_k,
                    filter=filters if filters else None,
                    query_type="semantic",
                    semantic_configuration_name="default"  # Adjust based on your config
                )

            else:  # hybrid (default)
                # Hybrid search: Vector + Semantic + Keyword
                query_vector = await generate_embedding(query)

                vector_query = VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=50,  # Cast wider net for hybrid
                    fields="content_vector"
                )

                results = await search_client.search(
                    search_text=query,
                    vector_queries=[vector_query],
                    top=top_k,
                    filter=filters if filters else None,
                    query_type="semantic",
                    semantic_configuration_name="default"
                )

            # Process results
            documents = []
            async for result in results:
                doc = {
                    "id": result.get("id", ""),
                    "title": result.get("title", ""),
                    "content": result.get("content", "")[:1000],  # Truncate for response size
                    "score": result.get("@search.score", 0.0),
                    "reranker_score": result.get("@search.reranker_score"),
                    "metadata": {
                        "source": result.get("source", ""),
                        "created_at": result.get("created_at", ""),
                        "page_number": result.get("page_number"),
                        "chunk_id": result.get("chunk_id")
                    }
                }
                documents.append(doc)

            logging.info(f"Found {len(documents)} documents")

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "documents": documents,
                    "result_count": len(documents),
                    "query": query,
                    "index": index_name,
                    "search_type": search_type
                }, indent=2),
                mimetype="application/json",
                status_code=200
            )

    except Exception as e:
        logging.error(f"Error in RAG function: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            mimetype="application/json",
            status_code=500
        )


async def generate_embedding(text: str) -> list[float]:
    """
    Generate embedding for text using Azure OpenAI
    """
    from openai import AsyncAzureOpenAI

    client = AsyncAzureOpenAI(
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version="2024-02-01",
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
    )

    response = await client.embeddings.create(
        input=text,
        model=os.environ.get("AZURE_EMBED_DEPLOYMENT", "text-embedding-3-large")
    )

    return response.data[0].embedding
```

### Function definitions for Azure agents

```python
def get_rag_function_definitions(function_app_url: str) -> list:
    """
    Get function definitions for RAG tools (Azure AI Search)
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "consult_rag",
                "description": "Search documents using Azure AI Search with semantic and vector search. Use this to find relevant information from ingested documents. Returns top matching documents with scores.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query in natural language (e.g., 'What is the voltage range of PI10?')"
                        },
                        "index": {
                            "type": "string",
                            "description": "Index name (optional, defaults to configured index)",
                            "default": "documents"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results to return (1-50)",
                            "default": 5
                        },
                        "search_type": {
                            "type": "string",
                            "enum": ["vector", "semantic", "hybrid"],
                            "description": "Type of search (hybrid recommended)",
                            "default": "hybrid"
                        },
                        "filters": {
                            "type": "string",
                            "description": "Optional OData filter expression (e.g., \"source eq 'manual.pdf'\")",
                            "default": ""
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]
```

---

## Part 4: Tool Selection & Registration Logic

### File: `python/packages/core/agent_framework/tools/tool_selector.py`

```python
"""
Tool Selection Logic
Decides whether to use local or cloud tools based on data source configuration
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from ..schemas import DataSourceConfig


@dataclass
class ToolConfig:
    """Configuration for a selected tool"""
    name: str
    type: str  # "local" or "cloud"
    deployment: str  # "python_function" or "azure_function"
    url: Optional[str] = None  # For Azure Functions
    function_definitions: List[Dict] = None  # Tool definitions for agent
    instance: Optional[Any] = None  # For local tools


class ToolSelector:
    """
    Analyzes data sources and selects appropriate tools
    """

    def __init__(self, azure_functions_url: str):
        """
        Args:
            azure_functions_url: Base URL for Azure Functions (e.g., https://myapp.azurewebsites.net)
        """
        self.azure_functions_url = azure_functions_url

    def select_tools(self, data_sources: List[DataSourceConfig]) -> Dict[str, List[ToolConfig]]:
        """
        Analyze data sources and select appropriate tools

        Returns:
            {
                "local_tools": [ToolConfig, ...],
                "cloud_tools": [ToolConfig, ...]
            }
        """
        local_tools = []
        cloud_tools = []

        for ds in data_sources:
            if ds.type == "file":
                tool_configs = self._select_file_tools(ds)
            elif ds.type == "database":
                tool_configs = self._select_database_tools(ds)
            elif ds.type == "mcp_server":
                tool_configs = self._select_mcp_tools(ds)
            else:
                continue

            # Categorize tools
            for tool_config in tool_configs:
                if tool_config.type == "local":
                    local_tools.append(tool_config)
                else:
                    cloud_tools.append(tool_config)

        return {
            "local_tools": local_tools,
            "cloud_tools": cloud_tools
        }

    def _select_file_tools(self, ds: DataSourceConfig) -> List[ToolConfig]:
        """Select tools for file data sources"""
        tools = []

        if ds.path:
            ext = ds.path.lower().split('.')[-1]

            if ext in ['pdf', 'docx', 'md', 'txt']:
                # Document files → RAG (Azure AI Search)
                # NOTE: File must be ingested first
                tools.append(ToolConfig(
                    name="consult_rag",
                    type="cloud",
                    deployment="azure_function",
                    url=f"{self.azure_functions_url}/api/consult_rag",
                    function_definitions=get_rag_function_definitions(self.azure_functions_url)
                ))

            elif ext in ['db', 'duckdb']:
                # Database files → Local SQL tools
                from .local_sql_tools import LocalSQLTools, get_local_sql_function_definitions

                instance = LocalSQLTools(ds.path)
                tools.append(ToolConfig(
                    name="local_sql",
                    type="local",
                    deployment="python_function",
                    function_definitions=get_local_sql_function_definitions(ds.path),
                    instance=instance
                ))

        return tools

    def _select_database_tools(self, ds: DataSourceConfig) -> List[ToolConfig]:
        """Select tools for database data sources"""
        tools = []

        if ds.connection_string:
            conn_str = ds.connection_string.lower()

            if 'azure' in conn_str or 'sqlserver' in conn_str or 'database.windows.net' in conn_str:
                # Azure SQL → Cloud tool
                tools.append(ToolConfig(
                    name="execute_azure_sql",
                    type="cloud",
                    deployment="azure_function",
                    url=f"{self.azure_functions_url}/api/execute_azure_sql",
                    function_definitions=get_azure_sql_function_definitions(self.azure_functions_url)
                ))
            else:
                # Other databases → Local tool (could be remote but accessed via local connection)
                from .local_sql_tools import LocalSQLTools, get_local_sql_function_definitions

                instance = LocalSQLTools(ds.connection_string)
                tools.append(ToolConfig(
                    name="local_sql",
                    type="local",
                    deployment="python_function",
                    function_definitions=get_local_sql_function_definitions(ds.connection_string),
                    instance=instance
                ))

        return tools

    def _select_mcp_tools(self, ds: DataSourceConfig) -> List[ToolConfig]:
        """Select tools for MCP server data sources"""
        tools = []

        if ds.url:
            # MCP server with URL → Cloud tool
            tools.append(ToolConfig(
                name="call_mcp_server",
                type="cloud",
                deployment="azure_function",
                url=f"{self.azure_functions_url}/api/call_mcp_server",
                function_definitions=[{
                    "type": "function",
                    "function": {
                        "name": "call_mcp_server",
                        "description": f"Call MCP server at {ds.url}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "description": "Action to perform"},
                                "params": {"type": "object", "description": "Action parameters"}
                            },
                            "required": ["action"]
                        }
                    }
                }]
            ))

        return tools
```

---

## Part 5: Integration with Azure Orchestrator

### File: `python/packages/core/agent_framework/orchestrator/dynamic_orchestrator.py`

```python
"""
Dynamic Orchestrator with Tool Selection
Integrates local and cloud tools with Azure Foundry agents
"""

from azure.ai.agents.aio import AgentsClient
from azure.ai.agents.models import AsyncFunctionTool
from azure.identity.aio import DefaultAzureCredential
from typing import Dict, List, Any
import os
import json
import httpx

from ..tools.tool_selector import ToolSelector, ToolConfig
from ..schemas import WorkflowConfig, DataSourceConfig, JobStatus


class DynamicOrchestrator:
    """
    Orchestrator that dynamically selects and registers tools
    based on data source configuration
    """

    def __init__(self, azure_project_endpoint: str, azure_functions_url: str, registry):
        self.azure_project_endpoint = azure_project_endpoint
        self.azure_functions_url = azure_functions_url
        self.registry = registry

        # Initialize Azure Agents client
        self.agents_client = AgentsClient(
            endpoint=azure_project_endpoint,
            credential=DefaultAzureCredential()
        )

        # Initialize tool selector
        self.tool_selector = ToolSelector(azure_functions_url)

        # Cache for local tool instances
        self.local_tools_cache = {}

    async def start_workflow(
        self,
        workflow_id: str,
        input_data: Dict[str, Any],
        hil_mode: bool = True
    ) -> JobStatus:
        """
        Start workflow with dynamic tool selection
        """
        workflow_config = self.registry.get_workflow(workflow_id)
        if not workflow_config:
            raise ValueError(f"Workflow {workflow_id} not found")

        # Select tools based on data sources
        tool_selection = self.tool_selector.select_tools(workflow_config.data_sources)

        # Register local tools
        if tool_selection["local_tools"]:
            await self._register_local_tools(tool_selection["local_tools"])

        # Create job status
        job = JobStatus(
            workflow_id=workflow_id,
            status="running",
            context=input_data,
            logs=[
                "Workflow started",
                f"Selected {len(tool_selection['local_tools'])} local tools",
                f"Selected {len(tool_selection['cloud_tools'])} cloud tools"
            ],
            hil_mode=hil_mode
        )
        self.registry.save_job(job)

        # Store tool selection in job context for later use
        job.context["_tool_selection"] = {
            "local": [t.name for t in tool_selection["local_tools"]],
            "cloud": [t.name for t in tool_selection["cloud_tools"]]
        }

        # Execute workflow
        await self._execute_job(job, workflow_config, tool_selection)

        return job

    async def _register_local_tools(self, local_tools: List[ToolConfig]):
        """
        Register local tools with Azure Agents SDK
        Uses enable_auto_function_calls
        """
        tool_functions = set()

        for tool_config in local_tools:
            instance = tool_config.instance
            if not instance:
                continue

            # Add all methods from the instance
            # For LocalSQLTools: query_database, get_database_schema, list_tables, describe_table
            for method_name in dir(instance):
                if not method_name.startswith('_'):
                    method = getattr(instance, method_name)
                    if callable(method):
                        tool_functions.add(method)

            # Cache the instance
            self.local_tools_cache[tool_config.name] = instance

        if tool_functions:
            function_tool = AsyncFunctionTool(tool_functions)
            await self.agents_client.enable_auto_function_calls(
                function_tool,
                max_retry=10
            )

    async def _execute_job(
        self,
        job: JobStatus,
        config: WorkflowConfig,
        tool_selection: Dict[str, List[ToolConfig]]
    ):
        """
        Execute workflow steps
        """
        try:
            # Get agent IDs from config (assuming agents already created)
            from ..azure_agents_config import load_agent_config
            agent_config = load_agent_config()

            while job.current_step_index < len(config.steps):
                step = config.steps[job.current_step_index]

                if step.type == "agent_call":
                    # Get Azure agent ID
                    agent_id = agent_config["agents"].get(step.agent_id, {}).get("id")
                    if not agent_id:
                        raise ValueError(f"Agent {step.agent_id} not found in configuration")

                    # Format prompt
                    prompt = step.input_template.format(**job.context)

                    job.logs.append(f"Executing step '{step.name}' with agent {agent_id}")

                    # Run agent (tools are already registered)
                    result = await self.agents_client.create_thread_and_process_run(
                        agent_id=agent_id,
                        thread={"messages": [{"role": "user", "content": prompt}]}
                    )

                    # Parse response
                    step_output = self._parse_response(result)

                    # Store results
                    job.context[step.output_key] = step_output.content
                    if "step_outputs" not in job.context:
                        job.context["step_outputs"] = {}
                    job.context["step_outputs"][step.name] = step_output.model_dump()

                    job.logs.append(f"Step '{step.name}' completed")

                elif step.type == "user_confirmation":
                    job.status = "waiting_for_user"
                    job.logs.append(f"Waiting for user confirmation: {step.message}")
                    self.registry.save_job(job)
                    return

                # HIL check
                if job.hil_mode:
                    job.status = "waiting_for_user"
                    job.logs.append(f"Step '{step.name}' completed. Pausing for review.")
                    self.registry.save_job(job)
                    return

                # Move to next step
                job.current_step_index += 1
                self.registry.save_job(job)

            # Workflow complete
            job.status = "completed"
            job.logs.append("Workflow completed successfully")
            self.registry.save_job(job)

        except Exception as e:
            job.status = "failed"
            job.logs.append(f"Execution failed: {str(e)}")
            self.registry.save_job(job)
            raise

    def _parse_response(self, result) -> Any:
        """Parse Azure agent response"""
        from ..schemas import StepOutput

        if result.messages:
            last_message = result.messages[-1]
            content = last_message.content

            # Try to parse as StepOutput JSON
            try:
                data = json.loads(content)
                return StepOutput(**data)
            except:
                return StepOutput(
                    thought_process="Agent response",
                    content=content,
                    metrics={},
                    insights=[],
                    visualizations=[]
                )

        return StepOutput(
            thought_process="Empty response",
            content="No output",
            metrics={},
            insights=[],
            visualizations=[]
        )
```

---

## Part 6: Azure Function Requirements & Deployment

### `azure-functions/requirements.txt`

```txt
azure-functions
azure-identity==1.15.0
azure-keyvault-secrets==4.7.0
azure-search-documents==11.4.0
pyodbc==5.0.1
openai==1.12.0
```

### `azure-functions/host.json`

```json
{
  "version": "2.0",
  "logging": {
    "applicationInsights": {
      "samplingSettings": {
        "isEnabled": true,
        "maxTelemetryItemsPerSecond": 20
      }
    }
  },
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  },
  "functionTimeout": "00:05:00"
}
```

### Deployment Script: `deploy_azure_functions.sh`

```bash
#!/bin/bash

# Azure Functions Deployment Script

RESOURCE_GROUP="agent-framework-rg"
FUNCTION_APP_NAME="agent-tools-functions"
STORAGE_ACCOUNT="agenttoolsstorage$(date +%s)"
LOCATION="eastus"
KEY_VAULT_NAME="agent-tools-kv"

echo "=========================================="
echo "Deploying Azure Functions for Agent Tools"
echo "=========================================="

# Create resource group
echo "Creating resource group..."
az group create --name $RESOURCE_GROUP --location $LOCATION

# Create storage account
echo "Creating storage account..."
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS

# Create Key Vault
echo "Creating Key Vault..."
az keyvault create \
  --name $KEY_VAULT_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

# Create function app (Python 3.11)
echo "Creating Function App..."
az functionapp create \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --storage-account $STORAGE_ACCOUNT \
  --consumption-plan-location $LOCATION \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --os-type Linux

# Enable managed identity
echo "Enabling Managed Identity..."
FUNCTION_IDENTITY=$(az functionapp identity assign \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

echo "Function App Managed Identity: $FUNCTION_IDENTITY"

# Grant Key Vault access to Function App
echo "Granting Key Vault access..."
az keyvault set-policy \
  --name $KEY_VAULT_NAME \
  --object-id $FUNCTION_IDENTITY \
  --secret-permissions get list

# Set environment variables
echo "Configuring Function App settings..."
az functionapp config appsettings set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    KEY_VAULT_URL="https://$KEY_VAULT_NAME.vault.azure.net/" \
    AZURE_SEARCH_ENDPOINT="<YOUR_SEARCH_ENDPOINT>" \
    AZURE_SEARCH_INDEX="documents" \
    AZURE_OPENAI_ENDPOINT="<YOUR_OPENAI_ENDPOINT>" \
    AZURE_OPENAI_API_KEY="<YOUR_OPENAI_KEY>" \
    AZURE_EMBED_DEPLOYMENT="text-embedding-3-large"

# Deploy functions
echo "Deploying functions..."
cd azure-functions
func azure functionapp publish $FUNCTION_APP_NAME

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo "Function App URL: https://$FUNCTION_APP_NAME.azurewebsites.net"
echo "Key Vault: https://$KEY_VAULT_NAME.vault.azure.net/"
echo ""
echo "Next steps:"
echo "1. Add your Azure SQL connection strings to Key Vault:"
echo "   az keyvault secret set --vault-name $KEY_VAULT_NAME --name 'default-connection-string' --value '<YOUR_CONNECTION_STRING>'"
echo ""
echo "2. Grant Function App Managed Identity access to Azure AI Search:"
echo "   az search service update --name <YOUR_SEARCH_SERVICE> --resource-group <RG> --identity-type SystemAssigned"
echo "   az role assignment create --assignee $FUNCTION_IDENTITY --role 'Search Index Data Reader' --scope <SEARCH_RESOURCE_ID>"
```

---

## Part 7: Usage Example

### Complete workflow example

```python
"""
Example: Using SQL and RAG tools with Azure Foundry agents
"""

import asyncio
from agent_framework.orchestrator.dynamic_orchestrator import DynamicOrchestrator
from agent_framework.registry import WorkflowRegistry
from agent_framework.schemas import WorkflowConfig, AgentConfig, DataSourceConfig, StepConfig

async def main():
    # Initialize orchestrator
    orchestrator = DynamicOrchestrator(
        azure_project_endpoint="https://pi12-resource.services.ai.azure.com/api/projects/pi12",
        azure_functions_url="https://agent-tools-functions.azurewebsites.net",
        registry=WorkflowRegistry()
    )

    # Create workflow config
    workflow = WorkflowConfig(
        name="PI10 Analysis Workflow",
        description="Analyze PI10 system using local DB and cloud documents",
        user_intent="Analyze PI10 specifications and operational data",
        data_sources=[
            DataSourceConfig(
                id="ds-1",
                name="PI10 Documentation",
                type="file",
                path="./documents/eDrivePredM.pdf"
            ),
            DataSourceConfig(
                id="ds-2",
                name="Operational Database",
                type="file",
                path="./data/operations.db"  # Local SQLite
            )
        ],
        agents=[
            AgentConfig(
                id="agent-rag",
                name="RAG Agent",
                role="Document Analyst",
                instructions="You are an expert at finding information in technical documents. Use consult_rag to search documents.",
                model_provider="azure_openai",
                model_name="gpt-4o",
                data_sources=["ds-1"]
            ),
            AgentConfig(
                id="agent-sql",
                name="SQL Agent",
                role="Data Analyst",
                instructions="You are a database expert. Use query_database to analyze operational data. Always call get_database_schema first.",
                model_provider="azure_openai",
                model_name="gpt-4o",
                data_sources=["ds-2"]
            )
        ],
        steps=[
            StepConfig(
                name="Get PI10 Specifications",
                type="agent_call",
                agent_id="agent-rag",
                input_template="What is the voltage range and torque output of the PI10 system?",
                output_key="specifications"
            ),
            StepConfig(
                name="Query Operational Data",
                type="agent_call",
                agent_id="agent-sql",
                input_template="Get the last 10 operational records from the database.",
                output_key="operational_data"
            )
        ]
    )

    # Save workflow
    orchestrator.registry.save_workflow(workflow)

    # Execute workflow
    job = await orchestrator.start_workflow(
        workflow_id=workflow.id,
        input_data={"user_query": "Analyze PI10 system"},
        hil_mode=True
    )

    print(f"Job started: {job.id}")
    print(f"Status: {job.status}")
    print(f"Logs: {job.logs}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Summary

This implementation provides:

1. **Local SQL Tools** (`LocalSQLTools`) for .db/.duckdb files - runs on backend server
2. **Azure Function** for Azure SQL - serverless, uses Managed Identity + Key Vault
3. **Azure Function** for RAG - Azure AI Search with vector + semantic search
4. **Tool Selector** - automatically chooses local vs cloud based on data source
5. **Dynamic Orchestrator** - registers local tools, calls cloud tools, manages workflow
6. **Complete deployment scripts** - Azure Functions, Key Vault, permissions

**Key Features:**
- Hybrid architecture (local + cloud tools)
- Secure (Managed Identity, Key Vault)
- Scalable (Azure Functions)
- Flexible (adapts to data source location)
- HIL support (pause/resume with user feedback)

**Next Steps:**
1. Deploy Azure Functions
2. Test with existing Azure Foundry agents
3. Add file ingestion pipeline for PDFs → Azure AI Search
4. Integrate with frontend

Ready to implement!
