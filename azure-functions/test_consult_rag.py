#!/usr/bin/env python
"""Test consult_rag function directly."""
import asyncio
import os
import sys

# Add shared_code to path
sys.path.insert(0, os.path.dirname(__file__))

async def test():
    from shared_code.rag import consult_rag_tool
    
    # Use the workflow ID from the recent run
    workflow_id = "d3e28c2b-adcd-456f-ae55-fe15862c530d"
    query = "problem statement described in patent"
    
    print(f"Testing consult_rag with workflow_id={workflow_id}")
    print(f"Query: {query}")
    
    result = await consult_rag_tool(
        query=query,
        workflow_id=workflow_id,
        top_k=5,
        search_type="hybrid"
    )
    
    if result.get("success"):
        print(f"SUCCESS: Found {len(result.get('documents', []))} documents")
        for i, doc in enumerate(result.get("documents", [])[:3]):
            print(f"\n--- Document {i+1} ---")
            print(f"Title: {doc.get('title', 'N/A')}")
            print(f"Content preview: {doc.get('content', '')[:200]}...")
    else:
        print(f"FAILED: {result.get('error')}")
        print(f"Full result: {result}")

if __name__ == "__main__":
    asyncio.run(test())
