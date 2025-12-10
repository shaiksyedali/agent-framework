"""
Update Agent Definitions Script
Updates existing Azure Foundry Agents (Assistants) with correct tool definitions.
Targeting:
- RAG Agent: Add 'consult_rag' function tool.
- Ensure SQL Agent has correct tools.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI

# Import tool definitions from creation script
# We'll just define them here to be safe and explicit
def get_consult_rag_tool():
    return {
        "type": "function",
        "function": {
            "name": "consult_rag",
            "description": "Search schema documentation using RAG agent",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for documentation"
                    }
                },
                "required": ["query"]
            }
        }
    }

def get_sql_tools():
    # Copy from create_azure_agents.py
    return [
        {
            "type": "function",
            "function": {
                "name": "execute_sql_query",
                "description": "Execute SQL query on specified database with approval gate for writes",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SQL query to execute"},
                        "database": {"type": "string", "description": "Database name"},
                        "require_approval": {"type": "boolean", "description": "Whether to require user approval"}
                    },
                    "required": ["query", "database"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_database_schema",
                "description": "Get schema information for a database",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "database": {"type": "string", "description": "Database name"}
                    },
                    "required": ["database"]
                }
            }
        },
        get_consult_rag_tool() 
    ]

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("update_agents")

async def update_agents():
    # 1. Load Config
    config_path = Path("azure_agents_config.json")
    if not config_path.exists():
        logger.error("Configuration file not found.")
        return

    with open(config_path) as f:
        config = json.load(f)
    
    agents = config.get("agents", {})
    
    # 2. Init Client
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

    if api_key:
        client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )
    else:
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
        client = AsyncAzureOpenAI(
            azure_ad_token_provider=token_provider,
            azure_endpoint=endpoint,
            api_version=api_version,
        )

    # 3. Update RAG Agent
    rag_id = agents.get("rag_agent", {}).get("id")
    if rag_id:
        logger.info(f"Updating RAG Agent ({rag_id})...")
        try:
            # We add consult_rag AND keep file_search
            await client.beta.assistants.update(
                assistant_id=rag_id,
                tools=[
                    {"type": "file_search"},
                    get_consult_rag_tool()
                ]
            )
            logger.info("✓ RAG Agent updated with 'consult_rag' tool.")
        except Exception as e:
            logger.error(f"Failed to update RAG agent: {e}")
    else:
        logger.warning("RAG Agent ID not found in config.")

    # 4. Update SQL Agent (Just in case)
    sql_id = agents.get("sql_agent", {}).get("id")
    if sql_id:
        logger.info(f"Updating SQL Agent ({sql_id})...")
        try:
            await client.beta.assistants.update(
                assistant_id=sql_id,
                tools=get_sql_tools()
            )
            logger.info("✓ SQL Agent updated.")
        except Exception as e:
            logger.error(f"Failed to update SQL agent: {e}")

    await client.close()

if __name__ == "__main__":
    load_env = Path(".env.azure")
    if load_env.exists():
        with open(load_env) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v
                    
    asyncio.run(update_agents())
