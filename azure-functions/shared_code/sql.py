
import logging
import os
import json
import sqlite3
from pathlib import Path

try:
    import pyodbc
except ImportError:
    pyodbc = None

async def execute_sql_query_tool(query: str, database: str, require_approval: bool = True) -> dict:
    """
    Shared SQL execution logic.
    Supports 'local' (SQLite) and 'azure' (SQL Server).
    """
    logging.info(f"Executing SQL: {query} on {database}")
    
    # Safety Check
    if "DROP" in query.upper() or "DELETE" in query.upper():
        if require_approval:
             return {"success": False, "error": "Destructive actions (DROP/DELETE) require explicit approval."}

    try:
        results = []
        message = ""
        
        # 1. Local SQLite
        if "local" in database.lower() or "sqlite" in database.lower() or not database:
            # Look for local_data.db in parent of parent (root of functions?) or precise location
            # Assuming shared_code is inside azure-functions, and db is in project root...
            # But functions run in their own sandbox. 
            # We'll assume a local.db exists near the script for dev.
            db_path = Path(__file__).parent.parent / "local_data.db"
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(query)
            
            if query.strip().upper().startswith("SELECT"):
                columns = [description[0] for description in cursor.description]
                rows = cursor.fetchall()
                results = [dict(zip(columns, row)) for row in rows][:100] # Limit 100
                message = f"Retrieved {len(results)} rows."
            else:
                conn.commit()
                message = "Query executed successfully."
            conn.close()

        # 2. Azure SQL (Cloud)
        elif "azure" in database.lower() or "cloud" in database.lower() or "server" in database.lower():
            if not pyodbc:
                return {"success": False, "error": "pyodbc module not installed."}
            
            server = os.environ.get("AZURE_SQL_SERVER")
            db_name = os.environ.get("AZURE_SQL_DATABASE")
            user = os.environ.get("AZURE_SQL_USERNAME")
            pwd = os.environ.get("AZURE_SQL_PASSWORD")
            driver = "{ODBC Driver 18 for SQL Server}"
            
            if not server or not db_name:
                 return {"success": False, "error": "AZURE_SQL_SERVER/DATABASE env vars missing."}
            
            conn_str = f"DRIVER={driver};SERVER={server};DATABASE={db_name}"
            if user and pwd:
                conn_str += f";UID={user};PWD={pwd}"
            else:
                conn_str += ";Authentication=ActiveDirectoryMsi"
                
            with pyodbc.connect(conn_str) as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                if query.strip().upper().startswith("SELECT"):
                    columns = [column[0] for column in cursor.description]
                    rows = cursor.fetchall()
                    results = [dict(zip(columns, row)) for row in rows][:100]
                    message = f"Retrieved {len(results)} rows."
                else:
                    conn.commit()
                    message = "Query executed successfully."
        else:
            return {"success": False, "error": f"Unknown database type: {database}"}

        # Determine dialect for downstream SQL generation hints
        if "local" in database.lower() or "sqlite" in database.lower() or not database:
            dialect = "sqlite"
        elif "azure" in database.lower() or "server" in database.lower():
            dialect = "mssql"
        else:
            dialect = "unknown"

        return {
            "success": True, 
            "results": results, 
            "message": message,
            "count": len(results),
            "dialect": dialect
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

async def get_database_schema_tool(database: str) -> dict:
    """Gets schema info."""
    # Simplified schema query
    if "local" in database.lower():
        query = "SELECT type, name, sql FROM sqlite_master WHERE type='table'"
    else:
        query = "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS"
        
    return await execute_sql_query_tool(query, database, require_approval=False)
