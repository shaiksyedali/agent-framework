#!/usr/bin/env python3
"""
SQLite to Azure SQL Migration Tool

Migrates any SQLite database to Azure SQL Server using Azure AD authentication.
Supports database creation, schema conversion, and data migration.

Features:
- Creates database on Azure SQL Server if it doesn't exist
- Converts SQLite schema to T-SQL compatible format
- Handles type conversions (INTEGER→INT, TEXT→NVARCHAR, etc.)
- Uses Azure AD authentication (no password required)
- Supports batch inserts for large datasets
- Verifies row counts after migration
- Configurable for any SQLite database
- Multiple backends: pyodbc or sqlcmd (fallback)

Prerequisites:
- Azure CLI installed and logged in (az login)
- One of:
  - pyodbc with ODBC Driver 18 for SQL Server, OR
  - sqlcmd (mssql-tools18) for fallback mode

Usage:
    python scripts/migrate_to_azure_sql.py \\
        --source tdn_op.db \\
        --server sql-divt-pi12-dev.database.windows.net \\
        --database tdn-op-db \\
        --resource-group rg-divt-pi12emob-dev-westeurope

Author: Azure-First Agent Framework
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import pyodbc
try:
    import pyodbc
    HAS_PYODBC = True
except ImportError:
    HAS_PYODBC = False

# Check for sqlcmd availability
def check_sqlcmd() -> bool:
    """Check if sqlcmd is available."""
    try:
        result = subprocess.run(['sqlcmd', '-?'], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False

HAS_SQLCMD = check_sqlcmd()

if not HAS_PYODBC and not HAS_SQLCMD:
    logger.warning("Neither pyodbc nor sqlcmd found. Install one of:")
    logger.warning("  pip install pyodbc  (requires ODBC Driver 18)")
    logger.warning("  sudo apt-get install mssql-tools18  (for sqlcmd)")


# =============================================================================
# TYPE MAPPINGS
# =============================================================================

# SQLite to SQL Server type mapping
SQLITE_TO_MSSQL_TYPES = {
    # Integer types
    'INTEGER': 'INT',
    'INT': 'INT',
    'TINYINT': 'TINYINT',
    'SMALLINT': 'SMALLINT',
    'MEDIUMINT': 'INT',
    'BIGINT': 'BIGINT',
    'UNSIGNED BIG INT': 'BIGINT',
    'INT2': 'SMALLINT',
    'INT8': 'BIGINT',
    
    # Text types
    'TEXT': 'NVARCHAR(MAX)',
    'CHARACTER': 'NVARCHAR(255)',
    'VARCHAR': 'NVARCHAR(255)',
    'VARYING CHARACTER': 'NVARCHAR(255)',
    'NCHAR': 'NCHAR(255)',
    'NATIVE CHARACTER': 'NVARCHAR(255)',
    'NVARCHAR': 'NVARCHAR(255)',
    'CLOB': 'NVARCHAR(MAX)',
    
    # Real/Float types
    'REAL': 'FLOAT',
    'DOUBLE': 'FLOAT',
    'DOUBLE PRECISION': 'FLOAT',
    'FLOAT': 'FLOAT',
    'NUMERIC': 'DECIMAL(18,6)',
    'DECIMAL': 'DECIMAL(18,6)',
    
    # Blob types
    'BLOB': 'VARBINARY(MAX)',
    
    # Boolean (SQLite uses INTEGER)
    'BOOLEAN': 'BIT',
    
    # Date/Time types
    'DATE': 'DATE',
    'DATETIME': 'DATETIME2',
    'TIMESTAMP': 'DATETIME2',
    'TIME': 'TIME',
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ColumnInfo:
    """Information about a database column."""
    name: str
    sqlite_type: str
    mssql_type: str
    is_nullable: bool
    is_primary_key: bool
    default_value: Optional[str] = None


@dataclass
class TableInfo:
    """Information about a database table."""
    name: str
    columns: List[ColumnInfo]
    primary_keys: List[str]
    row_count: int = 0


@dataclass
class MigrationResult:
    """Result of migration for a single table."""
    table_name: str
    success: bool
    source_rows: int
    migrated_rows: int
    error: Optional[str] = None


# =============================================================================
# AZURE CLI HELPERS
# =============================================================================

def run_az_command(args: List[str], capture_output: bool = True) -> Tuple[int, str, str]:
    """Run an Azure CLI command."""
    cmd = ['az'] + args
    logger.debug(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(
        cmd,
        capture_output=capture_output,
        text=True
    )
    
    return result.returncode, result.stdout, result.stderr


def check_az_login() -> bool:
    """Check if Azure CLI is logged in."""
    returncode, stdout, stderr = run_az_command(['account', 'show'])
    return returncode == 0


def get_access_token() -> Optional[str]:
    """Get Azure AD access token for SQL Server."""
    returncode, stdout, stderr = run_az_command([
        'account', 'get-access-token',
        '--resource', 'https://database.windows.net/',
        '--query', 'accessToken',
        '-o', 'tsv'
    ])
    
    if returncode == 0:
        return stdout.strip()
    else:
        logger.error(f"Failed to get access token: {stderr}")
        return None


def create_database(
    resource_group: str,
    server_name: str,
    database_name: str,
    service_objective: str = 'Basic'
) -> bool:
    """Create Azure SQL Database using Azure CLI."""
    logger.info(f"Creating database '{database_name}' on server '{server_name}'...")
    
    # Check if database exists
    returncode, stdout, stderr = run_az_command([
        'sql', 'db', 'show',
        '--resource-group', resource_group,
        '--server', server_name,
        '--name', database_name
    ])
    
    if returncode == 0:
        logger.info(f"Database '{database_name}' already exists")
        return True
    
    # Create database
    returncode, stdout, stderr = run_az_command([
        'sql', 'db', 'create',
        '--resource-group', resource_group,
        '--server', server_name,
        '--name', database_name,
        '--service-objective', service_objective
    ])
    
    if returncode == 0:
        logger.info(f"✓ Database '{database_name}' created successfully")
        return True
    else:
        logger.error(f"Failed to create database: {stderr}")
        return False


def add_firewall_rule(
    resource_group: str,
    server_name: str,
    rule_name: str = 'AllowCurrentIP'
) -> bool:
    """Add firewall rule for current IP."""
    import urllib.request
    
    try:
        # Get current IP
        my_ip = urllib.request.urlopen('https://api.ipify.org').read().decode('utf8')
        logger.info(f"Your IP address: {my_ip}")
        
        returncode, stdout, stderr = run_az_command([
            'sql', 'server', 'firewall-rule', 'create',
            '--resource-group', resource_group,
            '--server', server_name,
            '--name', rule_name,
            '--start-ip-address', my_ip,
            '--end-ip-address', my_ip
        ])
        
        if returncode == 0:
            logger.info(f"✓ Firewall rule '{rule_name}' added for IP {my_ip}")
            return True
        elif 'already exists' in stderr.lower():
            logger.info(f"Firewall rule '{rule_name}' already exists")
            return True
        else:
            logger.warning(f"Could not add firewall rule: {stderr}")
            return False
            
    except Exception as e:
        logger.warning(f"Could not add firewall rule: {e}")
        return False


# =============================================================================
# SQLITE HELPERS
# =============================================================================

def get_sqlite_tables(conn: sqlite3.Connection) -> List[str]:
    """Get list of tables from SQLite database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return [row[0] for row in cursor.fetchall()]


