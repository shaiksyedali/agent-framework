"""
Azure Function: SQL Tool for Azure SQL Database
Executes on Azure Functions (serverless)
Uses Managed Identity for secure authentication
"""

import azure.functions as func
import json
import logging
import os



async def main(req: func.HttpRequest) -> func.HttpResponse:
    # Add vendored packages to path
    import sys
    import os
    site_packages = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.python_packages', 'lib', 'site-packages')
    if site_packages not in sys.path:
        sys.path.append(site_packages)

    """
    Execute SQL query on Azure SQL Database.

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

        # Lazy load dependencies
        import pyodbc
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient


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

        # Connect to Azure SQL (can use private endpoint)
        conn = pyodbc.connect(conn_string, timeout=30)
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

            # Convert to list of dicts (handle None values and types)
            result_rows = []
            for row in rows:
                row_dict = {}
                for i, value in enumerate(row):
                    if value is not None:
                        row_dict[columns[i]] = str(value)
                    else:
                        row_dict[columns[i]] = None
                result_rows.append(row_dict)

            response = {
                "success": True,
                "rows": result_rows,
                "row_count": len(result_rows),
                "columns": columns,
                "dialect": "mssql"  # Azure SQL is always SQL Server
            }
        else:  # INSERT/UPDATE/DELETE
            conn.commit()
            response = {
                "success": True,
                "rows_affected": cursor.rowcount,
                "message": f"Query executed successfully. {cursor.rowcount} rows affected.",
                "dialect": "mssql"
            }

        conn.close()

        logging.info(f"Query executed successfully. Row count: {response.get('row_count', 0)}")

        return func.HttpResponse(
            json.dumps(response, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except pyodbc.Error as e:
        logging.error(f"SQL error: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "SQLError"
            }),
            mimetype="application/json",
            status_code=500
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
