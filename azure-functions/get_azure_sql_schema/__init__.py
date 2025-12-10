"""
Azure Function: Get Schema for Azure SQL Database
Returns database schema including tables, columns, and data types
"""

import azure.functions as func
import json
import logging
import os
import pyodbc
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient


async def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get schema for Azure SQL Database.

    Request Body:
        {
            "database": "mydb"  // optional, defaults to 'default'
        }

    Response:
        {
            "success": true,
            "database": "mydb",
            "database_type": "azure_sql",
            "tables": {
                "users": [
                    {"name": "id", "type": "int", "nullable": false},
                    {"name": "name", "type": "varchar", "nullable": true}
                ]
            },
            "table_count": 5
        }
    """
    logging.info('Azure SQL Schema Function triggered')

    try:
        # Parse request
        req_body = req.get_json()
        database = req_body.get('database', 'default')

        logging.info(f"Retrieving schema for database: {database}")

        # Get connection string from Key Vault
        vault_url = os.environ.get("KEY_VAULT_URL")
        if not vault_url:
            raise ValueError("KEY_VAULT_URL environment variable not set")

        credential = DefaultAzureCredential()
        secret_client = SecretClient(vault_url=vault_url, credential=credential)

        secret_name = f"{database}-connection-string"
        try:
            secret = secret_client.get_secret(secret_name)
            conn_string = secret.value
        except Exception as e:
            logging.error(f"Failed to retrieve secret '{secret_name}': {str(e)}")
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Database configuration not found for '{database}'",
                    "error_type": "ConfigurationError"
                }),
                mimetype="application/json",
                status_code=404
            )

        # Connect to Azure SQL
        conn = pyodbc.connect(conn_string, timeout=30)
        cursor = conn.cursor()

        # Get schema information using INFORMATION_SCHEMA
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
            AND t.TABLE_SCHEMA = 'dbo'
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

        logging.info(f"Retrieved schema with {len(schema)} tables")

        return func.HttpResponse(
            json.dumps({
                "success": True,
                "database": database,
                "database_type": "azure_sql",
                "dialect": "mssql",
                "tables": schema,
                "table_count": len(schema)
            }, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Error retrieving schema: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            mimetype="application/json",
            status_code=500
        )