def get_table_info(conn: sqlite3.Connection, table_name: str) -> TableInfo:
    """Get detailed information about a SQLite table."""
    # Get column info
    cursor = conn.execute(f"PRAGMA table_info('{table_name}')")
    columns = []
    primary_keys = []
    
    for row in cursor.fetchall():
        cid, name, col_type, not_null, default_val, is_pk = row
        
        # Convert SQLite type to MSSQL type
        sqlite_type = col_type.upper() if col_type else 'TEXT'
        
        # Handle types with length specifiers like VARCHAR(255)
        base_type = re.split(r'[\(\)]', sqlite_type)[0].strip()
        mssql_type = SQLITE_TO_MSSQL_TYPES.get(base_type, 'NVARCHAR(MAX)')
        
        # Preserve length for VARCHAR types
        if 'VARCHAR' in sqlite_type and '(' in sqlite_type:
            length = re.search(r'\((\d+)\)', sqlite_type)
            if length:
                mssql_type = f"NVARCHAR({length.group(1)})"
        
        column = ColumnInfo(
            name=name,
            sqlite_type=sqlite_type,
            mssql_type=mssql_type,
            is_nullable=(not_null == 0),
            is_primary_key=(is_pk > 0),
            default_value=default_val
        )
        columns.append(column)
        
        if is_pk > 0:
            primary_keys.append(name)
    
    # Get row count
    cursor = conn.execute(f"SELECT COUNT(*) FROM '{table_name}'")
    row_count = cursor.fetchone()[0]
    
    return TableInfo(
        name=table_name,
        columns=columns,
        primary_keys=primary_keys,
        row_count=row_count
    )


