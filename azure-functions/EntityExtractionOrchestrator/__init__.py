"""
Entity Extraction Orchestrator - Durable Orchestrator Function

Coordinates parallel entity extraction from document chunks.
Uses fan-out/fan-in pattern for efficient LLM processing.
"""
import azure.durable_functions as df
import logging


def orchestrator_function(context: df.DurableOrchestrationContext):
    """
    Orchestrator function that coordinates parallel entity extraction.
    
    Input format:
    {
        "chunks": [{"content": "...", "chunk_id": "...", "page_number": 1}, ...],
        "workflow_id": "xxx",
        "file_name": "xxx"
    }
    """
    # Get input
    input_data = context.get_input()
    chunks = input_data.get("chunks", [])
    workflow_id = input_data.get("workflow_id", "")
    file_name = input_data.get("file_name", "")
    
    if not context.is_replaying:
        logging.info(f"Starting entity extraction for {len(chunks)} chunks from {file_name}")
    
    # Fan-out: Create activity tasks for each chunk in batches
    # Reduced batch size to avoid Azure OpenAI rate limits
    batch_size = 5  # Reduced from 10 to avoid rate limiting
    all_results = []
    
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        
        # Create parallel tasks for this batch
        tasks = [
            context.call_activity(
                "ExtractEntitiesActivity",
                {
                    "content": chunk.get("content", ""),
                    "chunk_id": chunk.get("chunk_id", f"chunk_{j}"),
                    "page_number": chunk.get("page_number", 0)
                }
            )
            for j, chunk in enumerate(batch, start=i)
        ]
        
        # Wait for all tasks in this batch to complete
        batch_results = yield context.task_all(tasks)
        all_results.extend(batch_results)
    
    # Fan-in: Merge all results
    merged = yield context.call_activity(
        "MergeEntitiesActivity",
        {
            "results": all_results,
            "workflow_id": workflow_id,
            "file_name": file_name
        }
    )
    
    if not context.is_replaying:
        logging.info(f"Entity extraction complete: {merged.get('total_unique_entities', 0)} unique entities")
    
    # Update Azure Search with extracted entities
    index_name = input_data.get("index_name")
    if merged.get("entities") and index_name:
        chunks_with_entities = []
        
        # Map entities back to chunks
        for i, result in enumerate(all_results):
            if i < len(chunks):
                chunk = chunks[i]
                chunk_entities = result.get("entities", [])
                if chunk_entities:
                    chunks_with_entities.append({
                        "chunk_id": chunk.get("chunk_id"),
                        "page_number": chunk.get("page_number", 0),
                        "entities": chunk_entities
                    })
        
        update_result = yield context.call_activity(
            "UpdateEntitiesActivity",
            {
                "workflow_id": workflow_id,
                "file_name": file_name,
                "index_name": index_name,
                "chunks_with_entities": chunks_with_entities,
                "all_entities": merged.get("entities", [])
            }
        )
        
        if not context.is_replaying:
            logging.info(f"Updated search index with entities: {update_result}")
        
        merged["search_update"] = update_result
    
    return merged


main = df.Orchestrator.create(orchestrator_function)
