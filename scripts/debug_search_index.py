
import os
import asyncio
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes.aio import SearchIndexClient
from dotenv import load_dotenv

load_dotenv(".env.azure")

async def list_indexes():
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    key = os.getenv("AZURE_SEARCH_KEY") or os.getenv("AZURE_SEARCH_API_KEY")
    
    if not endpoint or not key:
        print("Error: Missing AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_KEY")
        return

    print(f"Connecting to {endpoint}...")
    credential = AzureKeyCredential(key)
    client = SearchIndexClient(endpoint=endpoint, credential=credential)
    
    try:
        print("Listing indexes:")
        async for index in client.list_indexes():
            print(f" - {index.name}")
    except Exception as e:
        print(f"Error listing indexes: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(list_indexes())