def get_table_data(conn: sqlite3.Connection, table_name: str) -> Tuple[List[str], List[Tuple]]:
    """Get all data from a SQLite table."""
    cursor = conn.execute(f"SELECT * FROM '{table_name}'")
    columns = [description[0] for description in cursor.description]
    rows = cursor.fetchall()
    return columns, rows

# =============================================================================
# SQL SERVER HELPERS - SQLCMD BACKEND
# =============================================================================

class SqlCmdCursor:
    """Cursor-like object for SqlCmdBackend."""
    
    def __init__(self, backend: 'SqlCmdBackend'):
        self.backend = backend
        self._last_result = None
        self._last_output = ""
    
    def execute(self, sql: str, params: tuple = None) -> None:
        """Execute SQL statement."""
        # Handle parameterized queries by substituting values
        if params:
            # Simple parameter substitution for ? placeholders
            for param in params:
                if param is None:
                    sql = sql.replace('?', 'NULL', 1)
                elif isinstance(param, str):
                    # Escape single quotes
                    escaped = param.replace("'", "''")
                    sql = sql.replace('?', f"N'{escaped}'", 1)
                elif isinstance(param, (int, float)):
                    sql = sql.replace('?', str(param), 1)
                else:
                    escaped = str(param).replace("'", "''")
                    sql = sql.replace('?', f"N'{escaped}'", 1)
        
        success, output = self.backend._execute_sql(sql)
        self._last_result = success
        self._last_output = output
        
        if not success:
            raise Exception(f"SQL execution failed: {output}")
    
    def executemany(self, sql: str, params_list: List[tuple]) -> None:
        """Execute SQL for multiple parameter sets."""
        # Build a batch of INSERT statements
        statements = []
        for params in params_list:
            stmt = sql
            for param in params:
                if param is None:
                    stmt = stmt.replace('?', 'NULL', 1)
                elif isinstance(param, str):
                    escaped = param.replace("'", "''")
                    stmt = stmt.replace('?', f"N'{escaped}'", 1)
                elif isinstance(param, (int, float)):
                    stmt = stmt.replace('?', str(param), 1)
                else:
                    escaped = str(param).replace("'", "''")
                    stmt = stmt.replace('?', f"N'{escaped}'", 1)
            statements.append(stmt)
        
        # Execute all statements in one batch
        batch_sql = "SET NOCOUNT ON;\n" + "\n".join(statements)
        success, output = self.backend._execute_sql(batch_sql)
        self._last_result = success
        self._last_output = output
        
        if not success:
            raise Exception(f"Batch execution failed: {output}")
    
    def fetchone(self) -> Optional[tuple]:
        """Fetch one row from results."""
        # Parse last output
        lines = [l.strip() for l in self._last_output.strip().split('\n') if l.strip()]
        
        # Skip header lines and separators
        data_lines = []
        for line in lines:
            if line.startswith('-') or not line:
                continue
            if '---' in line:
                continue
            # Skip "rows affected" messages
            if 'rows affected' in line.lower():
                continue
            data_lines.append(line)
        
        if len(data_lines) >= 2:
            # First line is headers, second is data
            # For COUNT(*) queries, just return the number
            try:
                parts = data_lines[1].split()
                if parts:
                    return (int(parts[0]),)
            except (ValueError, IndexError):
                pass
        
        return (0,)
    
    def fetchall(self) -> List[tuple]:
        """Fetch all rows."""
        result = self.fetchone()
        return [result] if result else []


