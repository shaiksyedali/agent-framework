"""
Azure Function: get_document_summary
Retrieves pre-computed document summary and metadata from Azure AI Search.
"""
import azure.functions as func
import logging
import json
import os
import sys

async def main(req: func.HttpRequest) -> func.HttpResponse:
    # Path Setup
    site_packages = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.python_packages', 'lib', 'site-packages')
    if site_packages not in sys.path:
        sys.path.append(site_packages)
    
    logging.info('Get Document Summary Function triggered')
    
    try:
        from azure.search.documents.aio import SearchClient
        from azure.core.credentials import AzureKeyCredential
        
        req_body = req.get_json()
        workflow_id = req_body.get('workflow_id')
        file_name = req_body.get('file_name')  # Optional: filter by specific file
        include_entities = req_body.get('include_entities', True)
        include_keywords = req_body.get('include_keywords', True)
        include_relationships = req_body.get('include_relationships', True)  # NEW

        if not workflow_id:
            return func.HttpResponse(
                json.dumps({"error": "workflow_id is required", "success": False}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Config
        search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
        search_key = os.environ.get("AZURE_SEARCH_KEY") or os.environ.get("AZURE_SEARCH_API_KEY")
        index_name = os.environ.get("AZURE_SEARCH_INDEX", "schema-docs")
        
        if not search_endpoint or not search_key:
            return func.HttpResponse(
                json.dumps({"error": "Search configuration missing", "success": False}),
                status_code=500,
                mimetype="application/json"
            )
        
        credential = AzureKeyCredential(search_key)
        async with SearchClient(search_endpoint, index_name, credential) as client:
            
            # Build filter for document summaries
            filter_str = f"workflow_id eq '{workflow_id}' and doc_type eq 'document_summary'"
            if file_name:
                filter_str += f" and file_name eq '{file_name}'"
            
            # Search for document summaries - include new graph fields
            results = await client.search(
                search_text="*",
                filter=filter_str,
                select=["id", "file_name", "executive_summary", "key_findings", 
                        "table_of_contents", "total_chunks", "entities", "keywords", 
                        "relationships", "entity_stats", "created_at"],  # Added graph fields
                top=100
            )
            
            summaries = []
            async for doc in results:
                summary = {
                    "file_name": doc.get("file_name"),
                    "executive_summary": doc.get("executive_summary", ""),
                    "key_findings": json.loads(doc.get("key_findings", "[]")) if doc.get("key_findings") else [],
                    "table_of_contents": json.loads(doc.get("table_of_contents", "[]")) if doc.get("table_of_contents") else [],
                    "total_chunks": doc.get("total_chunks", 0),
                    "created_at": doc.get("created_at")
                }
                
                # GraphRAG: Parse and include entity data with types
                if include_entities:
                    entities_str = doc.get("entities", "[]")
                    try:
                        summary["entities"] = json.loads(entities_str) if entities_str else []
                    except:
                        summary["entities"] = []
                
                if include_keywords:
                    keywords_str = doc.get("keywords", "[]")
                    try:
                        summary["keywords"] = json.loads(keywords_str) if keywords_str else []
                    except:
                        summary["keywords"] = []
                
                # NEW: Include relationships and stats
                if include_relationships:
                    relationships_str = doc.get("relationships", "[]")
                    try:
                        summary["relationships"] = json.loads(relationships_str) if relationships_str else []
                    except:
                        summary["relationships"] = []
                    
                    stats_str = doc.get("entity_stats", "{}")
                    try:
                        summary["entity_stats"] = json.loads(stats_str) if stats_str else {}
                    except:
                        summary["entity_stats"] = {}
                
                summaries.append(summary)
            
            # If single file requested, return just that summary
            if file_name and len(summaries) == 1:
                return func.HttpResponse(
                    json.dumps({
                        "success": True,
                        "summary": summaries[0]
                    }),
                    mimetype="application/json",
                    status_code=200
                )
            
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "workflow_id": workflow_id,
                    "document_count": len(summaries),
                    "summaries": summaries
                }),
                mimetype="application/json",
                status_code=200
            )

    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": str(e), "success": False}),
            status_code=500,
            mimetype="application/json"
        )
