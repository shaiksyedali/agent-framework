"""
END-TO-END TEST WITH CORRECT TOOL NAMES
Tests that tools match agent expectations from scripts/create_azure_agents.py
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential
from azure.ai.agents.models import AsyncFunctionTool

# Add to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_framework.tools import LocalSQLTools

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Test with correct tool alignment"""
    
    logger.info("="*80)
    logger.info("END-TO-END TEST: Tool Name Alignment")
    logger.info("="*80)
    
    # Load environment
    env_file = Path(__file__).parent.parent.parent.parent.parent / ".env.azure"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value
    
    # Load agent config
    config_file = Path(__file__).parent.parent.parent.parent.parent / "azure_agents_config.json"
    with open(config_file) as f:
        config = json.load(f)
    
    logger.info("\n[1] Agent Configuration:")
    logger.info(f"  SQL Agent ID: {config['agents']['sql_agent']['id']}")
    logger.info(f"  RAG Agent ID: {config['agents']['rag_agent']['id']}")
    
    # Create test database
    db_path = Path(__file__).parent.parent.parent.parent.parent / "data" / "test_e2e.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"\n[2] Setting up test database: {db_path}")
    
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("DROP TABLE IF EXISTS products")
    cursor.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL
        )
    """)
    
    cursor.executemany("""
        INSERT INTO products (name, category, price)
        VALUES (?, ?, ?)
    """, [
        ("Laptop", "Electronics", 1299.99),
        ("Mouse", "Electronics", 29.99),
        ("Desk", "Furniture", 599.99),
        ("Chair", "Furniture", 399.99),
        ("Monitor", "Electronics", 449.99),
    ])
    
    conn.commit()
    conn.close()
    
    logger.info("  ✓ Created products table with 5 rows")
    
    # Initialize tools
    logger.info(f"\n[3] Initializing LocalSQLTools")
    tools = LocalSQLTools(str(db_path))
    
    # Verify tool methods exist
    logger.info(f"\n[4] Verifying tool methods:")
    assert hasattr(tools, 'execute_sql_query'), "Missing execute_sql_query"
    assert hasattr(tools, 'get_database_schema'), "Missing get_database_schema"
    logger.info("  ✓ execute_sql_query exists")
    logger.info("  ✓ get_database_schema exists")
    
    # Test tools directly
    logger.info(f"\n[5] Testing tools directly:")
    
    schema_result = await tools.get_database_schema(database=str(db_path))
    schema_data = json.loads(schema_result)
    logger.info(f"  ✓ get_database_schema: {schema_data['success']}")
    logger.info(f"    Tables: {list(schema_data.get('tables', {}).keys())}")
    
    query_result = await tools.execute_sql_query(
        query="SELECT * FROM products WHERE price > 400",
        database=str(db_path)
    )
    query_data = json.loads(query_result)
    logger.info(f"  ✓ execute_sql_query: {query_data['success']}")
    logger.info(f"    Rows returned: {query_data['row_count']}")
    
    # Initialize Azure client
    logger.info(f"\n[6] Initializing Azure Agents Client")
    credential = DefaultAzureCredential()
    agents_client = AgentsClient(
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        credential=credential
    )
    
    # Register tools with Azure SDK
    logger.info(f"\n[7] Registering tools with Azure Agents SDK")
    function_tool = AsyncFunctionTool({
        tools.execute_sql_query,
        tools.get_database_schema,
        tools.list_tables,
        tools.describe_table
    })
    
    agents_client.enable_auto_function_calls(function_tool, max_retry=10)
    logger.info(f"  ✓ Registered {len(function_tool._functions)} tools")
    logger.info(f"    Tool names: {list(function_tool._functions.keys())}")
    
    # Test with SQL agent
    logger.info(f"\n[8] Testing with SQL Agent")
    sql_agent_id = config["agents"]["sql_agent"]["id"]
    
    test_query = (
        f"I have a database at {db_path}. "
        "Please get the schema first, then query all products with price > 400. "
        "Format the results as a table."
    )
    
    logger.info(f"  Query: {test_query[:100]}...")
    logger.info(f"  Agent ID: {sql_agent_id}")
    
    try:
        result = await agents_client.create_thread_and_process_run(
            agent_id=sql_agent_id,
            thread={"messages": [{"role": "user", "content": test_query}]}
        )
        
        logger.info(f"\n[9] Agent Response:")
        logger.info(f"  Status: {result.status}")
        logger.info(f"  Thread ID: {result.thread_id}")
        
        if result.status == "completed":
            logger.info("\n  ✓✓✓ TEST PASSED ✓✓✓")
        else:
            logger.error(f"\n  ✗ Test failed with status: {result.status}")
            if hasattr(result, 'last_error'):
                logger.error(f"  Error: {result.last_error}")
        
    except Exception as e:
        logger.error(f"\n  ✗ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
    
    # Cleanup
    await agents_client.close()
    await credential.close()
    
    logger.info("\n" + "="*80)
    logger.info("TEST COMPLETE")
    logger.info("="*80)


if __name__ == "__main__":
    asyncio.run(main())