class SqlCmdBackend:
    """SQL Server connection using sqlcmd CLI tool."""
    
    def __init__(self, server: str, database: str, access_token: str):
        self.server = server
        self.database = database
        self.access_token = access_token
        self._temp_files = []
    
    def _execute_sql(self, sql: str) -> Tuple[bool, str]:
        """Execute SQL using sqlcmd with Azure AD authentication.
        
        Uses cached Azure CLI credentials (from 'az login').
        The -G flag tells sqlcmd to use Azure AD auth.
        """
        # Write SQL to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False, encoding='utf-8') as f:
            f.write(sql)
            sql_file = f.name
            self._temp_files.append(sql_file)
        
        try:
            # Use -G flag for Microsoft Entra ID (Azure AD) authentication
            # This uses the cached az login credentials, no username/password needed
            cmd = [
                'sqlcmd',
                '-S', self.server,
                '-d', self.database,
                '-G',  # Microsoft Entra ID authentication (uses az login)
                '-i', sql_file,
                '-I',  # Enable quoted identifiers
                '-b',  # Return error code on failure
                '-W',  # Remove trailing whitespace
                '-C',  # Trust server certificate
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr or result.stdout
                
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)
        finally:
            # Cleanup temp file
            try:
                os.unlink(sql_file)
            except:
                pass
    
    def cursor(self) -> SqlCmdCursor:
        """Return a cursor-like object."""
        return SqlCmdCursor(self)
    
    def commit(self):
        """No-op for sqlcmd (auto-commit)."""
        pass
    
    def close(self):
        """Cleanup temp files."""
        for f in self._temp_files:
            try:
                os.unlink(f)
            except:
                pass


# =============================================================================
# SQL SERVER HELPERS - PYODBC BACKEND
# =============================================================================

def get_azure_sql_connection(server: str, database: str, access_token: str, use_sqlcmd: bool = False) -> Union['pyodbc.Connection', SqlCmdBackend]:
    """Create connection to Azure SQL using Azure AD token."""
    
    # If user explicitly requested sqlcmd, use it or fail clearly
    if use_sqlcmd:
        if HAS_SQLCMD:
            logger.info("Using sqlcmd backend for Azure SQL connection")
            return SqlCmdBackend(server, database, access_token)
        else:
            logger.error("sqlcmd not found in PATH. Install mssql-tools18 or add to PATH:")
            logger.error("  export PATH=\"$PATH:/opt/mssql-tools18/bin\"")
            raise RuntimeError("sqlcmd not available but --use-sqlcmd was specified")
    
    # Default: try pyodbc first
    if not HAS_PYODBC:
        if HAS_SQLCMD:
            logger.info("pyodbc not available, using sqlcmd backend")
            return SqlCmdBackend(server, database, access_token)
        raise RuntimeError("Neither pyodbc nor sqlcmd available")
    
    import struct
    
    # Connection string for Azure AD token authentication
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes;"  # Changed to yes to avoid cert issues
    )
    
    # Connect with access token using proper struct packing
    # Reference: https://docs.microsoft.com/en-us/sql/connect/odbc/using-azure-active-directory
    SQL_COPT_SS_ACCESS_TOKEN = 1256
    
    # Encode token as UTF-16-LE and pack with length prefix
    token_bytes = access_token.encode('utf-16-le')
    # Use struct for proper 4-byte length prefix (little-endian unsigned int)
    token_struct = struct.pack('<I', len(token_bytes)) + token_bytes
    
    try:
        conn = pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})
        return conn
    except Exception as e:
        logger.error(f"pyodbc connection failed: {e}")
        logger.info("Falling back to sqlcmd backend...")
        if HAS_SQLCMD:
            return SqlCmdBackend(server, database, access_token)
        raise


def generate_create_table_sql(table_info: TableInfo) -> str:
    """Generate T-SQL CREATE TABLE statement."""
    columns_sql = []
    
    for col in table_info.columns:
        col_def = f"    [{col.name}] {col.mssql_type}"
        
        if not col.is_nullable:
            col_def += " NOT NULL"
        
        if col.default_value is not None:
            # Handle default values
            default = col.default_value
            if default.upper() == 'CURRENT_TIMESTAMP':
                default = 'GETDATE()'
            col_def += f" DEFAULT {default}"
        
        columns_sql.append(col_def)
    
    # Add primary key constraint
    if table_info.primary_keys:
        pk_cols = ', '.join([f"[{pk}]" for pk in table_info.primary_keys])
        columns_sql.append(f"    PRIMARY KEY ({pk_cols})")
    
    sql = f"""
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = '{table_info.name}')
BEGIN
    CREATE TABLE [{table_info.name}] (
{','.join(chr(10) + col for col in columns_sql)}
    )
END
"""
    return sql.strip()


