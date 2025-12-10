"""
Azure Foundry Multi-Agent Workflow Example

Demonstrates end-to-end workflow execution using Azure Foundry agents
with mixed data sources (Azure SQL + local SQLite).

Prerequisites:
    1. Deploy Azure infrastructure: ./scripts/deploy_infrastructure.sh
    2. Create agents: python scripts/create_azure_agents.py
    3. Configure .env.azure with your endpoints
    4. Install dependencies: pip install azure-ai-projects azure-identity pyodbc

Usage:
    python examples/azure_foundry_workflow_example.py
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "python" / "packages" / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent / "python" / "packages" / "azure-ai"))

try:
    from azure.ai.projects.aio import AIProjectClient
    from azure.identity.aio import DefaultAzureCredential
    from agent_framework_azure_ai import (
        AzureFoundryAgentAdapter,
        AzureSQLConnector,
        ToolExecutor,
    )
    from agent_framework.data.connectors import SQLiteConnector
    from agent_framework.orchestrator.context import OrchestrationContext
except ImportError as e:
    print(f"ERROR: Missing dependencies: {e}")
    print("Install with: pip install azure-ai-projects azure-identity pyodbc")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def setup_sample_data():
    """Create sample SQLite database for demonstration"""
    logger.info("Setting up sample local database...")

    import sqlite3

    conn = sqlite3.connect("local_products.db")
    cursor = conn.cursor()

    # Create products table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            price REAL,
            stock_quantity INTEGER
        )
    """)

    # Insert sample data
    sample_products = [
        (1, "Laptop Pro", "Electronics", 1299.99, 45),
        (2, "Wireless Mouse", "Electronics", 29.99, 150),
        (3, "Office Chair", "Furniture", 299.99, 30),
        (4, "Standing Desk", "Furniture", 599.99, 20),
        (5, "Monitor 27in", "Electronics", 399.99, 60),
    ]

    cursor.executemany(
        "INSERT OR REPLACE INTO products VALUES (?, ?, ?, ?, ?)",
        sample_products
    )

    conn.commit()
    conn.close()

    logger.info("✓ Sample database created: local_products.db")


async def main():
    """Main workflow execution"""

    # Load configuration
    config_file = Path(__file__).parent.parent / "azure_agents_config.json"
    if not config_file.exists():
        logger.error("ERROR: azure_agents_config.json not found!")
        logger.error("Run: python scripts/create_azure_agents.py")
        sys.exit(1)

    with open(config_file) as f:
        config = json.load(f)

    # Load environment
    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if not project_endpoint:
        logger.error("ERROR: AZURE_AI_PROJECT_ENDPOINT not set")
        logger.error("Set environment variable or create .env.azure file")
        sys.exit(1)

    # Setup sample data
    await setup_sample_data()

    logger.info("=" * 70)
    logger.info("Azure Foundry Multi-Agent Workflow Example")
    logger.info("=" * 70)
    logger.info("")

    # Initialize Azure clients
    logger.info("Initializing Azure AI Project Client...")
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        credential=credential,
        endpoint=project_endpoint
    )
    agents_client = project_client.agents

    try:
        # Setup data connectors
        logger.info("Setting up data connectors...")

        # Azure SQL connector (if configured)
        azure_sql_server = os.getenv("AZURE_SQL_SERVER")
        azure_sql_database = os.getenv("AZURE_SQL_DATABASE")

        if azure_sql_server and azure_sql_database:
            logger.info(f"  - Azure SQL: {azure_sql_server}/{azure_sql_database}")
            azure_sql_connector = AzureSQLConnector(
                server=azure_sql_server,
                database=azure_sql_database,
                use_managed_identity=True
            )
        else:
            logger.warning("  - Azure SQL not configured, skipping")
            azure_sql_connector = None

        # Local SQLite connector
        logger.info("  - Local SQLite: local_products.db")
        local_sqlite = SQLiteConnector(db_path="local_products.db")

        # Setup tool executor
        logger.info("Configuring tool executor...")
        tool_executor = ToolExecutor()

        # Register SQL tools
        async def execute_sql(query: str, database: str, require_approval: bool = False):
            """Execute SQL query on specified database"""
            logger.info(f"Executing SQL on {database}: {query[:60]}...")

            if require_approval:
                logger.warning("⚠️  Approval required for query (auto-approved in demo)")

            if database == "azure_sales" and azure_sql_connector:
                return azure_sql_connector.run_query(query)
            elif database == "local_products":
                return local_sqlite.run_query(query)
            else:
                return {"error": f"Unknown database: {database}"}

        def get_schema(database: str):
            """Get database schema"""
            logger.info(f"Getting schema for: {database}")

            if database == "azure_sales" and azure_sql_connector:
                return azure_sql_connector.get_schema()
            elif database == "local_products":
                return local_sqlite.get_schema()
            else:
                return f"Database {database} not found"

        tool_executor.register("execute_sql_query", execute_sql)
        tool_executor.register("get_database_schema", get_schema)
        tool_executor.register("list_available_agents", lambda: json.dumps({
            "agents": [
                {"name": "sql_agent", "description": "Query databases"},
                {"name": "rag_agent", "description": "Search documents"},
                {"name": "planner_agent", "description": "Plan workflows"},
                {"name": "executor_agent", "description": "Execute workflows"},
                {"name": "response_generator", "description": "Format responses"}
            ]
        }))

        # Create agent adapters
        logger.info("Creating agent adapters...")

        supervisor = AzureFoundryAgentAdapter(
            agents_client=agents_client,
            agent_id=config["agents"]["supervisor"]["id"],
            agent_name="supervisor_agent",
            description="Master orchestrator agent",
            tool_executor=tool_executor
        )

        logger.info(f"✓ Supervisor agent ready: {supervisor.id}")

        # Setup orchestration context
        context = OrchestrationContext()
        if azure_sql_connector:
            context = context.with_connector("azure_sales_db", azure_sql_connector)
        context = context.with_connector("local_products_db", local_sqlite)

        # Execute workflow
        logger.info("")
        logger.info("=" * 70)
        logger.info("WORKFLOW EXECUTION")
        logger.info("=" * 70)
        logger.info("")

        query = "What products do we have in the local products database? Show me the top 5 by price."

        logger.info(f"User Query:")
        logger.info(f"  {query}")
        logger.info("")
        logger.info("Executing workflow (this may take 30-60 seconds)...")
        logger.info("")

        # Run supervisor agent
        response = await supervisor.run(query)

        logger.info("=" * 70)
        logger.info("WORKFLOW RESPONSE")
        logger.info("=" * 70)
        logger.info("")
        logger.info(response.messages[0].text)
        logger.info("")
        logger.info("=" * 70)
        logger.info("✓ Workflow completed successfully!")
        logger.info("=" * 70)

    finally:
        await credential.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nCancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
