"""
Azure SQL Database Connector with Managed Identity support.

Provides secure database access using Azure Managed Identity or connection strings
stored in Azure Key Vault.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from agent_framework.data.connectors import SQLConnector, SQLApprovalPolicy

try:
    import pyodbc
except ImportError:
    raise ImportError(
        "pyodbc not installed. Install with: pip install pyodbc\n"
        "Note: Requires ODBC Driver 18 for SQL Server"
    )

try:
    from azure.identity.aio import DefaultAzureCredential
    from azure.keyvault.secrets.aio import SecretClient
except ImportError:
    raise ImportError(
        "Azure packages not installed. Install with:\n"
        "  pip install azure-identity azure-keyvault-secrets"
    )

logger = logging.getLogger(__name__)


class AzureSQLConnector(SQLConnector):
    """
    Azure SQL Database connector with Managed Identity authentication.

    Supports two authentication modes:
    1. Managed Identity (recommended for Azure-hosted applications)
    2. Connection string from Key Vault

    Example with Managed Identity:
        ```python
        connector = AzureSQLConnector(
            server="myserver.database.windows.net",
            database="sales-db",
            use_managed_identity=True
        )

        schema = connector.get_schema()
        results = connector.run_query("SELECT * FROM customers LIMIT 10")
        ```

    Example with Key Vault:
        ```python
        connector = AzureSQLConnector(
            keyvault_uri="https://my-keyvault.vault.azure.net/",
            keyvault_secret_name="sql-connection-string",
            use_managed_identity=False
        )
        ```
    """

    def __init__(
        self,
        *,
        server: str | None = None,
        database: str | None = None,
        use_managed_identity: bool = True,
        keyvault_uri: str | None = None,
        keyvault_secret_name: str | None = None,
        driver: str = "ODBC Driver 18 for SQL Server",
        approval_policy: SQLApprovalPolicy | None = None,
    ):
        """
        Initialize Azure SQL connector.

        Args:
            server: Azure SQL server FQDN (e.g., 'myserver.database.windows.net')
            database: Database name
            use_managed_identity: Use Managed Identity for authentication
            keyvault_uri: Azure Key Vault URI for connection string
            keyvault_secret_name: Secret name in Key Vault
            driver: ODBC driver name
            approval_policy: SQL approval policy for query gating

        Raises:
            ValueError: If required parameters are missing
        """
        super().__init__(approval_policy=approval_policy)

        self.use_managed_identity = use_managed_identity

        if use_managed_identity:
            if not server or not database:
                raise ValueError(
                    "server and database required for Managed Identity authentication"
                )
            self.server = server
            self.database = database
            self.driver = driver
            self._credential = None
        else:
            if not keyvault_uri or not keyvault_secret_name:
                raise ValueError(
                    "keyvault_uri and keyvault_secret_name required for Key Vault authentication"
                )
            self.keyvault_uri = keyvault_uri
            self.keyvault_secret_name = keyvault_secret_name
            self._connection_string = None
            self._credential = None

    @property
    def dialect(self) -> str:
        """Return the SQL dialect for this connector."""
        return "mssql"

    async def _get_connection(self) -> pyodbc.Connection:
        """Get database connection with appropriate authentication"""

        if self.use_managed_identity:
            # Use Managed Identity
            if not self._credential:
                self._credential = DefaultAzureCredential()

            # Get access token for Azure SQL
            token = await self._credential.get_token(
                "https://database.windows.net/.default"
            )

            # Build connection string with token
            connection_string = (
                f"Driver={{{self.driver}}};"
                f"Server=tcp:{self.server},1433;"
                f"Database={self.database};"
                f"Encrypt=yes;"
                f"TrustServerCertificate=no;"
                f"Connection Timeout=30;"
            )

            # Convert token to struct for SQL Server
            import struct

            token_bytes = token.token.encode("utf-16-le")
            token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

            # Connect with token
            conn = pyodbc.connect(
                connection_string,
                attrs_before={1256: token_struct}  # SQL_COPT_SS_ACCESS_TOKEN
            )
        else:
            # Use connection string from Key Vault
            if not self._connection_string:
                await self._load_connection_string_from_keyvault()

            conn = pyodbc.connect(self._connection_string)

        return conn

    async def _load_connection_string_from_keyvault(self):
        """Load connection string from Azure Key Vault"""
        if not self._credential:
            self._credential = DefaultAzureCredential()

        secret_client = SecretClient(
            vault_url=self.keyvault_uri, credential=self._credential
        )

        try:
            secret = await secret_client.get_secret(self.keyvault_secret_name)
            self._connection_string = secret.value
            logger.info(
                f"Loaded connection string from Key Vault: {self.keyvault_secret_name}"
            )
        finally:
            await secret_client.close()

    def get_schema(self) -> str:
        """
        Get database schema information.

        Returns:
            Human-readable schema description
        """
        # Run synchronously in event loop
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._get_schema_async())
        finally:
            loop.close()

    async def _get_schema_async(self) -> str:
        """Get schema asynchronously"""
        conn = await self._get_connection()

        try:
            cursor = conn.cursor()

            # Get all tables
            cursor.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """)

            tables = cursor.fetchall()

            schema_parts = []

            for schema_name, table_name in tables:
                full_table = f"{schema_name}.{table_name}"

                # Get columns for this table
                cursor.execute(
                    """
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                    ORDER BY ORDINAL_POSITION
                """,
                    (schema_name, table_name),
                )

                columns = cursor.fetchall()

                col_desc = []
                for col_name, data_type, nullable, max_len in columns:
                    type_str = data_type
                    if max_len:
                        type_str += f"({max_len})"
                    null_str = "NULL" if nullable == "YES" else "NOT NULL"
                    col_desc.append(f"  {col_name} {type_str} {null_str}")

                schema_parts.append(f"Table: {full_table}\n" + "\n".join(col_desc))

            return "\n\n".join(schema_parts)

        finally:
            conn.close()

    def run_query(
        self, query: str, params: Sequence[Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Execute SQL query and return results.

        Args:
            query: SQL query to execute
            params: Optional query parameters

        Returns:
            List of dictionaries with query results
        """
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._run_query_async(query, params))
        finally:
            loop.close()

    async def _run_query_async(
        self, query: str, params: Sequence[Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute query asynchronously"""
        conn = await self._get_connection()

        try:
            cursor = conn.cursor()

            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            # Check if query returns results
            if cursor.description is None:
                # DML query (INSERT, UPDATE, DELETE)
                conn.commit()
                return [{"rows_affected": cursor.rowcount}]

            # Get column names
            columns = [column[0] for column in cursor.description]

            # Fetch all rows
            rows = cursor.fetchall()

            # Convert to list of dicts
            results = []
            for row in rows:
                results.append(dict(zip(columns, row)))

            return results

        finally:
            conn.close()

    async def close(self):
        """Close and clean up resources"""
        if self._credential:
            await self._credential.close()
            self._credential = None
