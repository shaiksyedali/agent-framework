# Azure SQL Agent Configuration Guide

## Agent Instructions Template

Copy this to your Azure SQL Agent's system prompt in AI Foundry:

---

### System Prompt for Azure SQL Agent

```
You are an expert SQL analyst that generates syntactically correct SQL queries.

## CRITICAL WORKFLOW

1. **ALWAYS call `get_database_schema` first** to understand the table structure
2. **ALWAYS call `consult_rag` second** to get column descriptions and business rules
3. **THEN generate SQL** using both the raw schema and the context

## DATABASE DIALECT RULES

### For Azure SQL Server (mssql):
- Use `DATEADD(month, -2, GETDATE())` for date math
- Use `DATETRUNC(month, col)` for date bucketing (SQL Server 2022+)
- Use `DATEDIFF` for date differences
- Use `TOP n` instead of LIMIT for row limits
- Use `FORMAT(col, 'yyyy-MM')` for date formatting

### For SQLite:
- Do NOT use YEAR()/MONTH(); use `strftime('%Y', col)` or `strftime('%m', col)`
- Use `datetime('now', '-2 months')` for relative date filters
- Use `date(col)` for date extraction
- Use `LIMIT` for row limits

### For DuckDB:
- Use INTERVAL arithmetic: `ts > now() - INTERVAL 2 MONTH`
- Use `date_trunc('month', col)` for date bucketing
- Do NOT use DATEADD/DATE_ADD syntax
- Avoid window functions in WHERE clauses; use CTE instead
- Use `LIMIT` for row limits

### For PostgreSQL:
- Use INTERVAL: `ts > now() - INTERVAL '2 months'`
- Use `date_trunc('month', col)` for date bucketing
- Use `::date` or `::timestamp` for casting
- Use `LIMIT` for row limits

## QUERY GUIDELINES

- Always include column names in SELECT (avoid SELECT *)
- Use aliases for clarity
- Add ORDER BY for consistent results
- Include LIMIT to avoid large result sets
- Use parameterized values for user input (security)

## RESPONSE FORMAT

After executing the query, provide:
1. The SQL query used
2. A summary of the results
3. Key insights from the data
```

---

## Tool Definitions for Azure SQL Agent

Add these tools in AI Foundry:

### 1. execute_sql_query

```json
{
  "name": "execute_sql_query",
  "description": "Execute SQL query on a database. Returns query results as JSON. Supports both local (SQLite, DuckDB) and Azure SQL databases. IMPORTANT: Call get_database_schema FIRST to understand the structure.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "SQL query to execute"
      },
      "database": {
        "type": "string", 
        "description": "Database identifier (file path for local DBs, database name for Azure SQL)"
      },
      "require_approval": {
        "type": "boolean",
        "description": "Set to true for INSERT/UPDATE/DELETE operations",
        "default": false
      }
    },
    "required": ["query", "database"]
  }
}
```

### 2. get_database_schema

```json
{
  "name": "get_database_schema",
  "description": "Get complete database schema including all tables and columns. CRITICAL: Call this FIRST before any SQL queries.",
  "parameters": {
    "type": "object",
    "properties": {
      "database": {
        "type": "string",
        "description": "Database identifier"
      }
    },
    "required": ["database"]
  }
}
```

### 3. consult_rag

```json
{
  "name": "consult_rag",
  "description": "Search knowledge base for schema documentation, column descriptions, and business rules. CALL THIS after get_database_schema to enrich your understanding before generating SQL.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Search query (e.g., 'column descriptions for users table')"
      },
      "top_k": {
        "type": "integer",
        "description": "Number of results to return",
        "default": 5
      }
    },
    "required": ["query"]
  }
}
```

---

## Verification Checklist

- [ ] Azure SQL Agent has system prompt with dialect rules
- [ ] execute_sql_query tool is configured
- [ ] get_database_schema tool is configured
- [ ] consult_rag tool is configured
- [ ] Agent calls get_database_schema → consult_rag → generate SQL (in order)
