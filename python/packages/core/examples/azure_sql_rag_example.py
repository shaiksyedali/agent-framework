"""
Complete example demonstrating Azure tools integration with local and cloud tools.

This example shows:
1. Setting up Azure Foundry agents with tools
2. Using local SQL tools (.db files)
3. Using cloud SQL tools (Azure SQL)
4. Using cloud RAG tools (Azure AI Search)
5. Running a multi-agent workflow
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import List

from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

# Import from our framework
from agent_framework.azure import create_multi_agent_system
from agent_framework_azure_ai import AzureFoundrySettings

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
    type: str  # "file", "database", "mcp_server"
    path: str = None
    connection_string: str = None
    url: str = None


async def main():
    """Main example function"""
    
    # Load environment variables
    load_dotenv(".env.azure")
    
    logger.info("=" * 80)
    logger.info("Azure SQL + RAG Multi-Agent Example")
    logger.info("=" * 80)
    
    # ====================================================================================
    # STEP 1: Initialize Azure clients
    # ====================================================================================
    
    logger.info("\n[STEP 1] Initializing Azure clients...")
    
    credential = DefaultAzureCredential()
    
    project_client = AIProjectClient(
        credential=credential,
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    )
    
    # Load agent IDs from config
    with open("azure_agents_config.json", "r") as f:
        agent_config = json.load(f)
    
    logger.info(f"✓ Azure clients initialized")
    logger.info(f"✓ Loaded {len(agent_config['agents'])} agent configurations")
    
    # ====================================================================================
    # STEP 2: Define data sources
    # ====================================================================================
    
    logger.info("\n[STEP 2] Defining data sources...")
    
    data_sources = [
        # Local SQLite database
        DataSourceConfig(
            id="ds-1",
            name="Local Sales DB",
            type="file",
            path="/home/crossfitdev/agent-framework/data/sales.db"
        ),
        
        # Azure SQL Database (cloud)
        DataSourceConfig(
            id="ds-2",
            name="Azure Production DB",
            type="database",
            connection_string=os.environ.get("AZURE_SQL_CONNECTION_STRING", "")
        ),
        
        # PDF documents for RAG
        DataSourceConfig(
            id="ds-3",
            name="Product Manuals",
            type="file",
            path="/home/crossfitdev/agent-framework/data/manual.pdf"
        ),
    ]
    
    logger.info(f"✓ Defined {len(data_sources)} data sources:")
    for ds in data_sources:
        logger.info(f"  - {ds.name} ({ds.type})")
    
    # ====================================================================================
    # STEP 3: Create multi-agent system with tools
    # ====================================================================================
    
    logger.info("\n[STEP 3] Creating multi-agent system with tools...")
    
    azure_functions_url = os.environ.get(
        "AZURE_FUNCTIONS_URL",
        "https://your-function-app.azurewebsites.net"
    )
    
    # Prepare agent configs
    agent_configs = {
        "supervisor": {
            "id": agent_config["agents"]["supervisor"]["id"],
            "description": "Supervisor agent - coordinates workflow"
        },
        "sql_agent": {
            "id": agent_config["agents"]["sql_agent"]["id"],
            "description": "SQL agent - executes database queries"
        },
        "rag_agent": {
            "id": agent_config["agents"]["rag_agent"]["id"],
            "description": "RAG agent - searches documents"
        },
        "response_generator": {
            "id": agent_config["agents"]["response_generator"]["id"],
            "description": "Response generator - formats final output"
        },
    }
    
    # Create all agents with appropriate tools
    agents = create_multi_agent_system(
        agents_client=project_client.agents,
        agent_configs=agent_configs,
        data_sources=data_sources,
        azure_functions_url=azure_functions_url,
    )
    
    logger.info(f"✓ Created {len(agents)} agents with tools")
    for name, agent in agents.items():
        tools = agent.tool_executor.list_tools() if agent.tool_executor else []
        logger.info(f"  - {name}: {len(tools)} tools")
        for tool in tools:
            logger.info(f"    • {tool}")
    
    # ====================================================================================
    # STEP 4: Example 1 - Local SQL Query
    # ====================================================================================
    
    logger.info("\n" + "=" * 80)
    logger.info("[EXAMPLE 1] Local SQL Query")
    logger.info("=" * 80)
    
    try:
        sql_agent = agents["sql_agent"]
        
        logger.info("\n📊 Querying local sales database...")
        
        result = await sql_agent.run(
            "What are the top 5 customers by total sales? Use the local database."
        )
        
        logger.info(f"\n✓ Result:\n{result.messages[0].text}")
        
    except Exception as e:
        logger.error(f"❌ Example 1 failed: {e}", exc_info=True)
    
    # ====================================================================================
    # STEP 5: Example 2 - RAG Document Search
    # ====================================================================================
    
    logger.info("\n" + "=" * 80)
    logger.info("[EXAMPLE 2] RAG Document Search")
    logger.info("=" * 80)
    
    try:
        rag_agent = agents["rag_agent"]
        
        logger.info("\n📄 Searching product manuals...")
        
        result = await rag_agent.run(
            "What is the voltage range of the PI10 product? Search the manuals."
        )
        
        logger.info(f"\n✓ Result:\n{result.messages[0].text}")
        
    except Exception as e:
        logger.error(f"❌ Example 2 failed: {e}", exc_info=True)
    
    # ====================================================================================
    # STEP 6: Example 3 - Hybrid Query (Local SQL + RAG)
    # ====================================================================================
    
    logger.info("\n" + "=" * 80)
    logger.info("[EXAMPLE 3] Hybrid Query (SQL + RAG)")
    logger.info("=" * 80)
    
    try:
        supervisor = agents["supervisor"]
        
        logger.info("\n🎯 Running hybrid workflow...")
        
        result = await supervisor.run(
            """Analyze the following:
            1. Get the list of products from the local sales database
            2. For each product, search the manuals for technical specifications
            3. Generate a summary report combining sales data and technical specs
            
            Please coordinate between the SQL agent and RAG agent to complete this task.
            """
        )
        
        logger.info(f"\n✓ Result:\n{result.messages[0].text}")
        
    except Exception as e:
        logger.error(f"❌ Example 3 failed: {e}", exc_info=True)
    
    # ====================================================================================
    # STEP 7: Cleanup
    # ====================================================================================
    
    logger.info("\n[CLEANUP] Closing connections...")
    
    await project_client.close()
    await credential.close()
    
    logger.info("✓ All connections closed")
    logger.info("\n" + "=" * 80)
    logger.info("Example complete!")
    logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
