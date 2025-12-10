
import asyncio
import os
from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential

async def inspect():
    try:
        credential = DefaultAzureCredential()
        # We need a dummy endpoint or the real one if env var is set
        endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "https://example.com")
        client = AgentsClient(endpoint=endpoint, credential=credential)
        
        print(f"AgentsClient attributes: {dir(client)}")
        
        if hasattr(client, 'runs'):
            print(f"\nRunsOperations attributes: {dir(client.runs)}")
        else:
            print("\nClient has no 'runs' attribute")
            
        await client.close()
        await credential.close()

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(inspect())
