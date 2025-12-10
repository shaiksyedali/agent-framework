"""
Update Entities Activity - Durable Activity Function

Updates the Azure Search index with extracted entities.
Called after entity extraction and merging complete.
"""
import logging
import os
import asyncio
import uuid


def main(input: dict) -> dict:
    """
    Activity function that updates Azure Search with extracted entities.
    
    Input:
    {
        "workflow_id": "xxx",
        "file_name": "xxx",
        "index_name": "xxx",
        "chunks_with_entities": [{"chunk_id": "x", "page_number": 1, "entities": [...]}],
        "all_entities": [{"name": "...", "type": "..."}]
    }
    """
    return asyncio.run(_update_entities(input))


async def _update_entities(input: dict) -> dict:
    """Async implementation of entity update."""
    from azure.search.documents.aio import SearchClient
    from azure.core.credentials import AzureKeyCredential
    
    workflow_id = input.get("workflow_id", "")
    file_name = input.get("file_name", "")
    index_name = input.get("index_name", "")
    chunks_with_entities = input.get("chunks_with_entities", [])
    all_entities = input.get("all_entities", [])
    
    if not index_name or not workflow_id:
        return {"success": False, "error": "Missing index_name or workflow_id"}
    
    if not chunks_with_entities:
        return {"success": True, "message": "No entities to update", "updated": 0}
    
    # Get search credentials
    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    search_key = os.environ.get("AZURE_SEARCH_KEY")
    
    if not search_endpoint or not search_key:
        return {"success": False, "error": "Search credentials not configured"}
    
    try:
        credential = AzureKeyCredential(search_key)
        
        # Build updates for each chunk
        updates = []
        for chunk_data in chunks_with_entities:
            chunk_id = chunk_data.get("chunk_id")
            page_number = chunk_data.get("page_number", 0)
            entities = chunk_data.get("entities", [])
            
            # Generate the document ID (must match the one used during indexing)
            doc_id = f"{workflow_id}-{file_name}-p{page_number}-c{chunk_id}"
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))
            
            # Extract entity names for entity_codes field (facetable)
            # Include IDENTIFIER and COMPONENT types for facets
            facetable_types = {"IDENTIFIER", "COMPONENT", "ACTOR"}
            entity_codes = [
                e.get("name", "") 
                for e in entities 
                if e.get("type", "").upper() in facetable_types and e.get("name")
            ]
            
            if entity_codes:
                updates.append({
                    "id": doc_id,
                    "@search.action": "merge",
                    "entity_codes": entity_codes
                })
        
        if not updates:
            return {"success": True, "message": "No entity_codes to update", "updated": 0}
        
        # Update documents in batches
        async with SearchClient(search_endpoint, index_name, credential) as client:
            batch_size = 100
            total_updated = 0
            
            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]
                try:
                    result = await client.merge_documents(batch)
                    total_updated += len([r for r in result if r.succeeded])
                except Exception as e:
                    logging.warning(f"Batch update failed: {e}")
        
        logging.info(f"Updated {total_updated} documents with entity_codes")
        
        return {
            "success": True,
            "updated": total_updated,
            "total_entities": len(all_entities),
            "chunks_processed": len(chunks_with_entities)
        }
        
    except Exception as e:
        logging.error(f"Failed to update entities: {e}")
        return {"success": False, "error": str(e)}
