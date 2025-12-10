
import json
import logging
import os
import asyncio
from azure.core.credentials import AzureKeyCredential

async def generate_embedding(text: str) -> list[float]:
    """
    Generate embedding for text using Azure OpenAI.
    """
    try:
        from openai import AsyncAzureOpenAI
        
        client = AsyncAzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
        )

        response = await client.embeddings.create(
            input=text,
            model=os.environ.get("AZURE_EMBED_DEPLOYMENT", "text-embedding-3-small"),
            dimensions=int(os.environ.get("AZURE_EMBED_DIM", "1536"))
        )

        return response.data[0].embedding

    except Exception as e:
        logging.error(f"Error generating embedding: {str(e)}")
        raise

async def consult_rag_tool(query: str, index_name: str = None, top_k: int = 100, search_type: str = "hybrid", workflow_id: str = None) -> dict:
    """
    Enhanced RAG retrieval with hybrid search (vector + keyword + semantic).
    
    Industry best practices implemented:
    - Hybrid retrieval: Combines vector similarity with keyword matching
    - Semantic ranking: Uses Azure's semantic ranker for relevance
    - Semantic captions: AI-generated answer snippets
    - Rich metadata: Includes chunk summaries, entities, and relationships
    
    Args:
        query: Search query
        index_name: Target index name
        top_k: Number of results to return
        search_type: 'vector', 'keyword', 'hybrid', or 'semantic'
        workflow_id: Optional workflow ID for filtering documents
    """
    try:
        from azure.search.documents.aio import SearchClient
        from azure.search.documents.models import VectorizedQuery, QueryType, QueryCaptionType, QueryAnswerType
        from azure.identity.aio import DefaultAzureCredential
        
        # Defaults
        if not index_name:
            index_name = os.environ.get('AZURE_SEARCH_INDEX', 'schema-docs')

        search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
        if not search_endpoint:
            return {"success": False, "error": "AZURE_SEARCH_ENDPOINT not set"}

        # Authenticate
        search_key = os.environ.get("AZURE_SEARCH_KEY") or os.environ.get("AZURE_SEARCH_API_KEY")
        if search_key:
            credential = AzureKeyCredential(search_key)
        else:
            credential = DefaultAzureCredential()

        async with SearchClient(search_endpoint, index_name, credential) as search_client:
            
            # Build vector query for vector/hybrid search
            vector_query = None
            if search_type in ["vector", "hybrid"]:
                query_vector = await generate_embedding(query)
                vector_query = VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=50,  # Retrieve more for better fusion
                    fields="content_vector"
                )

            # Build search parameters based on search type
            kwargs = {
                "top": top_k,
                "select": [
                    "id", "title", "content", "source", "page_number", "chunk_id",
                    "chunk_summary", "entities", "keywords", "category",
                    "executive_summary", "key_findings", "doc_type",
                    "relationships", "entity_stats"
                ],
            }
            
            # Add workflow filter if provided
            if workflow_id:
                kwargs["filter"] = f"workflow_id eq '{workflow_id}'"
                logging.info(f"Filtering RAG search to workflow: {workflow_id}")
            
            # Configure search based on type
            if search_type == "vector":
                # Pure vector search
                kwargs["vector_queries"] = [vector_query]
                kwargs["search_text"] = None
            elif search_type == "keyword":
                # Pure keyword/BM25 search
                kwargs["search_text"] = query
            elif search_type in ["hybrid", "semantic"]:
                # Hybrid: Vector + Keyword + Semantic ranking
                kwargs["search_text"] = query
                if vector_query:
                    kwargs["vector_queries"] = [vector_query]
                
                # Enable semantic ranking for better relevance
                semantic_config = os.environ.get("SEMANTIC_CONFIG_NAME", "default")
                kwargs["query_type"] = QueryType.SEMANTIC
                kwargs["semantic_configuration_name"] = semantic_config
                
                # Enable semantic captions for AI-generated answer snippets
                kwargs["query_caption"] = QueryCaptionType.EXTRACTIVE
                kwargs["query_answer"] = QueryAnswerType.EXTRACTIVE
                
                logging.info(f"Using hybrid search with semantic config: {semantic_config}")

            results = await search_client.search(**kwargs)
            
            # Process results with rich metadata
            documents = []
            semantic_answers = []
            
            # Extract semantic answers if available
            if hasattr(results, 'get_answers'):
                try:
                    answers = await results.get_answers()
                    if answers:
                        for answer in answers:
                            semantic_answers.append({
                                "text": answer.text,
                                "highlights": answer.highlights,
                                "score": answer.score
                            })
                except Exception as e:
                    logging.warning(f"Could not get semantic answers: {e}")
            
            async for result in results:
                doc = {
                    "id": result.get("id"),
                    "title": result.get("title"),
                    "content": result.get("content", "")[:2000],  # Limit content size
                    "doc_type": result.get("doc_type", "chunk"),
                    "score": result.get("@search.score"),
                    "reranker_score": result.get("@search.reranker_score"),
                    "metadata": {
                        "source": result.get("source"),
                        "page": result.get("page_number"),
                        "chunk_id": result.get("chunk_id"),
                        "category": result.get("category")
                    }
                }
                
                # Add pre-computed summary if available
                if result.get("chunk_summary"):
                    doc["summary"] = result.get("chunk_summary")
                
                # Add executive summary for document summaries
                if result.get("executive_summary"):
                    doc["executive_summary"] = result.get("executive_summary")
                    doc["key_findings"] = result.get("key_findings")
                
                # Add entities and relationships for graph context
                if result.get("entities"):
                    try:
                        doc["entities"] = json.loads(result.get("entities")) if isinstance(result.get("entities"), str) else result.get("entities")
                    except:
                        doc["entities"] = result.get("entities")
                
                if result.get("relationships"):
                    try:
                        doc["relationships"] = json.loads(result.get("relationships")) if isinstance(result.get("relationships"), str) else result.get("relationships")
                    except:
                        pass
                
                if result.get("entity_stats"):
                    try:
                        doc["entity_stats"] = json.loads(result.get("entity_stats")) if isinstance(result.get("entity_stats"), str) else result.get("entity_stats")
                    except:
                        pass
                
                # Add semantic captions if available (must convert to serializable format)
                try:
                    if hasattr(result, 'captions') and result.captions:
                        doc["captions"] = [
                            {
                                "text": str(c.text) if hasattr(c, 'text') else str(c),
                                "highlights": str(c.highlights) if hasattr(c, 'highlights') else ""
                            } 
                            for c in result.captions
                        ]
                    elif "@search.captions" in result:
                        captions = result.get("@search.captions")
                        if captions:
                            doc["captions"] = [
                                {
                                    "text": str(c.text) if hasattr(c, 'text') else str(c),
                                    "highlights": str(c.highlights) if hasattr(c, 'highlights') else ""
                                }
                                for c in captions
                            ] if hasattr(captions, '__iter__') else []
                except Exception as cap_err:
                    logging.warning(f"Error processing captions: {cap_err}")
                
                documents.append(doc)
            
            return {
                "success": True,
                "search_type": search_type,
                "documents": documents,
                "count": len(documents),
                "semantic_answers": semantic_answers if semantic_answers else None
            }

    except Exception as e:
        logging.error(f"RAG Error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def get_entity_facets(
    index_name: str = None,
    field_name: str = "entity_codes",
    max_facets: int = 1000,
    workflow_id: str = None
) -> dict:
    """
    Get all unique entity values using Azure AI Search facets.
    
    This enables aggregation queries like "how many unique DTC codes" 
    without retrieving all documents. Facets are computed server-side
    and return counts for each unique value.
    
    Args:
        index_name: Target index name
        field_name: Facetable field to aggregate
        max_facets: Maximum number of unique values to return
        workflow_id: Optional workflow filter
    
    Returns:
        Dict with unique values and counts
    """
    try:
        from azure.search.documents.aio import SearchClient
        from azure.core.credentials import AzureKeyCredential
        
        if not index_name:
            index_name = os.environ.get('AZURE_SEARCH_INDEX', 'schema-docs')
        
        search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
        search_key = os.environ.get("AZURE_SEARCH_KEY") or os.environ.get("AZURE_SEARCH_API_KEY")
        
        if not search_endpoint or not search_key:
            return {"success": False, "error": "Azure Search credentials not configured"}
        
        credential = AzureKeyCredential(search_key)
        
        async with SearchClient(search_endpoint, index_name, credential) as search_client:
            # Build filter if workflow_id specified
            filter_expr = f"workflow_id eq '{workflow_id}'" if workflow_id else None
            
            # Execute facet query - this returns ALL unique values with counts
            results = await search_client.search(
                search_text="*",  # Match all documents
                facets=[f"{field_name},count:{max_facets}"],
                filter=filter_expr,
                top=0  # We only need facets, not documents
            )
            
            # Extract facet results
            facet_results = []
            if hasattr(results, 'get_facets'):
                facets = await results.get_facets()
                if facets and field_name in facets:
                    for facet in facets[field_name]:
                        facet_results.append({
                            "value": facet.get("value", ""),
                            "count": facet.get("count", 0)
                        })
            
            # Sort by count descending
            facet_results.sort(key=lambda x: x["count"], reverse=True)
            
            return {
                "success": True,
                "field": field_name,
                "total_unique": len(facet_results),
                "facets": facet_results,
                "workflow_id": workflow_id
            }
    
    except Exception as e:
        logging.error(f"Facet query error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def consult_rag_with_rerank(
    query: str, 
    index_name: str = None, 
    top_k: int = 100, 
    search_type: str = "hybrid", 
    workflow_id: str = None,
    enable_rerank: bool = True
) -> dict:
    """
    Enhanced RAG retrieval with optional LLM-based reranking.
    
    This implements the full RAG pipeline:
    1. Hybrid retrieval (vector + keyword + semantic)
    2. LLM-based reranking for precision
    
    Args:
        query: Search query
        index_name: Target index name
        top_k: Number of results to return after reranking
        search_type: 'vector', 'keyword', 'hybrid', or 'semantic'
        workflow_id: Optional workflow ID for filtering
        enable_rerank: Whether to apply LLM reranking (default: True)
    """
    # First, retrieve more documents than needed (for reranking pool)
    retrieve_k = top_k * 3 if enable_rerank else top_k
    
    result = await consult_rag_tool(
        query=query,
        index_name=index_name,
        top_k=retrieve_k,
        search_type=search_type,
        workflow_id=workflow_id
    )
    
    if not result.get("success") or not result.get("documents"):
        return result
    
    documents = result["documents"]
    
    # Apply reranking if enabled and we have enough documents
    if enable_rerank and len(documents) > 3:
        try:
            from shared_code.reranker import rerank_documents
            documents = await rerank_documents(query, documents, top_k)
            result["reranked"] = True
            logging.info(f"Reranked {result['count']} documents to {len(documents)}")
        except Exception as e:
            logging.warning(f"Reranking failed, using original order: {e}")
            documents = documents[:top_k]
            result["reranked"] = False
    else:
        documents = documents[:top_k]
        result["reranked"] = False
    
    result["documents"] = documents
    result["count"] = len(documents)
    
    return result


