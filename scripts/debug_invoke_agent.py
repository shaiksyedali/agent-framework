
import asyncio
import os
import json
import logging
import sys
from pathlib import Path

# Mock Azure Functions HttpRequest
class MockRequest:
    def __init__(self, body):
        self._body = body
    def get_json(self):
        return self._body

# Setup logging
logging.basicConfig(level=logging.INFO)

async def main():
    print("Testing invoke_agent logic locally...")
    
    # 1. Imports check
    try:
        print("Attempting imports...")
        from azure.ai.agents.aio import AgentsClient
        from azure.identity.aio import DefaultAzureCredential
        from azure.core.credentials import AccessToken
        from azure.core.credentials_async import AsyncTokenCredential
        print("Imports successful.")
    except ImportError as e:
        print(f"Import failed: {e}")
        return

    # 2. Config check
    config_path = Path("azure-functions/azure_agents_config.json").absolute()
    print(f"Looking for config at: {config_path}")
    if not config_path.exists():
        print("Config not found!")
        return
    
    with open(config_path, "r") as f:
        config = json.load(f)
        print("Config loaded.")

    # 3. Auth check
    # TRYING OPENAI ENDPOINT to see if API Key works
    project_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    print(f"Testing with OpenAI Endpoint: {project_endpoint}")
    
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    print(f"API Key present: {bool(api_key)}")

    # Wrapper for API Key authentication (copied from function)
    class APIKeyTokenCredential(AsyncTokenCredential):
        def __init__(self, api_key: str):
            self._api_key = api_key
        async def get_token(self, *scopes, **kwargs):
            return AccessToken(token=self._api_key, expires_on=9999999999)
        async def close(self): pass

    if api_key:
        credential = APIKeyTokenCredential(api_key)
    else:
        credential = DefaultAzureCredential()

    # 4. Client creation check
    print("Creating AsyncAzureOpenAI Client...")
    try:
        from openai import AsyncAzureOpenAI
        
        client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
            azure_endpoint=project_endpoint
        )
        
        print("Client created successfully.")
        
        print("Listing assistants...")
        assistants = await client.beta.assistants.list()
        print(f"Found {len(assistants.data)} assistants.")
        for a in assistants.data:
            print(f" - {a.name} ({a.id})")
        
        print("Creating thread...")
        thread = await client.beta.threads.create()
        print(f"Thread created: {thread.id}")
            
    except Exception as e:
        print(f"Client creation/usage failed: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"Client creation/usage failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Ensure env vars are loaded? 
    # Use dotenv to load .env.azure
    from dotenv import load_dotenv
    load_dotenv(".env.azure")
    
    asyncio.run(main())