def create_table(conn: 'pyodbc.Connection', table_info: TableInfo) -> bool:
    """Create table in Azure SQL."""
    try:
        create_sql = generate_create_table_sql(table_info)
        logger.debug(f"Creating table SQL:\n{create_sql}")
        
        cursor = conn.cursor()
        cursor.execute(create_sql)
        conn.commit()
        
        logger.info(f"  ✓ Table [{table_info.name}] created/verified")
        return True
        
    except Exception as e:
        logger.error(f"  ✗ Failed to create table [{table_info.name}]: {e}")
        return False


def insert_data(
    conn: 'pyodbc.Connection',
    table_name: str,
    columns: List[str],
    rows: List[Tuple],
    batch_size: int = 100
) -> int:
    """Insert data into Azure SQL table in batches."""
    if not rows:
        return 0
    
    # Build INSERT statement
    col_names = ', '.join([f"[{col}]" for col in columns])
    placeholders = ', '.join(['?' for _ in columns])
    insert_sql = f"INSERT INTO [{table_name}] ({col_names}) VALUES ({placeholders})"
    
    cursor = conn.cursor()
    total_inserted = 0
    
    # Insert in batches
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        
        try:
            cursor.executemany(insert_sql, batch)
            conn.commit()
            total_inserted += len(batch)
            
            # Progress indicator
            if len(rows) > 1000 and (i + batch_size) % 1000 == 0:
                logger.info(f"    ... inserted {total_inserted}/{len(rows)} rows")
                
        except Exception as e:
            logger.error(f"  ✗ Batch insert failed at row {i}: {e}")
            # Try row-by-row for this batch to identify problematic row
            for j, row in enumerate(batch):
                try:
                    cursor.execute(insert_sql, row)
                    conn.commit()
                    total_inserted += 1
                except Exception as row_error:
                    logger.warning(f"    Skipping row {i+j}: {row_error}")
    
    return total_inserted