async def advanced_rag_retrieve(
    query: str,
    index_name: str = None,
    top_k: int = 100,
    workflow_id: str = None,
    enable_query_expansion: bool = True,
    enable_rerank: bool = True,
    enable_hyde: bool = True  # NEW: HyDE for better semantic matching
) -> dict:
    """
    Full industry-standard RAG pipeline with all enhancements.
    
    Pipeline:
    1. Query expansion (generate alternative queries)
    2. HyDE (hypothetical document for semantic matching)
    3. Multi-query retrieval (search with all queries)
    4. Result fusion (merge and deduplicate)
    5. Hybrid search (vector + keyword + semantic)
    6. LLM reranking (final relevance scoring)
    
    Args:
        query: Original search query
        index_name: Target index
        top_k: Final number of results
        workflow_id: Optional workflow filter
        enable_query_expansion: Use multi-query retrieval
        enable_rerank: Apply LLM reranking
        enable_hyde: Generate hypothetical answer for semantic search
    """
    all_documents = []
    doc_ids_seen = set()
    queries_used = [query]
    hyde_doc = None
    
    # 1. Query expansion - generate alternative query phrasings
    if enable_query_expansion:
        try:
            from shared_code.query_enhancement import expand_query
            queries_used = await expand_query(query, num_variations=2)
            logging.info(f"Query expansion: {len(queries_used)} variations")
        except Exception as e:
            logging.warning(f"Query expansion failed: {e}")
            queries_used = [query]
    
    # 2. HyDE - generate hypothetical document for better semantic matching
    # This helps when query terms don't match document terminology
    if enable_hyde:
        try:
            from shared_code.query_enhancement import hypothetical_document_embedding
            hyde_doc = await hypothetical_document_embedding(query)
            if hyde_doc and hyde_doc != query:
                queries_used.append(hyde_doc)
                logging.info(f"HyDE generated hypothetical answer (added to search)")
        except Exception as e:
            logging.warning(f"HyDE generation failed (continuing without): {e}")
    
    # 3. Multi-query retrieval - fetch from all query variations
    retrieve_per_query = top_k * 2 if len(queries_used) > 1 else top_k * 3
    
    for q in queries_used:
        result = await consult_rag_tool(
            query=q,
            index_name=index_name,
            top_k=retrieve_per_query,
            search_type="hybrid",
            workflow_id=workflow_id
        )
        
        if result.get("success") and result.get("documents"):
            for doc in result["documents"]:
                doc_id = doc.get("id")
                if doc_id and doc_id not in doc_ids_seen:
                    all_documents.append(doc)
                    doc_ids_seen.add(doc_id)
    
    if not all_documents:
        return {
            "success": False,
            "error": "No documents found",
            "queries_used": queries_used
        }
    
    # 3. Sort by initial score
    all_documents.sort(
        key=lambda x: x.get("reranker_score") or x.get("score") or 0,
        reverse=True
    )
    
    # 4. Apply LLM reranking if enabled
    if enable_rerank and len(all_documents) > 3:
        try:
            from shared_code.reranker import rerank_documents
            all_documents = await rerank_documents(query, all_documents, top_k)
            reranked = True
        except Exception as e:
            logging.warning(f"Reranking failed: {e}")
            all_documents = all_documents[:top_k]
            reranked = False
    else:
        all_documents = all_documents[:top_k]
        reranked = False
    
    return {
        "success": True,
        "documents": all_documents,
        "count": len(all_documents),
        "queries_used": queries_used,
        "reranked": reranked,
        "hyde_used": hyde_doc is not None,
        "pipeline": "advanced"
    }
