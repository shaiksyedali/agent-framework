"""
Local SQL Tools for .db and .duckdb files.

Runs on the backend server (not in Azure Functions).
Provides SQL query capabilities for local database files.
"""

import sqlite3
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class LocalSQLTools:
    """
    SQL tools for local database files (.db, .duckdb)
    Used when data is on local filesystem or not accessible from cloud
    """

    def __init__(self, db_path: str):
        """
        Initialize local SQL tools.

        Args:
            db_path: Path to database file (sqlite:///path/to/file.db or duckdb:///path/to/file.duckdb)
        """
        self.db_path = db_path
        self.db_type = self._detect_db_type(db_path)
        logger.info(f"Initialized LocalSQLTools for {self.db_type} database: {db_path}")

    def _detect_db_type(self, db_path: str) -> str:
        """Detect database type from path."""
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

    @property
    def dialect(self) -> str:
        """Return the SQL dialect for this database (sqlite or duckdb)."""
        return self.db_type

    def _get_file_path(self) -> str:
        """Extract file path from connection string."""
        if "://" in self.db_path:
            return self.db_path.split("://")[1]
        return self.db_path

    async def execute_sql_query(
        self,
        query: str,
        database: str,
        require_approval: bool = False
    ) -> str:
        """
        Execute SQL query on local database.

        Note: The 'database' parameter is included for consistency with Azure Agents API
        but is ignored for local file databases (the database is the file itself).

        Args:
            query: SQL query to execute
            database: Database identifier (used for naming/logging only for local files)
            require_approval: Whether approval is required (handled by orchestrator)

        Returns:
            JSON string with query results

        Example:
            result = await tools.execute_sql_query(
                "SELECT * FROM users WHERE age > 18",
                database="sales"
            )
        """
        file_path = self._get_file_path()
        logger.info(f"Executing query on {file_path}: {query[:100]}...")

        try:
            if self.db_type == "duckdb":
                # Import duckdb only if needed
                try:
                    import duckdb
                except ImportError:
                    return json.dumps({
                        "success": False,
                        "error": "DuckDB not installed. Install with: pip install duckdb",
                        "error_type": "ImportError"
                    })

                conn = duckdb.connect(file_path, read_only=True)
                result = conn.execute(query).fetchall()
                columns = [desc[0] for desc in conn.description] if conn.description else []
                conn.close()
            else:  # sqlite
                conn = sqlite3.connect(file_path)
                cursor = conn.cursor()
                cursor.execute(query)
                result = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                conn.close()

            # Convert to list of dicts
            rows = [dict(zip(columns, row)) for row in result]

            logger.info(f"Query executed successfully. Returned {len(rows)} rows.")

            return json.dumps({
                "success": True,
                "rows": rows,
                "row_count": len(rows),
                "columns": columns
            }, default=str)

        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            })

    async def get_database_schema(self, database: str) -> str:
        """
        Get database schema (tables and columns).

        Note: The 'database' parameter is included for consistency with Azure Agents API
        but is ignored for local file databases.

        Args:
            database: Database identifier (used for naming/logging only for local files)

        Returns:
            JSON string with schema information

        Example:
            schema = await tools.get_database_schema(database="sales")
        """
        file_path = self._get_file_path()
        logger.info(f"Retrieving schema for {file_path}")

        try:
            if self.db_type == "duckdb":
                try:
                    import duckdb
                except ImportError:
                    return json.dumps({
                        "success": False,
                        "error": "DuckDB not installed",
                        "error_type": "ImportError"
                    })

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

            logger.info(f"Retrieved schema with {len(schema)} tables")

            return json.dumps({
                "success": True,
                "database": file_path,
                "database_type": self.db_type,
                "tables": schema,
                "table_count": len(schema)
            }, indent=2)

        except Exception as e:
            logger.error(f"Schema retrieval failed: {str(e)}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            })

    async def list_tables(self) -> str:
        """
        List all tables in database.

        Returns:
            JSON string with table names
        """
        file_path = self._get_file_path()
        logger.info(f"Listing tables in {file_path}")

        try:
            if self.db_type == "duckdb":
                try:
                    import duckdb
                except ImportError:
                    return json.dumps({
                        "success": False,
                        "error": "DuckDB not installed",
                        "error_type": "ImportError"
                    })

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

            logger.info(f"Found {len(table_names)} tables")

            return json.dumps({
                "success": True,
                "tables": table_names,
                "table_count": len(table_names)
            })

        except Exception as e:
            logger.error(f"List tables failed: {str(e)}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            })

    async def describe_table(self, table_name: str) -> str:
        """
        Get detailed information about a specific table.

        Args:
            table_name: Name of the table

        Returns:
            JSON string with table structure and sample data
        """
        file_path = self._get_file_path()
        logger.info(f"Describing table '{table_name}' in {file_path}")

        try:
            if self.db_type == "duckdb":
                try:
                    import duckdb
                except ImportError:
                    return json.dumps({
                        "success": False,
                        "error": "DuckDB not installed",
                        "error_type": "ImportError"
                    })

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

            logger.info(f"Table '{table_name}' has {len(columns)} columns and {row_count} rows")

            return json.dumps({
                "success": True,
                "table_name": table_name,
                "columns": [{"name": col[0], "type": col[1]} for col in columns],
                "row_count": row_count,
                "sample_data": sample_data
            }, indent=2, default=str)

        except Exception as e:
            logger.error(f"Describe table failed: {str(e)}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            })


def get_local_sql_function_definitions(db_path: str) -> list:
    """
    Get function definitions for local SQL tools.
    These will be passed to Azure agents as available tools.

    Args:
        db_path: Path to the database file

    Returns:
        List of function definitions in Azure Agents format
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "execute_sql_query",
                "description": f"Execute SQL query on local database: {db_path}. Returns query results as JSON. Use this for SELECT queries to retrieve data. Always call get_database_schema FIRST to understand the database structure before writing queries. For INSERT/UPDATE/DELETE operations, set require_approval=true.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SQL query to execute (e.g., 'SELECT * FROM users WHERE age > 18')"
                        },
                        "database": {
                            "type": "string",
                            "description": f"Database name (for local files, use: '{db_path}')"
                        },
                        "require_approval": {
                            "type": "boolean",
                            "description": "Whether user approval is required before executing (set to true for INSERT/UPDATE/DELETE)",
                            "default": False
                        }
                    },
                    "required": ["query", "database"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_database_schema",
                "description": "Get complete database schema including all tables and their columns. **CRITICAL**: You MUST call this function FIRST before attempting any SQL queries to understand what tables and columns exist in the database.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "database": {
                            "type": "string",
                            "description": f"Database name (for local files, use: '{db_path}')"
                        }
                    },
                    "required": ["database"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_tables",
                "description": "List all tables in the database. Quick way to see available tables without full schema details.",
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
                "description": "Get detailed information about a specific table including columns, data types, row count, and sample data (first 5 rows). Use this to understand a table's structure and content before querying it.",
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
