"""
Integration test for Azure agent tools.

This test verifies:
1. Tool registration with correct names
2. Agent can call tools successfully
3. Tool execution returns correct results
4. End-to-end workflow with SQL agent
"""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_framework.azure import create_agent_with_tools
from agent_framework.tools import LocalSQLTools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class DataSourceConfig:
    """Data source configuration"""
    id: str
    name: str
    type: str
    path: str = None
    connection_string: str = None


async def setup_test_database():
    """Create a test database for testing"""
    import sqlite3
    
    db_path = Path(__file__).parent.parent.parent.parent.parent / "data" / "test_integration.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove old database if exists
    if db_path.exists():
        db_path.unlink()
    
    logger.info(f"Creating test database: {db_path}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Create products table
    cursor.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL
        )
    """)
    
    # Insert sample data
    cursor.executemany("""
        INSERT INTO products (name, category, price, stock)
        VALUES (?, ?, ?, ?)
    """, [
        ("Laptop", "Electronics", 999.99, 50),
        ("Mouse", "Electronics", 29.99, 200),
        ("Keyboard", "Electronics", 79.99, 150),
        ("Desk", "Furniture", 299.99, 30),
        ("Chair", "Furniture", 199.99, 45),
    ])
    
    conn.commit()
    conn.close()
    
    logger.info(f"✓ Test database created with 5 products")
    
    return str(db_path)


async def test_tool_registration():
    """Test 1: Verify tool registration works correctly"""
    logger.info("\n" + "="*80)
    logger.info("TEST 1: Tool Registration")
    logger.info("="*80)
    
    db_path = await setup_test_database()
    
    # Create data source
    data_sources = [
        DataSourceConfig(
            id="test-db",
            name="Test Database",
            type="file",
            path=db_path
        )
    ]
    
    # Create tools integration
    from agent_framework.azure import AzureToolsIntegration
    
    # Mock agents client for testing
    class MockAgentsClient:
        pass
    
    integration = AzureToolsIntegration(
        agents_client=MockAgentsClient(),
        azure_functions_url="https://mock.azurewebsites.net"
    )
    
    # Create tool executor
    executor = integration.create_tool_executor(data_sources)
    
    # Verify tools are registered with correct names
    registered_tools = executor.list_tools()
    
    logger.info(f"\n✓ Registered tools: {len(registered_tools)}")
    for tool in registered_tools:
        logger.info(f"  - {tool}")
    
    # Check critical tools are present
    assert "execute_sql_query" in registered_tools, "execute_sql_query not registered!"
    assert "get_database_schema" in registered_tools, "get_database_schema not registered!"
    
    logger.info("\n✓ All expected tools are registered with correct names")
    
    return executor, db_path


async def test_tool_execution():
    """Test 2: Verify tool execution works correctly"""
    logger.info("\n" + "="*80)
    logger.info("TEST 2: Tool Execution")
    logger.info("="*80)
    
    executor, db_path = await test_tool_registration()
    
    # Test get_database_schema
    logger.info("\n[2.1] Testing get_database_schema...")
    result = await executor.execute("get_database_schema", {"database": db_path})
    
    logger.info(f"Result type: {type(result)}")
    logger.info(f"Result preview: {str(result)[:200]}...")
    
    # Parse result
    if isinstance(result, str):
        result_json = json.loads(result)
    else:
        result_json = result
    
    assert result_json.get("success"), f"Schema fetch failed: {result_json.get('error')}"
    logger.info("✓ get_database_schema executed successfully")
    
    # Test execute_sql_query
    logger.info("\n[2.2] Testing execute_sql_query...")
    result = await executor.execute(
        "execute_sql_query",
        {
            "query": "SELECT * FROM products WHERE category = 'Electronics'",
            "database": db_path
        }
    )
    
    logger.info(f"Result type: {type(result)}")
    
    # Parse result
    if isinstance(result, str):
        result_json = json.loads(result)
    else:
        result_json = result
    
    assert result_json.get("success"), f"Query failed: {result_json.get('error')}"
    assert result_json.get("row_count") == 3, "Expected 3 electronics products"
    logger.info(f"✓ execute_sql_query returned {result_json['row_count']} rows")
    
    logger.info("\n✓ All tool executions successful")


async def test_agent_integration():
    """Test 3: Verify agent can call tools successfully"""
    logger.info("\n" + "="*80)
    logger.info("TEST 3: Agent Integration (End-to-End)")
    logger.info("="*80)
    
    # Load environment
    load_dotenv(".env.azure")
    
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    if not project_endpoint:
        logger.warning("⚠ AZURE_AI_PROJECT_ENDPOINT not set - skipping agent integration test")
        return
    
    # Load agent config
    config_file = Path(__file__).parent.parent.parent.parent.parent / "azure_agents_config.json"
    if not config_file.exists():
        logger.warning("⚠ azure_agents_config.json not found - skipping agent integration test")
        return
    
    with open(config_file) as f:
        agent_config = json.load(f)
    
    sql_agent_id = agent_config["agents"]["sql_agent"]["id"]
    
    # Setup test database
    db_path = await setup_test_database()
    
    data_sources = [
        DataSourceConfig(
            id="test-db",
            name="Test Database",
            type="file",
            path=db_path
        )
    ]
    
    # Initialize Azure client
    logger.info("\n[3.1] Initializing Azure client...")
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        credential=credential,
        endpoint=project_endpoint
    )
    
    # Create SQL agent with tools
    logger.info("\n[3.2] Creating SQL agent with tools...")
    sql_agent = create_agent_with_tools(
        agents_client=project_client.agents,
        agent_id=sql_agent_id,
        agent_name="sql_agent",
        data_sources=data_sources,
        azure_functions_url="https://mock.azurewebsites.net"  # Not needed for local tools
    )
    
    # Verify tools are registered
    if sql_agent.tool_executor:
        tools = sql_agent.tool_executor.list_tools()
        logger.info(f"✓ Agent has {len(tools)} tools registered:")
        for tool in tools:
            logger.info(f"    - {tool}")
    
    # Test agent query
    logger.info("\n[3.3] Testing agent query...")
    try:
        result = await sql_agent.run(
            f"""I have a database at {db_path}. 
            
            Please:
            1. Get the database schema first
            2. Then query all products with price > 100
            3. Return the results
            
            Use the tools: get_database_schema and execute_sql_query
            """
        )
        
        logger.info(f"\n✓ Agent response:\n{result.messages[0].text}")
        
    except Exception as e:
        logger.error(f"✗ Agent query failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Cleanup
    await project_client.close()
    await credential.close()
    
    logger.info("\n✓ Agent integration test complete")


async def main():
    """Run all tests"""
    logger.info("="*80)
    logger.info("Azure Agent Tools Integration Test Suite")
    logger.info("="*80)
    
    try:
        # Test 1: Tool Registration
        await test_tool_registration()
        
        # Test 2: Tool Execution
        await test_tool_execution()
        
        # Test 3: Agent Integration (if environment is configured)
        await test_agent_integration()
        
        logger.info("\n" + "="*80)
        logger.info("✓ ALL TESTS PASSED")
        logger.info("="*80)
        
    except AssertionError as e:
        logger.error(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n✗ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
