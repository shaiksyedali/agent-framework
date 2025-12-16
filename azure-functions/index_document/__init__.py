"""
Azure Function: index_document
Indexes documents into Azure AI Search for RAG retrieval.
Accepts base64-encoded file content for cloud processing.
"""
import azure.functions as func
import logging
import json
import os
import sys
import base64
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

# Path Setup for shared_code
site_packages = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.python_packages', 'lib', 'site-packages')
if site_packages not in sys.path:
    sys.path.append(site_packages)

func_root = os.path.dirname(os.path.dirname(__file__))
if func_root not in sys.path:
    sys.path.append(func_root)

# Note: AzureKeyCredential is imported inside functions to avoid cold start crash


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> List[Dict[str, Any]]:
    """Split text into overlapping chunks. Larger chunks = fewer chunks = faster processing."""
    # Configurable chunk size (default 800 tokens ~= 3200 chars)
    if chunk_size is None:
        chunk_size = int(os.environ.get("CHUNK_SIZE_TOKENS", "800"))
    if overlap is None:
        overlap = int(os.environ.get("CHUNK_OVERLAP_TOKENS", "100"))
    
    char_chunk_size = chunk_size * 4
    char_overlap = overlap * 4
    
    chunks = []
    start = 0
    chunk_id = 0
    
    while start < len(text):
        end = start + char_chunk_size
        chunk_content = text[start:end]
        
        if end < len(text):
            for sep in ['. ', '.\n', '? ', '!\n', '\n\n']:
                last_sep = chunk_content.rfind(sep)
                if last_sep > char_chunk_size - 200:
                    end = start + last_sep + len(sep)
                    chunk_content = text[start:end]
                    break
        
        chunks.append({
            "chunk_id": chunk_id,
            "content": chunk_content.strip()
        })
        
        chunk_id += 1
        start = end - char_overlap
        
        if start >= len(text):
            break
    
    return chunks


def extract_text_from_pdf_bytes(content: bytes) -> List[Dict[str, Any]]:
    """Extract text from PDF bytes, page by page."""
    import pypdf
    import io
    
    pages = []
    reader = pypdf.PdfReader(io.BytesIO(content))
    
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({
                "page_number": page_num,
                "content": text
            })
    
    return pages


