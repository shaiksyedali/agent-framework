"""Debug script to check entity_codes field in search index."""
import os
import asyncio
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from dotenv import load_dotenv

load_dotenv(".env.azure")

async def check_documents():
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    key = os.getenv("AZURE_SEARCH_KEY") or os.getenv("AZURE_SEARCH_API_KEY")
    index_name = os.getenv("AZURE_SEARCH_INDEX", "schema-docs-v2")
    
    if not endpoint or not key:
        print("Error: Missing AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_KEY")
        return

    print(f"Connecting to {endpoint}...")
    print(f"Index: {index_name}")
    credential = AzureKeyCredential(key)
    
    async with SearchClient(endpoint, index_name, credential) as client:
        # Count total documents - get NEWEST first
        results = await client.search(
            search_text="*",
            top=5,
            order_by=["created_at desc"],  # Get newest documents first
            select=["id", "file_name", "workflow_id", "entity_codes", "entities", "doc_type", "created_at"]
        )
        
        print("\n=== Sample Documents ===")
        count = 0
        async for doc in results:
            count += 1
            print(f"\n--- Document {count} ---")
            print(f"ID: {doc.get('id', 'N/A')}")
            print(f"File: {doc.get('file_name', 'N/A')}")
            print(f"Workflow: {doc.get('workflow_id', 'N/A')}")
            print(f"Doc Type: {doc.get('doc_type', 'N/A')}")
            
            entity_codes = doc.get('entity_codes')
            print(f"Entity Codes: {entity_codes}")
            print(f"Entity Codes Type: {type(entity_codes)}")
            print(f"Entity Codes Length: {len(entity_codes) if entity_codes else 0}")
            
            entities = doc.get('entities', '')
            if entities:
                print(f"Entities (preview): {str(entities)[:300]}...")
        
        print(f"\n=== Total: {count} documents shown ===")
        
        # Now check facets
        print("\n=== Testing Facets ===")
        try:
            facet_results = await client.search(
                search_text="*",
                facets=["entity_codes,count:100"],
                top=0
            )
            facets = await facet_results.get_facets()
            if facets:
                entity_facets = facets.get("entity_codes", [])
                print(f"Entity Codes Facets: {len(entity_facets)} unique values")
                for f in entity_facets[:10]:
                    print(f"  - {f}")
            else:
                print("No facets returned")
        except Exception as e:
            print(f"Facet error: {e}")

if __name__ == "__main__":
    asyncio.run(check_documents())
