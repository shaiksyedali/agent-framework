"""
Update RAG Agent tools and instructions.
Uses Azure AI Foundry AgentsClient (same as create_azure_agents.py).
Imports definitions from create_azure_agents.py (single source of truth).
"""
import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import json

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))
from create_azure_agents import get_rag_tools, get_rag_instructions

# Load environment
env_path = Path(__file__).parent.parent / ".env.azure"
if env_path.exists():
    load_dotenv(env_path)
    print(f"Loaded environment from: {env_path}")

async def update_rag_agent():
    """Update RAG agent using Azure AI Foundry AgentsClient."""
    from azure.ai.agents.aio import AgentsClient
    from azure.identity.aio import DefaultAzureCredential
    
    # Load current config
    config_path = Path(__file__).parent.parent / "azure_agents_config.json"
    with open(config_path) as f:
        config = json.load(f)
    
    rag_agent_id = config["agents"]["rag_agent"]["id"]
    project_endpoint = config.get("project_endpoint")
    
    print(f"Current RAG Agent ID: {rag_agent_id}")
    print(f"Project Endpoint: {project_endpoint}")
    
    # Use AZURE_AI_PROJECT_ENDPOINT from env if not in config
    if not project_endpoint:
        project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    
    if not project_endpoint:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT required")
        return
    
    # Initialize Azure AI Foundry client (same as create_azure_agents.py)
    credential = DefaultAzureCredential()
    
    try:
        agents_client = AgentsClient(
            endpoint=project_endpoint,
            credential=credential
        )
        
        # Get tools and instructions from create_azure_agents.py (single source of truth)
        new_tools = get_rag_tools()
        new_instructions = get_rag_instructions()
        
        print(f"\nUpdating RAG Agent {rag_agent_id}...")
        print(f"  Tools: {[t['function']['name'] for t in new_tools]}")
        
        # Update the agent using update_agent method
        updated = await agents_client.update_agent(
            agent_id=rag_agent_id,
            instructions=new_instructions,
            tools=new_tools
        )
        
        print(f"✓ RAG Agent updated successfully!")
        print(f"  ID: {updated.id}")
        print(f"  Name: {updated.name}")
        tool_names = []
        for t in updated.tools:
            if hasattr(t, 'function') and hasattr(t.function, 'name'):
                tool_names.append(t.function.name)
            elif hasattr(t, 'type'):
                tool_names.append(str(t.type))
        print(f"  Tools: {tool_names}")
        
    except Exception as e:
        print(f"ERROR updating RAG Agent: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await agents_client.close()
        await credential.close()

if __name__ == "__main__":
    asyncio.run(update_rag_agent())