async def generate_embeddings_batch(texts: List[str], batch_size: int = 10) -> List[List[float]]:
    """
    Generate embeddings for multiple texts with rate limiting and retry.
    
    Uses smaller batches with delays to avoid 429 rate limit errors.
    """
    from openai import AsyncAzureOpenAI
    import asyncio
    
    client = AsyncAzureOpenAI(
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
    )
    
    model = os.environ.get("AZURE_EMBED_DEPLOYMENT", "text-embedding-3-small")
    dim = int(os.environ.get("AZURE_EMBED_DIM", "1536"))
    
    all_embeddings = []
    
    # Process in smaller batches to avoid rate limits
    for i in range(0, len(texts), batch_size):
        batch_texts = [t[:8000] for t in texts[i:i + batch_size]]  # Limit each text
        
        # Retry with exponential backoff on rate limit
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await client.embeddings.create(
                    input=batch_texts,
                    model=model,
                    dimensions=dim
                )
                all_embeddings.extend([item.embedding for item in response.data])
                break
            except Exception as e:
                if "429" in str(e) or "RateLimitReached" in str(e):
                    wait_time = (2 ** attempt) * 5  # 5, 10, 20 seconds
                    logging.warning(f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                    await asyncio.sleep(wait_time)
                else:
                    raise e
        else:
            # If all retries failed, raise error
            raise Exception(f"Failed to generate embeddings after {max_retries} retries")
        
        # Small delay between batches to prevent rate limiting
        if i + batch_size < len(texts):
            await asyncio.sleep(1)  # 1 second delay between batches
    
    await client.close()
    return all_embeddings


async def generate_chunk_summaries_batch(
    chunks: List[Dict[str, Any]], 
    batch_size: int = 10,
    doc_intel_result: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Generate summaries and extract metadata for chunks using INTELLIGENT HYBRID EXTRACTION.
    
    Strategy:
    - If Doc Intelligence extracted entities from tables, use those directly for structured chunks
    - Only use LLM for summaries/keywords (skip entity extraction) for structured chunks
    - Use full LLM extraction for prose-only chunks
    
    This reduces LLM calls by 40-60% while maintaining entity coverage.
    
    Args:
        chunks: List of chunk dicts with 'content' key
        batch_size: Number of chunks to process concurrently
        doc_intel_result: Result from Document Intelligence extraction (optional)
    """
    from openai import AsyncAzureOpenAI
    import asyncio
    
    client = AsyncAzureOpenAI(
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
    )
    
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    
    # Extract Doc Intelligence data for hybrid extraction
    table_text = set()
    structured_phrases = set()
    doc_intel_entities = []
    use_hybrid = False
    
    if doc_intel_result and doc_intel_result.get("success"):
        table_text = doc_intel_result.get("table_text", set())
        structured_phrases = doc_intel_result.get("structured_phrases", set())
        doc_intel_entities = doc_intel_result.get("entities", [])
        use_hybrid = bool(table_text or doc_intel_entities)
        
        if use_hybrid:
            logging.info(f"Hybrid extraction enabled: {len(doc_intel_entities)} Doc Intel entities, "
                        f"{len(table_text)} table phrases available")
    
    # Import chunk detection function
    try:
        from shared_code.document_intelligence import chunk_has_structured_content, get_entities_for_chunk
    except ImportError:
        use_hybrid = False
        logging.warning("Could not import hybrid extraction functions, using standard mode")
    
    async def summarize_structured_chunk(chunk_content: str) -> Dict[str, Any]:
        """
        For structured chunks: Get ONLY summary and keywords from LLM.
        Entities come from Document Intelligence.
        """
        prompt = f"""Analyze this text and provide ONLY a summary and keywords (no entity extraction needed):
1. SUMMARY: A 1-2 sentence summary of the main topic
2. KEYWORDS: 3-5 important keywords
3. CATEGORY: One of (ERROR_CODE, PROCEDURE, SPECIFICATION, TROUBLESHOOTING, GENERAL)

Text:
{chunk_content[:4000]}

Respond in JSON format:
{{"summary": "...", "keywords": ["..."], "category": "..."}}"""

        try:
            response = await client.chat.completions.create(
                model=deployment,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400,  # Smaller since no entities
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # Get entities from Doc Intelligence that appear in this chunk
            chunk_entities = get_entities_for_chunk(chunk_content, doc_intel_entities, structured_phrases)
            
            return {
                "summary": result.get("summary", ""),
                "entities": chunk_entities,  # From Doc Intelligence, not LLM
                "relationships": [],  # Could be enhanced later
                "keywords": result.get("keywords", []),
                "category": result.get("category", "GENERAL"),
                "_extraction_mode": "hybrid_structured"
            }
        except Exception as e:
            logging.warning(f"Structured chunk processing failed: {e}")
            return {"summary": "", "entities": [], "relationships": [], "keywords": [], "category": "GENERAL"}
    
    async def summarize_prose_chunk(chunk_content: str) -> Dict[str, Any]:
        """
        For prose chunks: Full single-pass LLM extraction (summary + entities).
        """
        prompt = f"""Analyze this text and provide:
1. SUMMARY: A 1-2 sentence summary of the main topic
2. ENTITIES: Extract ALL identifiers, codes, component names, error codes, and technical terms. Types: CODE, COMPONENT, CONDITION, VALUE, PROCEDURE, CONCEPT
3. RELATIONSHIPS: Key connections between concepts
4. KEYWORDS: 3-5 important keywords
5. CATEGORY: One of (ERROR_CODE, PROCEDURE, SPECIFICATION, TROUBLESHOOTING, GENERAL)

Text:
{chunk_content[:4000]}

Respond in JSON format:
{{"summary": "...", "entities": [{{"name": "...", "type": "CODE|COMPONENT|CONDITION|VALUE|PROCEDURE|CONCEPT", "description": "..."}}], "relationships": [{{"source": "...", "target": "...", "type": "CAUSES|TRIGGERS|AFFECTS|HAS|RELATED_TO|FIXES|REQUIRES", "description": "..."}}], "keywords": ["..."], "category": "..."}}"""

        try:
            response = await client.chat.completions.create(
                model=deployment,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            return {
                "summary": result.get("summary", ""),
                "entities": result.get("entities", []),
                "relationships": result.get("relationships", []),
                "keywords": result.get("keywords", []),
                "category": result.get("category", "GENERAL"),
                "_extraction_mode": "llm_prose"
            }
        except Exception as e:
            logging.warning(f"Prose chunk processing failed: {e}")
            return {"summary": "", "entities": [], "relationships": [], "keywords": [], "category": "GENERAL"}
    
    async def smart_summarize_chunk(chunk_content: str) -> Dict[str, Any]:
        """
        Intelligent routing: Use structured extraction for table-heavy chunks,
        prose extraction for text-heavy chunks.
        """
        if use_hybrid and chunk_has_structured_content(chunk_content, table_text, structured_phrases):
            return await summarize_structured_chunk(chunk_content)
        else:
            return await summarize_prose_chunk(chunk_content)
    
    # Process in batches to avoid rate limits
    results = []
    structured_count = 0
    prose_count = 0
    
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        batch_results = await asyncio.gather(*[
            smart_summarize_chunk(c["content"]) for c in batch
        ])
        
        # Track extraction modes for logging
        for r in batch_results:
            if r.get("_extraction_mode") == "hybrid_structured":
                structured_count += 1
            else:
                prose_count += 1
        
        results.extend(batch_results)
        logging.info(f"Processed chunks {i+1} to {min(i+batch_size, len(chunks))} of {len(chunks)}")
    
    logging.info(f"Hybrid extraction complete: {structured_count} structured chunks (no LLM entities), "
                f"{prose_count} prose chunks (full LLM)")
    
    await client.close()
    return results



async def generate_document_summary(all_chunk_summaries: List[str], file_name: str) -> Dict[str, Any]:
    """
    Generate document-level summary from chunk summaries using Map-Reduce.
    """
    from openai import AsyncAzureOpenAI
    
    client = AsyncAzureOpenAI(
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
    )
    
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    
    # Combine chunk summaries (limit to avoid token overflow)
    combined = "\n".join([f"- {s}" for s in all_chunk_summaries[:100] if s])
    
    prompt = f"""Based on these section summaries from the document "{file_name}", provide:
1. An executive summary (3-5 sentences)
2. Key findings (5-10 bullet points)
3. Table of contents structure

Section Summaries:
{combined}

Respond in JSON format:
{{"executive_summary": "...", "key_findings": ["..."], "table_of_contents": ["..."]}}"""

    try:
        response = await client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1500,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        await client.close()
        return {
            "executive_summary": result.get("executive_summary", ""),
            "key_findings": result.get("key_findings", []),
            "table_of_contents": result.get("table_of_contents", [])
        }
    except Exception as e:
        logging.error(f"Document summary generation failed: {e}")
        await client.close()
        return {"executive_summary": "", "key_findings": [], "table_of_contents": []}


async def index_document_content(
    content: bytes,
    workflow_id: str,
    file_name: str,
    file_type: str,
    index_name: Optional[str] = None
) -> Dict[str, Any]:
    """Process and index document content to Azure AI Search."""
    from azure.search.documents.aio import SearchClient
    from azure.core.credentials import AzureKeyCredential
    
    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    search_key = os.environ.get("AZURE_SEARCH_KEY") or os.environ.get("AZURE_SEARCH_API_KEY")
    
    if not index_name:
        index_name = os.environ.get("AZURE_SEARCH_INDEX", "schema-docs")
    
    if not search_endpoint or not search_key:
        return {"success": False, "error": "AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_KEY not set"}
    
    try:
        # 1. Extract text using Document Intelligence (if enabled) or basic extraction
        doc_intel_entities = []
        tables = []
        doc_result = None  # Store Document Intelligence result for hybrid extraction
        use_doc_intel = os.environ.get("ENABLE_DOC_INTELLIGENCE", "false").lower() == "true"
        
        if use_doc_intel:
            try:
                from shared_code.document_intelligence import extract_from_any_format, deduplicate_entities
                
                logging.info(f"Attempting Document Intelligence extraction for {file_name}")
                doc_result = await extract_from_any_format(content, file_type, file_name)
                
                if doc_result.get("success"):
                    pages = doc_result.get("pages", [])
                    tables = doc_result.get("tables", [])
                    doc_intel_entities = doc_result.get("entities", [])
                    logging.info(f"Document Intelligence extracted: {len(pages)} pages, "
                               f"{len(tables)} tables, {len(doc_intel_entities)} entities")
                else:
                    logging.warning(f"Document Intelligence failed: {doc_result.get('error')}, using fallback")
                    raise Exception("Fallback to basic extraction")
                    
            except ImportError as ie:
                logging.error(f"Document Intelligence import failed - package not installed: {ie}")
                use_doc_intel = False
            except Exception as e:
                logging.warning(f"Document Intelligence fallback due to error: {type(e).__name__}: {e}")
                use_doc_intel = False  # Fall through to basic extraction
        
        logging.info(f"Extraction status: use_doc_intel={use_doc_intel}, pages_count={len(pages) if 'pages' in locals() else 0}")
        
        if not use_doc_intel:
            # Basic text extraction
            if file_type == "pdf":
                pages = extract_text_from_pdf_bytes(content)
            elif file_type in ["txt", "md", "csv", "json", "xml"]:
                text = content.decode('utf-8', errors='ignore')
                pages = [{"page_number": 1, "content": text}]
            else:
                return {"success": False, "error": f"Unsupported file type: {file_type}"}
        
        if not pages:
            # Include more detail about which extraction method was tried
            extraction_method = "Document Intelligence" if use_doc_intel else "pypdf basic extraction"
            doc_intel_error = doc_result.get('error', 'unknown') if doc_result else 'not attempted'
            return {
                "success": False, 
                "error": f"No text content extracted from file. Method: {extraction_method}. "
                         f"Doc Intelligence: {doc_intel_error}. "
                         f"This usually means the PDF is a scanned image without OCR text layer, "
                         f"or Document Intelligence failed to process it."
            }
        
        # 2. Chunk all pages - support both semantic and character-based chunking
        chunking_strategy = os.environ.get("CHUNKING_STRATEGY", "character").lower()  # Default: character (faster)
        all_chunks = []
        
        if chunking_strategy == "semantic":
            # Semantic chunking: split at natural topic boundaries
            try:
                from shared_code.chunking import semantic_chunk_text, paragraph_chunk_text
                logging.info("Using semantic chunking strategy")
                
                # Combine all pages into single text for better semantic analysis
                full_text = "\n\n".join(p["content"] for p in pages)
                chunks = await semantic_chunk_text(full_text, threshold=0.5)
                
                for chunk in chunks:
                    all_chunks.append({
                        "page_number": 1,  # Page tracking not available with semantic chunking
                        "chunk_id": chunk["chunk_id"],
                        "content": chunk["content"]
                    })
            except Exception as e:
                logging.warning(f"Semantic chunking failed, falling back to character-based: {e}")
                chunking_strategy = "character"
        
        if chunking_strategy == "paragraph":
            # Paragraph-based chunking: split on paragraph boundaries
            try:
                from shared_code.chunking import paragraph_chunk_text
                logging.info("Using paragraph chunking strategy")
                
                full_text = "\n\n".join(p["content"] for p in pages)
                chunks = paragraph_chunk_text(full_text)
                
                for chunk in chunks:
                    all_chunks.append({
                        "page_number": 1,
                        "chunk_id": chunk["chunk_id"],
                        "content": chunk["content"]
                    })
            except Exception as e:
                logging.warning(f"Paragraph chunking failed, falling back to character-based: {e}")
                chunking_strategy = "character"
        
        if chunking_strategy == "character" or not all_chunks:
            # Character-based chunking: fixed size with overlap (default)
            logging.info("Using character-based chunking strategy")
            for page in pages:
                chunks = chunk_text(page["content"])
                for chunk in chunks:
                    all_chunks.append({
                        "page_number": page["page_number"],
                        "chunk_id": chunk["chunk_id"],
                        "content": chunk["content"]
                    })
        
        logging.info(f"Generated {len(all_chunks)} chunks from {len(pages)} pages using {chunking_strategy} strategy")

        
        # 3. Batch generate embeddings
        chunk_texts = [c["content"] for c in all_chunks]
        embeddings = await generate_embeddings_batch(chunk_texts)
        
        # 4. Generate extractive summaries (using Azure AI Language - fast NLP, not LLM)
        enable_summaries = os.environ.get("ENABLE_CHUNK_SUMMARIES", "false").lower() == "true"
        chunk_summaries = []
        doc_summary = {}
        
        if enable_summaries and len(all_chunks) > 0:
            logging.info(f"Generating extractive summaries for {len(all_chunks)} chunks...")
            try:
                from shared_code.summarizer import generate_extractive_summaries
                chunk_texts = [c["content"] for c in all_chunks]
                chunk_summaries = await generate_extractive_summaries(
                    chunks=chunk_texts,
                    batch_size=25,
                    max_sentence_count=2,
                    timeout_seconds=180  # 3 minutes max for summaries
                )
                logging.info(f"Generated {len(chunk_summaries)} extractive summaries")
                
                # Generate document-level summary (combine first few chunk summaries)
                if chunk_summaries:
                    # Take first 5 summaries as document overview
                    overview_summaries = [s for s in chunk_summaries[:5] if s]
                    if overview_summaries:
                        doc_summary = {
                            "executive_summary": " ".join(overview_summaries[:3]),
                            "key_findings": overview_summaries[:5]
                        }
            except Exception as summary_error:
                logging.warning(f"Extractive summarization failed, continuing without summaries: {summary_error}")
        
        # 4b. Named entities - currently disabled (Azure NER doesn't recognize technical codes)
        # Entity_codes field will be populated by Document Intelligence entities only
        ner_entities_per_chunk = [[] for _ in all_chunks]
        
        # 5. Prepare documents for Azure AI Search + Build EntityGraph
        from shared_code.entity_graph import EntityGraph
        
        created_at = datetime.utcnow().isoformat()
        documents = []
        all_keywords = []
        all_relationships = []
        
        # Build EntityGraph for deduplication and relationship tracking
        entity_graph = EntityGraph()
        
        # Add Document Intelligence entities first (from tables and key-value pairs)
        if doc_intel_entities:
            logging.info(f"Adding {len(doc_intel_entities)} Document Intelligence entities to graph")
            for entity in doc_intel_entities:
                if isinstance(entity, dict):
                    entity_graph.add_entity(
                        name=entity.get("name", ""),
                        entity_type=entity.get("type", "CODE"),
                        description=entity.get("description", ""),
                        chunk_id="doc_intel"
                    )
        
        for i, chunk in enumerate(all_chunks):
            doc_id = f"{workflow_id}-{file_name}-p{chunk['page_number']}-c{chunk['chunk_id']}"
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))
            
            # Get chunk summary if available (from Azure AI Language extractive summarization)
            chunk_summary = chunk_summaries[i] if i < len(chunk_summaries) else ""
            
            # Get NER entities for this chunk (from Azure AI Language NER)
            ner_entities = ner_entities_per_chunk[i] if i < len(ner_entities_per_chunk) else []
            
            # Also include Document Intelligence entities that appear in this chunk
            di_entities = []
            if doc_intel_entities:
                chunk_content_lower = chunk["content"].lower()
                di_entities = [
                    e for e in doc_intel_entities
                    if isinstance(e, dict) and e.get("name", "").lower() in chunk_content_lower
                ]
            
            # Merge all entities (NER takes precedence)
            all_chunk_entities = ner_entities + di_entities
            
            # Add entities to graph for deduplication
            for entity in all_chunk_entities:
                if isinstance(entity, dict):
                    entity_graph.add_entity(
                        name=entity.get("name", ""),
                        entity_type=entity.get("type", "CONCEPT"),
                        description=entity.get("description", ""),
                        chunk_id=doc_id
                    )
                elif isinstance(entity, str):
                    entity_graph.add_entity(name=entity, entity_type="CONCEPT", chunk_id=doc_id)
            
            # Build entity_codes from Document Intelligence entities only
            # NER is disabled - Azure NER doesn't recognize technical codes
            entity_codes_list = []
            allowed_types = {"IDENTIFIER", "COMPONENT", "ACTOR", "CODE"}
            for e in di_entities:
                if e and isinstance(e, dict) and e.get("type", "").upper() in allowed_types:
                    entity_name = e.get("name", "")
                    if entity_name and entity_name not in entity_codes_list:
                        entity_codes_list.append(entity_name)
            
            doc = {
                "id": doc_id,
                "workflow_id": workflow_id,
                "file_name": file_name,
                "doc_type": "chunk",
                "title": f"{file_name} - Page {chunk['page_number']}",
                "content": chunk["content"],
                "content_vector": embeddings[i],
                "source": file_name,
                "page_number": chunk["page_number"],
                "chunk_id": str(chunk["chunk_id"]),
                "created_at": created_at,
                # Pre-computed metadata
                "chunk_summary": chunk_summary,  # From Azure AI Language extractive summarization
                "entities": json.dumps(all_chunk_entities),  # All entities (NER + DocIntel)
                "keywords": "",  # Keywords not extracted in fast path
                "category": "GENERAL",  # Generic category
                # Facetable field: array of entity names for Azure Search aggregation
                "entity_codes": entity_codes_list,
            }
            documents.append(doc)
            
            # Keywords aggregation removed (using extractive summaries instead)
        
        # Log entity graph stats
        graph_stats = entity_graph._count_by_types()
        logging.info(f"EntityGraph built: {len(entity_graph.entities)} unique entities, {len(entity_graph.relationships)} relationships")
        logging.info(f"Entity types: {dict(graph_stats)}")
        
        # 6. Add document-level summary record with EntityGraph data
        if doc_summary.get("executive_summary"):
            doc_summary_id = f"{workflow_id}-{file_name}-summary"
            doc_summary_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_summary_id))
            
            # Create summary embedding for vector search
            summary_text = doc_summary.get("executive_summary", "")
            summary_embedding = (await generate_embeddings_batch([summary_text]))[0] if summary_text else [0.0] * 1536
            
            # Get deduplicated entities sorted by frequency
            graph_data = entity_graph.to_dict()
            sorted_entities = sorted(
                graph_data["entities"], 
                key=lambda x: x.get("frequency", 1), 
                reverse=True
            )
            
            documents.append({
                "id": doc_summary_id,
                "workflow_id": workflow_id,
                "file_name": file_name,
                "doc_type": "document_summary",
                "title": f"{file_name} - Document Summary",
                "content": summary_text,
                "content_vector": summary_embedding,
                "source": file_name,
                "page_number": 0,
                "chunk_id": "summary",
                "created_at": created_at,
                # Document-level fields
                "executive_summary": doc_summary.get("executive_summary", ""),
                "key_findings": json.dumps(doc_summary.get("key_findings", [])),
                "table_of_contents": json.dumps(doc_summary.get("table_of_contents", [])),
                "total_chunks": len(all_chunks),
                # GraphRAG: Deduplicated entities with types and frequencies
                "entities": json.dumps(sorted_entities[:200]),  # Top 200 by frequency
                "keywords": json.dumps(list(set(all_keywords))[:50]),
                # NEW: Relationship data
                "relationships": json.dumps(graph_data["relationships"][:100]),
                # NEW: Entity graph statistics
                "entity_stats": json.dumps(graph_data["stats"]),
                # Facetable: all entity names for aggregation queries
                "entity_codes": [e.get("name", "") for e in sorted_entities if e.get("name")],
            })
            logging.info(f"Added document summary with {len(sorted_entities)} unique entities, {len(graph_data['relationships'])} relationships")
        
        # 7. Upload to Azure AI Search
        credential = AzureKeyCredential(search_key)
        async with SearchClient(search_endpoint, index_name, credential) as client:
            batch_size = 100
            uploaded = 0
            
            for i in range(0, len(documents), batch_size):
                batch = documents[i:i + batch_size]
                result = await client.upload_documents(batch)
                uploaded += len([r for r in result if r.succeeded])
        
        logging.info(f"Successfully indexed {uploaded}/{len(documents)} documents (including summaries)")
        
        return {
            "success": True,
            "workflow_id": workflow_id,
            "file_name": file_name,
            "pages": len(pages),
            "chunks": len(all_chunks),
            "indexed": uploaded,
            "summaries_generated": enable_summaries,
            "has_document_summary": bool(doc_summary.get("executive_summary")),
            # Include chunks for LLM entity extraction orchestration
            "_chunks_for_extraction": all_chunks,
            "_index_name": index_name
        }
    
    except Exception as e:
        logging.error(f"Error indexing document: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def main(req: func.HttpRequest, starter: str) -> func.HttpResponse:
    """
    Index Document HTTP Trigger.
    
    After basic indexing, triggers LLM entity extraction via Durable Functions.
    """
    logging.info('Index Document Function triggered')
    
    try:
        # Import dependencies here to catch import errors
        try:
            import pypdf
            logging.info(f"pypdf version: {pypdf.__version__}")
        except ImportError as e:
            logging.error(f"Failed to import pypdf: {e}")
            return func.HttpResponse(
                json.dumps({"error": f"Missing dependency: {e}", "success": False}),
                status_code=500,
                mimetype="application/json"
            )
        
        try:
            from azure.search.documents.aio import SearchClient
            from openai import AsyncAzureOpenAI
        except ImportError as e:
            logging.error(f"Failed to import Azure SDK: {e}")
            return func.HttpResponse(
                json.dumps({"error": f"Missing Azure SDK: {e}", "success": False}),
                status_code=500,
                mimetype="application/json"
            )
        
        # Check environment variables
        missing_vars = []
        for var in ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY"]:
            if not os.environ.get(var):
                missing_vars.append(var)
        
        if missing_vars:
            return func.HttpResponse(
                json.dumps({"error": f"Missing environment variables: {missing_vars}", "success": False}),
                status_code=500,
                mimetype="application/json"
            )
        
        req_body = req.get_json()
        workflow_id = req_body.get('workflow_id')
        file_name = req_body.get('file_name')
        file_content_b64 = req_body.get('file_content')  # base64 encoded
        file_type = req_body.get('file_type', 'pdf')
        index_name = req_body.get('index_name')

        if not workflow_id or not file_content_b64 or not file_name:
            return func.HttpResponse(
                json.dumps({"error": "workflow_id, file_name, and file_content are required"}),
                status_code=400,
                mimetype="application/json"
            )

        # Decode base64 content
        content = base64.b64decode(file_content_b64)
        logging.info(f"Received {len(content)} bytes for {file_name}")

        result = await index_document_content(
            content=content,
            workflow_id=workflow_id,
            file_name=file_name,
            file_type=file_type,
            index_name=index_name
        )
        
        # If indexing succeeded and we have chunks, optionally start LLM entity extraction
        # Disabled by default for fast indexing - enable via ENABLE_LLM_ENTITY_EXTRACTION=true
        extraction_instance_id = None
        enable_llm_extraction = os.environ.get("ENABLE_LLM_ENTITY_EXTRACTION", "false").lower() == "true"
        
        if enable_llm_extraction and result.get("success") and result.get("_chunks_for_extraction"):
            try:
                import azure.durable_functions as df
                
                chunks = result.pop("_chunks_for_extraction", [])
                index_for_extraction = result.pop("_index_name", None)
                
                # Create durable client and start orchestration
                client = df.DurableOrchestrationClient(starter)
                extraction_instance_id = await client.start_new(
                    "EntityExtractionOrchestrator",
                    client_input={
                        "chunks": chunks,
                        "workflow_id": workflow_id,
                        "file_name": file_name,
                        "index_name": index_for_extraction
                    }
                )
                
                logging.info(f"Started entity extraction orchestration: {extraction_instance_id}")
                result["entity_extraction_instance_id"] = extraction_instance_id
                
            except Exception as e:
                # Don't fail the indexing if orchestration fails to start
                logging.warning(f"Failed to start entity extraction orchestration: {e}")
                result["entity_extraction_error"] = str(e)
        else:
            # Remove internal fields from response
            result.pop("_chunks_for_extraction", None)
            result.pop("_index_name", None)
            if not enable_llm_extraction:
                logging.info("LLM entity extraction disabled (set ENABLE_LLM_ENTITY_EXTRACTION=true to enable)")
        
        status = 200 if result.get("success") else 500
        return func.HttpResponse(
            json.dumps(result),
            mimetype="application/json",
            status_code=status
        )

    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": str(e), "success": False}),
            status_code=500,
            mimetype="application/json"
        )

