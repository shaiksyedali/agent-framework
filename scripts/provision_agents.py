
import asyncio
import os
import json
import sys
from pathlib import Path
from openai import AsyncAzureOpenAI
from dotenv import load_dotenv

# Load env vars
load_dotenv(".env.azure")

# Import tool and instruction definitions from the original script
# We add the current directory to sys.path to find the module
sys.path.append(os.path.dirname(__file__))
try:
    from create_azure_agents import (
        get_supervisor_tools, get_supervisor_instructions,
        get_planner_tools, get_planner_instructions,
        get_executor_tools, get_executor_instructions,
        get_sql_tools, get_sql_instructions,
        get_rag_instructions, # RAG instructions (tools are just file_search)
        get_response_generator_tools, get_response_generator_instructions
    )
except ImportError:
    print("Could not import tool definitions. Make sure create_azure_agents.py is in the same directory.")
    sys.exit(1)

AGENTS_DEF = {
    "supervisor_agent": {
        "name": "Supervisor Agent",
        "instructions_getter": get_supervisor_instructions,
        "model": "gpt-4o",
        "tools_getter": get_supervisor_tools
    },
    "planner_agent": {
        "name": "Planner Agent",
        "instructions_getter": get_planner_instructions,
        "model": "gpt-4o",
        "tools_getter": get_planner_tools
    },
    "executor_agent": {
        "name": "Executor Agent",
        "instructions_getter": get_executor_instructions,
        "model": "gpt-4o",
        "tools_getter": get_executor_tools
    },
    "sql_agent": {
        "name": "SQL Agent",
        "instructions_getter": get_sql_instructions,
        "model": "gpt-4o",
        "tools_getter": get_sql_tools
    },
    "rag_agent": {
        "name": "RAG Agent",
        "instructions_getter": get_rag_instructions,
        "model": "gpt-4o",
        "tools_getter": None, # Special case for file_search
        "extra_tools": [{"type": "file_search"}]
    },
    "response_generator": {
        "name": "Response Generator",
        "instructions_getter": get_response_generator_instructions,
        "model": "gpt-4o",
        "tools_getter": get_response_generator_tools
    }
}

async def provision_agents():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
    
    if not endpoint or not api_key:
        print("Missing AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY")
        return

    client = AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version
    )

    print(f"Provisioning agents on {endpoint}...")
    
    new_config = {"agents": {}}
    
    for agent_key, defs in AGENTS_DEF.items():
        print(f"Creating {defs['name']}...")
        
        # Prepare tools
        tools = []
        if "tools_getter" in defs and defs["tools_getter"]:
            tools.extend(defs["tools_getter"]())
        if "extra_tools" in defs:
            tools.extend(defs["extra_tools"])
            
        kwargs = {
            "name": defs["name"],
            "instructions": defs["instructions_getter"](),
            "model": defs["model"],
            "tools": tools
        }
        
        if "response_format" in defs:
            kwargs["response_format"] = defs["response_format"]

        try:
            assistant = await client.beta.assistants.create(**kwargs)
            print(f" - Created ID: {assistant.id}")
            print(f" - Attached {len(tools)} tools.")
            
            new_config["agents"][agent_key] = {
                "name": agent_key, 
                "id": assistant.id,
                "description": kwargs["instructions"][:100] + "..."
            }
        except Exception as e:
            print(f"Failed to create {agent_key}: {e}")

    # Update config file
    config_path = Path("azure-functions/azure_agents_config.json")
    
    # Read existing to preserve other fields if any
    if config_path.exists():
        with open(config_path, "r") as f:
            existing = json.load(f)
            existing["agents"] = new_config["agents"] # Overwrite agents
            final_config = existing
    else:
        final_config = new_config
        
    with open(config_path, "w") as f:
        json.dump(final_config, f, indent=2)
        
    print(f"Updated {config_path}")

if __name__ == "__main__":
    asyncio.run(provision_agents())