def verify_row_count(conn: 'pyodbc.Connection', table_name: str) -> int:
    """Get row count from Azure SQL table."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
    return cursor.fetchone()[0]


# =============================================================================
# MIGRATION ORCHESTRATION
# =============================================================================

def migrate_table(
    sqlite_conn: sqlite3.Connection,
    mssql_conn: 'pyodbc.Connection',
    table_info: TableInfo,
    truncate_existing: bool = False
) -> MigrationResult:
    """Migrate a single table from SQLite to Azure SQL."""
    try:
        logger.info(f"\nMigrating table: {table_info.name} ({table_info.row_count} rows)")
        
        # Create table
        if not create_table(mssql_conn, table_info):
            return MigrationResult(
                table_name=table_info.name,
                success=False,
                source_rows=table_info.row_count,
                migrated_rows=0,
                error="Failed to create table"
            )
        
        # Truncate if requested
        if truncate_existing:
            try:
                cursor = mssql_conn.cursor()
                cursor.execute(f"TRUNCATE TABLE [{table_info.name}]")
                mssql_conn.commit()
                logger.info(f"  ✓ Truncated existing data")
            except Exception as e:
                logger.warning(f"  Could not truncate (table may be empty): {e}")
        
        # Get data from SQLite
        columns, rows = get_table_data(sqlite_conn, table_info.name)
        
        if not rows:
            logger.info(f"  ⊘ Table is empty, nothing to migrate")
            return MigrationResult(
                table_name=table_info.name,
                success=True,
                source_rows=0,
                migrated_rows=0
            )
        
        # Insert data
        inserted = insert_data(mssql_conn, table_info.name, columns, rows)
        
        # Verify
        target_count = verify_row_count(mssql_conn, table_info.name)
        
        success = (inserted == table_info.row_count)
        if success:
            logger.info(f"  ✓ Migrated {inserted} rows (verified: {target_count})")
        else:
            logger.warning(f"  ⚠ Row count mismatch: source={table_info.row_count}, inserted={inserted}, target={target_count}")
        
        return MigrationResult(
            table_name=table_info.name,
            success=success,
            source_rows=table_info.row_count,
            migrated_rows=inserted
        )
        
    except Exception as e:
        logger.error(f"  ✗ Migration failed: {e}")
        return MigrationResult(
            table_name=table_info.name,
            success=False,
            source_rows=table_info.row_count,
            migrated_rows=0,
            error=str(e)
        )


def run_migration(
    source_db: str,
    server: str,
    database: str,
    resource_group: Optional[str] = None,
    service_objective: str = 'Basic',
    truncate_existing: bool = False,
    tables: Optional[List[str]] = None,
    skip_db_creation: bool = False,
    skip_firewall: bool = False,
    use_sqlcmd: bool = False
) -> Dict[str, Any]:
    """
    Run the full migration process.
    
    Args:
        source_db: Path to SQLite database file
        server: Azure SQL Server FQDN (e.g., server.database.windows.net)
        database: Target database name
        resource_group: Azure resource group (required for DB creation)
        service_objective: Azure SQL tier (Basic, S0, S1, etc.)
        truncate_existing: Whether to truncate existing tables before insert
        tables: Optional list of specific tables to migrate
        skip_db_creation: Skip database creation step
        skip_firewall: Skip firewall rule creation
        
    Returns:
        Dict with migration results
    """
    results = {
        'success': False,
        'source_db': source_db,
        'target_server': server,
        'target_database': database,
        'tables_migrated': 0,
        'tables_failed': 0,
        'total_rows_migrated': 0,
        'details': []
    }
    
    # Validate source file
    source_path = Path(source_db)
    if not source_path.exists():
        logger.error(f"Source database not found: {source_db}")
        return results
    
    logger.info(f"=" * 60)
    logger.info(f"SQLite to Azure SQL Migration")
    logger.info(f"=" * 60)
    logger.info(f"Source: {source_db}")
    logger.info(f"Target: {server}/{database}")
    logger.info(f"=" * 60)
    
    # Check Azure CLI login
    if not check_az_login():
        logger.error("Not logged in to Azure CLI. Run 'az login' first.")
        return results
    
    logger.info("✓ Azure CLI authenticated")
    
    # Extract server name (without domain)
    server_name = server.replace('.database.windows.net', '')
    
    # Create database if needed
    if not skip_db_creation:
        if not resource_group:
            logger.error("--resource-group is required for database creation")
            return results
        
        if not create_database(resource_group, server_name, database, service_objective):
            logger.error("Failed to create database")
            return results
    
    # Add firewall rule
    if not skip_firewall and resource_group:
        add_firewall_rule(resource_group, server_name, f"Migration-{database}")
    
    # Get access token
    access_token = get_access_token()
    if not access_token:
        logger.error("Failed to get Azure AD access token")
        return results
    
    logger.info("✓ Azure AD access token obtained")
    
    # Connect to SQLite
    try:
        sqlite_conn = sqlite3.connect(source_db)
        logger.info(f"✓ Connected to SQLite database")
    except Exception as e:
        logger.error(f"Failed to connect to SQLite: {e}")
        return results
    
    # Connect to Azure SQL
    try:
        mssql_conn = get_azure_sql_connection(server, database, access_token, use_sqlcmd=use_sqlcmd)
        logger.info(f"✓ Connected to Azure SQL database")
    except Exception as e:
        logger.error(f"Failed to connect to Azure SQL: {e}")
        logger.error("Make sure:")
        logger.error("  1. Firewall rule allows your IP")
        logger.error("  2. ODBC Driver 18 for SQL Server is installed (or use --use-sqlcmd)")
        logger.error("  3. You have access to the database")
        logger.error("  Try: --use-sqlcmd flag to use sqlcmd backend instead")
        return results
    
    # Get tables to migrate
    all_tables = get_sqlite_tables(sqlite_conn)
    if tables:
        target_tables = [t for t in tables if t in all_tables]
        if len(target_tables) != len(tables):
            missing = set(tables) - set(target_tables)
            logger.warning(f"Tables not found in source: {missing}")
    else:
        target_tables = all_tables
    
    logger.info(f"\nTables to migrate: {len(target_tables)}")
    for t in target_tables:
        table_info = get_table_info(sqlite_conn, t)
        logger.info(f"  - {t}: {table_info.row_count} rows, {len(table_info.columns)} columns")
    
    # Migrate each table
    migration_results = []
    for table_name in target_tables:
        table_info = get_table_info(sqlite_conn, table_name)
        result = migrate_table(sqlite_conn, mssql_conn, table_info, truncate_existing)
        migration_results.append(result)
    
    # Close connections
    sqlite_conn.close()
    mssql_conn.close()
    
    # Summary
    logger.info(f"\n" + "=" * 60)
    logger.info("MIGRATION SUMMARY")
    logger.info("=" * 60)
    
    success_count = sum(1 for r in migration_results if r.success)
    fail_count = len(migration_results) - success_count
    total_rows = sum(r.migrated_rows for r in migration_results)
    
    for r in migration_results:
        status = "✓" if r.success else "✗"
        logger.info(f"  {status} {r.table_name}: {r.migrated_rows}/{r.source_rows} rows")
        if r.error:
            logger.info(f"      Error: {r.error}")
    
    logger.info(f"\nTotal: {success_count}/{len(migration_results)} tables migrated")
    logger.info(f"Total rows: {total_rows}")
    
    if fail_count == 0:
        logger.info("\n✓ MIGRATION COMPLETED SUCCESSFULLY")
    else:
        logger.warning(f"\n⚠ MIGRATION COMPLETED WITH {fail_count} FAILURES")
    
    results['success'] = (fail_count == 0)
    results['tables_migrated'] = success_count
    results['tables_failed'] = fail_count
    results['total_rows_migrated'] = total_rows
    results['details'] = [
        {
            'table': r.table_name,
            'success': r.success,
            'source_rows': r.source_rows,
            'migrated_rows': r.migrated_rows,
            'error': r.error
        }
        for r in migration_results
    ]
    
    return results


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Migrate SQLite database to Azure SQL Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic migration
  python migrate_to_azure_sql.py \\
    --source tdn_op.db \\
    --server sql-server.database.windows.net \\
    --database mydb \\
    --resource-group my-rg

  # Migrate specific tables only
  python migrate_to_azure_sql.py \\
    --source data.db \\
    --server sql.database.windows.net \\
    --database mydb \\
    --resource-group my-rg \\
    --tables users orders

  # Skip database creation (already exists)
  python migrate_to_azure_sql.py \\
    --source data.db \\
    --server sql.database.windows.net \\
    --database existing-db \\
    --skip-db-creation
"""
    )
    
    parser.add_argument(
        '--source', '-s',
        required=True,
        help='Path to source SQLite database file'
    )
    
    parser.add_argument(
        '--server',
        required=True,
        help='Azure SQL Server FQDN (e.g., myserver.database.windows.net)'
    )
    
    parser.add_argument(
        '--database', '-d',
        required=True,
        help='Target database name'
    )
    
    parser.add_argument(
        '--resource-group', '-g',
        help='Azure resource group (required for database creation)'
    )
    
    parser.add_argument(
        '--service-objective',
        default='Basic',
        help='Azure SQL service tier (default: Basic)'
    )
    
    parser.add_argument(
        '--tables',
        nargs='+',
        help='Specific tables to migrate (default: all)'
    )
    
    parser.add_argument(
        '--truncate',
        action='store_true',
        help='Truncate existing tables before inserting'
    )
    
    parser.add_argument(
        '--skip-db-creation',
        action='store_true',
        help='Skip database creation (use existing database)'
    )
    
    parser.add_argument(
        '--skip-firewall',
        action='store_true',
        help='Skip firewall rule creation'
    )
    
    parser.add_argument(
        '--output-json',
        help='Write results to JSON file'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--use-sqlcmd',
        action='store_true',
        help='Use sqlcmd backend instead of pyodbc (recommended if pyodbc causes segfaults)'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Run migration
    results = run_migration(
        source_db=args.source,
        server=args.server,
        database=args.database,
        resource_group=args.resource_group,
        service_objective=args.service_objective,
        truncate_existing=args.truncate,
        tables=args.tables,
        skip_db_creation=args.skip_db_creation,
        skip_firewall=args.skip_firewall,
        use_sqlcmd=args.use_sqlcmd
    )
    
    # Write JSON output if requested
    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"\nResults written to: {args.output_json}")
    
    # Exit with appropriate code
    sys.exit(0 if results['success'] else 1)


if __name__ == '__main__':
    main()
