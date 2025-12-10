"""
Simple Azure Foundry SQL Query Example

Demonstrates basic SQL query execution using Azure Foundry SQL agent.

Usage:
    python examples/azure_simple_sql_example.py
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python" / "packages" / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent / "python" / "packages" / "azure-ai"))

from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from agent_framework_azure_ai import AzureFoundryAgentAdapter, ToolExecutor
from agent_framework.data.connectors import SQLiteConnector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Execute simple SQL query"""

    # Load configuration
    config_file = Path(__file__).parent.parent / "azure_agents_config.json"
    with open(config_file) as f:
        config = json.load(f)

    # Initialize
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        credential=credential,
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    )

    # Create sample database
    import sqlite3
    conn = sqlite3.connect("demo.db")
    conn.execute("CREATE TABLE IF NOT EXISTS customers (id INT, name TEXT, revenue REAL)")
    conn.execute("INSERT OR REPLACE INTO customers VALUES (1, 'Acme Corp', 50000)")
    conn.execute("INSERT OR REPLACE INTO customers VALUES (2, 'TechStart Inc', 75000)")
    conn.execute("INSERT OR REPLACE INTO customers VALUES (3, 'Global Industries', 120000)")
    conn.commit()
    conn.close()

    # Setup tools
    sqlite = SQLiteConnector(db_path="demo.db")
    tool_executor = ToolExecutor()
    tool_executor.register("execute_sql_query", lambda query, database, require_approval=False: sqlite.run_query(query))
    tool_executor.register("get_database_schema", lambda database: sqlite.get_schema())

    # Create SQL agent adapter
    sql_agent = AzureFoundryAgentAdapter(
        agents_client=project_client.agents,
        agent_id=config["agents"]["sql_agent"]["id"],
        agent_name="sql_agent",
        tool_executor=tool_executor
    )

    # Execute query
    logger.info("Querying database...")
    response = await sql_agent.run("What are the top 3 customers by revenue?")

    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(response.messages[0].text)
    print("=" * 60)

    await credential.close()


if __name__ == "__main__":
    asyncio.run(main())
