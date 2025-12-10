"""
Azure Function: consult_rag
Uses shared_code.rag for logic.
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
    
    func_root = os.path.dirname(os.path.dirname(__file__))
    if func_root not in sys.path:
        sys.path.append(func_root)

    logging.info('RAG Function triggered')
    
    try:
        from shared_code import rag

        req_body = req.get_json()
        query = req_body.get('query')
        index = req_body.get('index')
        top_k = req_body.get('top_k', 10)
        search_type = req_body.get('search_type', 'hybrid')
        workflow_id = req_body.get('workflow_id')
        enable_rerank = req_body.get('enable_rerank', False)
        pipeline = req_body.get('pipeline', 'advanced')  # Default: full pipeline with expansion + reranking

        if not query:
            return func.HttpResponse(json.dumps({"error": "Query required"}), status_code=400)

        # Choose RAG pipeline
        if pipeline == 'facets':
            # Facet query for aggregation (count unique entity codes)
            result = await rag.get_entity_facets(
                index_name=index,
                field_name=req_body.get('facet_field', 'entity_codes'),
                max_facets=req_body.get('max_facets', 1000),
                workflow_id=workflow_id
            )
        elif pipeline == 'advanced':
            # Full industry-standard pipeline with query expansion + reranking
            result = await rag.advanced_rag_retrieve(
                query=query,
                index_name=index,
                top_k=top_k,
                workflow_id=workflow_id,
                enable_query_expansion=True,
                enable_rerank=True
            )
        elif enable_rerank:
            # Standard with reranking only
            result = await rag.consult_rag_with_rerank(
                query, index, top_k, search_type, workflow_id, enable_rerank=True
            )
        else:
            # Standard hybrid retrieval
            result = await rag.consult_rag_tool(query, index, top_k, search_type, workflow_id)
        
        status = 200 if result.get("success") else 500
        return func.HttpResponse(
            json.dumps(result),
            mimetype="application/json",
            status_code=status
        )

    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500)

