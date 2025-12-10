"""
Merge Entities Activity - Durable Activity Function

Merges entities from all chunks into a deduplicated list.
Called after all extraction activities complete.
"""
import logging


def main(input: dict) -> dict:
    """
    Activity function that merges entities from all chunks.
    
    Input:
    {
        "results": [{"entities": [...], "relationships": [...]}, ...],
        "workflow_id": "xxx",
        "file_name": "xxx"
    }
    
    Output:
    {
        "entities": [...],
        "relationships": [...],
        "total_unique_entities": N,
        "total_chunks_processed": M,
        "chunks_with_entities": K
    }
    """
    from shared_code.llm_entity_extraction import merge_entities
    
    results = input.get("results", [])
    workflow_id = input.get("workflow_id", "")
    file_name = input.get("file_name", "")
    
    # Count chunks with entities
    chunks_with_entities = sum(1 for r in results if r.get("entities"))
    
    logging.info(f"Merging entities from {len(results)} chunks, {chunks_with_entities} have entities")
    
    # Merge all entities
    merged = merge_entities(results)
    
    logging.info(f"Merged to {merged.get('total_unique_entities', 0)} unique entities")
    
    return {
        "entities": merged.get("entities", []),
        "relationships": merged.get("relationships", []),
        "total_unique_entities": merged.get("total_unique_entities", 0),
        "total_chunks_processed": len(results),
        "chunks_with_entities": chunks_with_entities,
        "workflow_id": workflow_id,
        "file_name": file_name
    }
