#!/usr/bin/env python3
"""
SQLite to Azure SQL Migration via Azure Functions

Migrates SQLite database to Azure SQL by routing SQL through
the deployed execute_azure_sql Azure Function.

This approach bypasses local authentication issues by using
the Azure Function's Managed Identity to access the database.

Usage:
    python scripts/migrate_via_functions.py \
        --source tdn_op.db \
        --database tdn-op-db \
        --verbose
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# SQLite to SQL Server type mapping
SQLITE_TO_MSSQL_TYPES = {
    'INTEGER': 'INT',
    'INT': 'INT',
    'BIGINT': 'BIGINT',
    'TEXT': 'NVARCHAR(MAX)',
    'VARCHAR': 'NVARCHAR(255)',
    'REAL': 'FLOAT',
    'FLOAT': 'FLOAT',
    'BLOB': 'VARBINARY(MAX)',
    'BOOLEAN': 'BIT',
    'DATE': 'DATE',
    'DATETIME': 'DATETIME2',
    'TIMESTAMP': 'DATETIME2',
}


@dataclass
class TableInfo:
    name: str
    columns: List[Dict]
    primary_keys: List[str]
    row_count: int = 0


class AzureFunctionSQLClient:
    """Execute SQL via Azure Functions HTTP API."""
    
    def __init__(self, functions_url: str, functions_key: str, database: str):
        self.base_url = functions_url.rstrip('/')
        self.api_key = functions_key
        self.database = database
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'x-functions-key': self.api_key
        })
    
    def execute(self, query: str) -> Dict[str, Any]:
        """Execute SQL query via Azure Function."""
        url = f"{self.base_url}/api/execute_azure_sql"
        
        payload = {
            "query": query,
            "database": self.database
        }
        
        try:
            response = self.session.post(url, json=payload, timeout=300)
            result = response.json()
            
            if response.status_code != 200:
                logger.error(f"Azure Function error: {result}")
                return {"success": False, "error": result.get("error", "Unknown error")}
            
            return result
            
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def test_connection(self) -> bool:
        """Test connection to Azure SQL via function."""
        result = self.execute("SELECT 1 as test")
        if result.get("success"):
            logger.info("✓ Azure Function connection successful")
            return True
        else:
            logger.error(f"✗ Connection failed: {result.get('error')}")
            return False


def get_sqlite_tables(conn: sqlite3.Connection) -> List[str]:
    """Get list of tables from SQLite."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return [row[0] for row in cursor.fetchall()]


def get_table_info(conn: sqlite3.Connection, table_name: str) -> TableInfo:
    """Get table schema information."""
    cursor = conn.execute(f"PRAGMA table_info('{table_name}')")
    columns = []
    primary_keys = []
    
    for row in cursor.fetchall():
        cid, name, col_type, not_null, default_val, is_pk = row
        
        sqlite_type = col_type.upper() if col_type else 'TEXT'
        base_type = re.split(r'[\(\)]', sqlite_type)[0].strip()
        mssql_type = SQLITE_TO_MSSQL_TYPES.get(base_type, 'NVARCHAR(MAX)')
        
        if 'VARCHAR' in sqlite_type and '(' in sqlite_type:
            length = re.search(r'\((\d+)\)', sqlite_type)
            if length:
                mssql_type = f"NVARCHAR({length.group(1)})"
        
        columns.append({
            'name': name,
            'mssql_type': mssql_type,
            'nullable': not_null == 0,
            'is_pk': is_pk > 0,
            'default': default_val
        })
        
        if is_pk > 0:
            primary_keys.append(name)
    
    cursor = conn.execute(f"SELECT COUNT(*) FROM '{table_name}'")
    row_count = cursor.fetchone()[0]
    
    return TableInfo(table_name, columns, primary_keys, row_count)


def generate_create_table_sql(table_info: TableInfo) -> str:
    """Generate T-SQL CREATE TABLE."""
    columns_sql = []
    
    for col in table_info.columns:
        col_def = f"[{col['name']}] {col['mssql_type']}"
        if not col['nullable']:
            col_def += " NOT NULL"
        columns_sql.append(col_def)
    
    if table_info.primary_keys:
        pk_cols = ', '.join([f"[{pk}]" for pk in table_info.primary_keys])
        columns_sql.append(f"PRIMARY KEY ({pk_cols})")
    
    return f"""
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = '{table_info.name}')
CREATE TABLE [{table_info.name}] (
    {', '.join(columns_sql)}
)
""".strip()


def escape_value(value: Any) -> str:
    """Escape value for SQL."""
    if value is None:
        return 'NULL'
    elif isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"N'{escaped}'"
    elif isinstance(value, (int, float)):
        return str(value)
    else:
        escaped = str(value).replace("'", "''")
        return f"N'{escaped}'"


