#!/usr/bin/env python3
"""
Verify MCP Agent tools in Azure AI Foundry.
Checks if the agent has the web_search tool registered.
"""
import asyncio
import json
import os
from pathlib import Path

# Load environment
env_path = Path(__file__).parent.parent / ".env.azure"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k] = v


async def verify_mcp_agent():
    from azure.ai.agents.aio import AgentsClient
    from azure.identity.aio import DefaultAzureCredential
    
    # Load config
    config_path = Path(__file__).parent.parent / "azure_agents_config.json"
    with open(config_path) as f:
        config = json.load(f)
    
    mcp_agent_id = config["agents"]["mcp_agent"]["id"]
    endpoint = config.get("project_endpoint") or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    
    print("=" * 60)
    print("MCP Agent Verification")
    print("=" * 60)
    print(f"Agent ID: {mcp_agent_id}")
    print(f"Endpoint: {endpoint}")
    print()
    
    credential = DefaultAzureCredential()
    client = AgentsClient(endpoint=endpoint, credential=credential)
    
    try:
        # Use get_agent (not agents.get)
        agent = await client.get_agent(agent_id=mcp_agent_id)
        
        print(f"Agent Name: {agent.name}")
        print(f"Model: {agent.model}")
        print()
        
        # List tools
        print("Registered Tools:")
        print("-" * 40)
        
        tool_names = []
        if agent.tools:
            for tool in agent.tools:
                if hasattr(tool, 'function'):
                    name = tool.function.name
                    desc = tool.function.description[:60] if tool.function.description else "No description"
                    tool_names.append(name)
                    print(f"  ✓ {name}")
                    print(f"    {desc}...")
                elif hasattr(tool, 'type'):
                    print(f"  - {tool.type}")
        else:
            print("  (No tools registered)")
        
        print()
        
        # Check for expected tools
        expected_tools = ["web_search", "playwright_scrape"]
        missing = [t for t in expected_tools if t not in tool_names]
        
        if missing:
            print("⚠️  MISSING TOOLS:")
            for t in missing:
                print(f"    - {t}")
            print()
            print("Run 'python scripts/create_azure_agents.py' to update agent")
        else:
            print("✅ All expected tools are registered!")
        
        # Show instructions (first 500 chars)
        print()
        print("Instructions Preview:")
        print("-" * 40)
        if agent.instructions:
            print(agent.instructions[:500] + "...")
        else:
            print("(No instructions)")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await client.close()
        await credential.close()


if __name__ == "__main__":
    asyncio.run(verify_mcp_agent())
