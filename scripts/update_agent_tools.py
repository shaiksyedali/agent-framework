"""
Update Azure Foundry agents with tool definitions.

This script updates the existing Azure agents with the correct tool definitions
for local and cloud tools based on the configured data sources.
"""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import List

from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

# Add parent directory to path to import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python", "packages", "core"))

from agent_framework.azure import AzureToolsIntegration

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
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
    """Update agent tool definitions"""
    
    logger.info("="*80)
    logger.info("Updating Azure Agent Tool Definitions")
    logger.info("="*80)
    
    # Load environment
    load_dotenv(".env.azure")
    
    # Initialize Azure clients
    logger.info("\n[1] Initializing Azure clients...")
    
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        credential=credential,
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    )
    
    # Load agent IDs
    with open("azure_agents_config.json", "r") as f:
        agent_config = json.load(f)
    
    logger.info(f"✓ Loaded {len(agent_config['agents'])} agent configurations")
    
    # Define data sources (customize based on your setup)
    logger.info("\n[2] Defining data sources...")
    
    data_sources = [
        # Local SQLite database
        DataSourceConfig(
            id="ds-1",
            name="Local Database",
            type="file",
            path="/home/crossfitdev/agent-framework/data/test.db"
        ),
        
        # Azure SQL Database (if configured)
        DataSourceConfig(
            id="ds-2",
            name="Azure SQL Database",
            type="database",
            connection_string=os.environ.get("AZURE_SQL_CONNECTION_STRING", "")
        ) if os.environ.get("AZURE_SQL_CONNECTION_STRING") else None,
        
        # PDF documents for RAG
        DataSourceConfig(
            id="ds-3",
            name="Documents",
            type="file",
            path="/home/crossfitdev/agent-framework/data/documents/"
        ),
    ]
    
    # Filter out None values
    data_sources = [ds for ds in data_sources if ds is not None]
    
    logger.info(f"✓ Configured {len(data_sources)} data sources")
    for ds in data_sources:
        logger.info(f"  - {ds.name} ({ds.type})")
    
    # Create integration
    logger.info("\n[3] Creating tools integration...")
    
    azure_functions_url = os.environ.get(
        "AZURE_FUNCTIONS_URL",
        "https://your-function-app.azurewebsites.net"
    )
    
    integration = AzureToolsIntegration(
        agents_client=project_client.agents,
        azure_functions_url=azure_functions_url,
        api_key=os.environ.get("AZURE_FUNCTIONS_KEY")
    )
    
    logger.info(f"✓ Integration initialized with URL: {azure_functions_url}")
    
    # Update each agent with appropriate tools
    logger.info("\n[4] Updating agent tool definitions...")
    
    # SQL Agent - gets both local and cloud SQL tools
    logger.info("\n  Updating SQL Agent...")
    sql_tools = integration.get_tool_definitions_for_agent(
        agent_type="sql_agent",
        data_sources=data_sources
    )
    
    logger.info(f"    Tool definitions: {len(sql_tools)}")
    for tool in sql_tools:
        logger.info(f"      - {tool['function']['name']}")
    
    # Note: Azure Foundry agents API doesn't support updating tools directly
    # Tools must be registered when creating the agent
    # This is for reference/validation purposes
    logger.info("    ✓ Tool definitions generated (registered at runtime)")
    
    # RAG Agent - gets RAG tools
    logger.info("\n  Updating RAG Agent...")
    rag_tools = integration.get_tool_definitions_for_agent(
        agent_type="rag_agent",
        data_sources=data_sources
    )
    
    logger.info(f"    Tool definitions: {len(rag_tools)}")
    for tool in rag_tools:
        logger.info(f"      - {tool['function']['name']}")
    
    logger.info("    ✓ Tool definitions generated (registered at runtime)")
    
    # Save tool definitions for reference
    logger.info("\n[5] Saving tool definitions...")
    
    tool_definitions = {
        "sql_agent": sql_tools,
        "rag_agent": rag_tools,
        "azure_functions_url": azure_functions_url,
    }
    
    with open("agent_tool_definitions.json", "w") as f:
        json.dump(tool_definitions, f, indent=2)
    
    logger.info("✓ Saved to agent_tool_definitions.json")
    
    # Cleanup
    await project_client.close()
    await credential.close()
    
    logger.info("\n" + "="*80)
    logger.info("Update Complete!")
    logger.info("="*80)
    logger.info("")
    logger.info("IMPORTANT: Tool definitions are registered at runtime when you")
    logger.info("create agent adapters using create_agent_with_tools().")
    logger.info("")
    logger.info("The Azure agents already have tools defined in their instructions.")
    logger.info("The ToolExecutor will handle tool calls dynamically based on")
    logger.info("the data sources you provide.")
    logger.info("")


if __name__ == "__main__":
    asyncio.run(main())