def generate_insert_sql(table_name: str, columns: List[str], rows: List[Tuple], batch_size: int = 50) -> List[str]:
    """Generate batch INSERT statements."""
    statements = []
    col_names = ', '.join([f"[{c}]" for c in columns])
    
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        values_list = []
        
        for row in batch:
            values = ', '.join([escape_value(v) for v in row])
            values_list.append(f"({values})")
        
        sql = f"INSERT INTO [{table_name}] ({col_names}) VALUES {', '.join(values_list)}"
        statements.append(sql)
    
    return statements


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    sql_client: AzureFunctionSQLClient,
    table_info: TableInfo,
    truncate: bool = False
) -> Tuple[bool, int]:
    """Migrate a single table."""
    logger.info(f"\nMigrating: {table_info.name} ({table_info.row_count} rows)")
    
    # Create table
    create_sql = generate_create_table_sql(table_info)
    logger.debug(f"CREATE TABLE SQL:\n{create_sql}")
    
    result = sql_client.execute(create_sql)
    if not result.get("success"):
        logger.error(f"  ✗ Failed to create table: {result.get('error')}")
        return False, 0
    
    logger.info(f"  ✓ Table created/verified")
    
    # Truncate if requested
    if truncate:
        result = sql_client.execute(f"DELETE FROM [{table_info.name}]")
        if result.get("success"):
            logger.info(f"  ✓ Table truncated")
    
    if table_info.row_count == 0:
        logger.info(f"  ⊘ No data to migrate")
        return True, 0
    
    # Get data
    cursor = sqlite_conn.execute(f"SELECT * FROM '{table_info.name}'")
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    
    # Generate and execute INSERT statements
    insert_statements = generate_insert_sql(table_info.name, columns, rows, batch_size=50)
    
    total_inserted = 0
    for i, sql in enumerate(insert_statements):
        result = sql_client.execute(sql)
        if result.get("success"):
            batch_size = min(50, len(rows) - i * 50)
            total_inserted += batch_size
            if (i + 1) % 10 == 0:
                logger.info(f"    ... {total_inserted}/{len(rows)} rows")
        else:
            logger.warning(f"  ⚠ Batch {i+1} failed: {result.get('error')}")
    
    logger.info(f"  ✓ Migrated {total_inserted}/{len(rows)} rows")
    return True, total_inserted


def run_migration(
    source_db: str,
    database: str,
    functions_url: str,
    functions_key: str,
    truncate: bool = False,
    tables: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Run the full migration."""
    results = {
        'success': False,
        'tables_migrated': 0,
        'total_rows': 0,
        'details': []
    }
    
    # Validate source
    if not Path(source_db).exists():
        logger.error(f"Source not found: {source_db}")
        return results
    
    logger.info("=" * 60)
    logger.info("SQLite to Azure SQL Migration (via Azure Functions)")
    logger.info("=" * 60)
    logger.info(f"Source: {source_db}")
    logger.info(f"Target: {database}")
    logger.info("=" * 60)
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(source_db)
    logger.info("✓ Connected to SQLite")
    
    # Create Azure Function client
    sql_client = AzureFunctionSQLClient(functions_url, functions_key, database)
    
    # Test connection
    if not sql_client.test_connection():
        logger.error("Cannot connect to Azure SQL via Functions")
        return results
    
    # Get tables
    all_tables = get_sqlite_tables(sqlite_conn)
    target_tables = tables if tables else all_tables
    
    logger.info(f"\nTables to migrate: {len(target_tables)}")
    for t in target_tables:
        info = get_table_info(sqlite_conn, t)
        logger.info(f"  - {t}: {info.row_count} rows")
    
    # Migrate
    success_count = 0
    total_rows = 0
    
    for table_name in target_tables:
        table_info = get_table_info(sqlite_conn, table_name)
        success, rows = migrate_table(sqlite_conn, sql_client, table_info, truncate)
        
        if success:
            success_count += 1
            total_rows += rows
        
        results['details'].append({
            'table': table_name,
            'success': success,
            'rows': rows
        })
    
    sqlite_conn.close()
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("MIGRATION SUMMARY")
    logger.info("=" * 60)
    
    for d in results['details']:
        status = "✓" if d['success'] else "✗"
        logger.info(f"  {status} {d['table']}: {d['rows']} rows")
    
    logger.info(f"\nTotal: {success_count}/{len(target_tables)} tables, {total_rows} rows")
    
    results['success'] = success_count == len(target_tables)
    results['tables_migrated'] = success_count
    results['total_rows'] = total_rows
    
    if results['success']:
        logger.info("\n✓ MIGRATION COMPLETED SUCCESSFULLY")
    else:
        logger.warning("\n⚠ MIGRATION COMPLETED WITH ERRORS")
    
    return results


def main():
    parser = argparse.ArgumentParser(description='Migrate SQLite to Azure SQL via Azure Functions')
    
    parser.add_argument('--source', '-s', required=True, help='SQLite database file')
    parser.add_argument('--database', '-d', required=True, help='Target Azure SQL database name')
    parser.add_argument('--functions-url', help='Azure Functions URL (or set AZURE_FUNCTIONS_URL)')
    parser.add_argument('--functions-key', help='Azure Functions key (or set AZURE_FUNCTIONS_KEY)')
    parser.add_argument('--tables', nargs='+', help='Specific tables to migrate')
    parser.add_argument('--truncate', action='store_true', help='Truncate tables before insert')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Get credentials
    functions_url = args.functions_url or os.environ.get('AZURE_FUNCTIONS_URL')
    functions_key = args.functions_key or os.environ.get('AZURE_FUNCTIONS_KEY')
    
    if not functions_url or not functions_key:
        logger.error("Azure Functions URL and key required")
        logger.error("Set AZURE_FUNCTIONS_URL and AZURE_FUNCTIONS_KEY environment variables")
        sys.exit(1)
    
    results = run_migration(
        source_db=args.source,
        database=args.database,
        functions_url=functions_url,
        functions_key=functions_key,
        truncate=args.truncate,
        tables=args.tables
    )
    
    sys.exit(0 if results['success'] else 1)


if __name__ == '__main__':
    main()
