# SQL Agent Use Cases: Local and Azure DBs

## Complete Flow

```
User Query
    │
    ▼
Azure SQL Agent (AI Foundry)
    │
    ├─ 1. get_database_schema(database)
    │      ├─ Local (.db, .duckdb) → azure_executor._execute_local_sql()
    │      └─ Azure SQL → Azure Function get_azure_sql_schema
    │
    ├─ 2. consult_rag(query, workflow_id)  ← Schema docs, business rules
    │      └─ Always → Azure Function consult_rag
    │
    └─ 3. execute_sql_query(query, database)
           ├─ Local → azure_executor._execute_local_sql()
           └─ Azure → Azure Function execute_azure_sql
```

## Use Cases

### 1. Local SQLite Database
- **Database:** `data/ops.db`
- **Dialect:** sqlite
- **Schema:** From `sqlite_master`
- **RAG:** Azure Function (same as Azure DBs)

### 2. Local DuckDB Database
- **Database:** `data/analytics.duckdb`
- **Dialect:** duckdb
- **Schema:** From `information_schema.columns`
- **RAG:** Azure Function (same as Azure DBs)

### 3. Azure SQL Server
- **Database:** `sales` (Key Vault secret: `sales-connection-string`)
- **Dialect:** mssql
- **Schema:** Azure Function get_azure_sql_schema
- **RAG:** Azure Function consult_rag

## Dialect in Responses

| Source | Response Field |
|--------|----------------|
| `azure_executor._execute_local_sql()` | `dialect: "sqlite"` or `"duckdb"` |
| Azure Function `execute_azure_sql` | `dialect: "mssql"` |
| Azure Function `get_azure_sql_schema` | `dialect: "mssql"` |

## SQL Agent Workflow

The Azure SQL Agent instructions now include:

1. **FIRST**: Call `get_database_schema` 
2. **SECOND**: Call `consult_rag` for documentation
3. **THEN**: Generate SQL using correct dialect syntax

This ensures schema docs (RAG) are used for both local and Azure DBs.
