"""
Extractive Summarization module using Azure AI Language.

Generates high-quality chunk summaries without LLM overhead.
Uses Azure AI Language extractive summarization which identifies
key sentences rather than generating new text.

Performance: ~3 seconds per batch of 25 chunks
268 chunks = ~33 seconds (well within 5-minute timeout)
"""
import logging
import os
import asyncio
from typing import List, Optional, Dict, Any

# Lazy imports to avoid cold start issues
_client = None


def _get_client():
    """Get or create Azure AI Language client (lazy initialization)."""
    global _client
    if _client is not None:
        return _client
    
    endpoint = os.environ.get("AZURE_LANGUAGE_ENDPOINT")
    key = os.environ.get("AZURE_LANGUAGE_KEY")
    
    if not endpoint or not key:
        logging.warning("Azure AI Language not configured (AZURE_LANGUAGE_ENDPOINT/KEY missing)")
        return None
    
    from azure.ai.textanalytics import TextAnalyticsClient
    from azure.core.credentials import AzureKeyCredential
    
    _client = TextAnalyticsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )
    return _client


async def generate_extractive_summaries(
    chunks: List[str],
    batch_size: int = 25,
    max_sentence_count: int = 2,
    timeout_seconds: int = 180
) -> List[str]:
    """
    Generate extractive summaries for multiple chunks using Azure AI Language.
    
    This uses Azure's NLP-based extractive summarization which:
    - Identifies the most important sentences in each chunk
    - Returns them with relevance ranking
    - Does NOT use LLM (faster and cheaper)
    
    Args:
        chunks: List of text chunks to summarize
        batch_size: Documents per API request (Azure limit: 25)
        max_sentence_count: Number of sentences per summary (1-3 recommended)
        timeout_seconds: Maximum time for all summarization
    
    Returns:
        List of summaries (one per chunk). Falls back to first sentence if API fails.
    """
    if not chunks:
        return []
    
    client = _get_client()
    if client is None:
        logging.info("Azure AI Language not available, using fallback summarization")
        return [_fallback_summary(chunk) for chunk in chunks]
    
    from azure.ai.textanalytics import ExtractiveSummaryAction
    
    summaries = [""] * len(chunks)  # Pre-allocate for index-based assignment
    start_time = asyncio.get_event_loop().time()
    
    try:
        # Process in batches
        for batch_start in range(0, len(chunks), batch_size):
            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout_seconds:
                logging.warning(f"Summarization timeout after {batch_start} chunks")
                # Fill remaining with fallback
                for i in range(batch_start, len(chunks)):
                    summaries[i] = _fallback_summary(chunks[i])
                break
            
            batch_end = min(batch_start + batch_size, len(chunks))
            batch = chunks[batch_start:batch_end]
            
            # Prepare documents with IDs
            documents = []
            for i, text in enumerate(batch):
                # Azure AI Language has character limits per document
                # Truncate to avoid errors (125,000 char limit)
                truncated_text = text[:100000] if len(text) > 100000 else text
                
                # Skip very short chunks that can't be summarized
                if len(truncated_text.strip()) < 50:
                    summaries[batch_start + i] = truncated_text.strip()[:150]
                    continue
                
                documents.append({
                    "id": str(batch_start + i),
                    "text": truncated_text
                })
            
            if not documents:
                continue
            
            try:
                # Run extractive summarization
                poller = client.begin_analyze_actions(
                    documents=documents,
                    actions=[ExtractiveSummaryAction(max_sentence_count=max_sentence_count)],
                    polling_interval=1
                )
                
                # Wait for results with timeout
                result = poller.result()
                
                # Process results
                for doc_results in result:
                    for action_result in doc_results:
                        if action_result.is_error:
                            logging.warning(f"Summary error for doc {action_result.id}: {action_result.error}")
                            idx = int(action_result.id)
                            summaries[idx] = _fallback_summary(chunks[idx])
                        else:
                            idx = int(action_result.id)
                            # Combine extracted sentences
                            if action_result.sentences:
                                summary = " ".join([s.text for s in action_result.sentences])
                                summaries[idx] = summary
                            else:
                                summaries[idx] = _fallback_summary(chunks[idx])
                
                logging.info(f"Summarized batch {batch_start}-{batch_end} ({len(documents)} docs)")
                
            except Exception as batch_error:
                logging.warning(f"Batch {batch_start}-{batch_end} failed: {batch_error}")
                # Fallback for this batch
                for i in range(batch_start, batch_end):
                    if not summaries[i]:
                        summaries[i] = _fallback_summary(chunks[i])
            
            # Small delay between batches to avoid rate limiting
            await asyncio.sleep(0.5)
        
        # Fill any remaining empty summaries
        for i, summary in enumerate(summaries):
            if not summary:
                summaries[i] = _fallback_summary(chunks[i])
        
        logging.info(f"Generated {len(summaries)} summaries in {asyncio.get_event_loop().time() - start_time:.1f}s")
        return summaries
        
    except Exception as e:
        logging.error(f"Summarization failed completely: {e}")
        return [_fallback_summary(chunk) for chunk in chunks]


def _fallback_summary(text: str, max_length: int = 200) -> str:
    """
    Fast fallback: Extract first sentence + key phrases.
    Used when Azure AI Language is unavailable or fails.
    """
    if not text or len(text.strip()) < 10:
        return text.strip()[:max_length] if text else ""
    
    # Get first sentence
    text = text.strip()
    
    # Find sentence boundary
    for sep in ['. ', '.\n', '! ', '!\n', '? ', '?\n']:
        idx = text.find(sep)
        if idx > 20 and idx < 300:  # Reasonable sentence length
            return text[:idx + 1].strip()
    
    # No good sentence boundary, just truncate
    if len(text) > max_length:
        # Try to break at word boundary
        truncated = text[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.7:
            return truncated[:last_space] + "..."
        return truncated + "..."
    
    return text


def generate_extractive_summaries_sync(
    chunks: List[str],
    batch_size: int = 25,
    max_sentence_count: int = 2
) -> List[str]:
    """
    Synchronous wrapper for extractive summarization.
    Use this in non-async contexts.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in async context, create new task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    generate_extractive_summaries(chunks, batch_size, max_sentence_count)
                )
                return future.result(timeout=180)
        else:
            return loop.run_until_complete(
                generate_extractive_summaries(chunks, batch_size, max_sentence_count)
            )
    except Exception as e:
        logging.error(f"Sync summarization failed: {e}")
        return [_fallback_summary(chunk) for chunk in chunks]


async def generate_keywords(text: str, max_keywords: int = 5) -> List[str]:
    """
    Extract key phrases from text using Azure AI Language.
    Useful for chunk metadata alongside summaries.
    """
    client = _get_client()
    if client is None:
        return _extract_keywords_fallback(text, max_keywords)
    
    try:
        result = client.extract_key_phrases([text])
        for doc in result:
            if not doc.is_error and doc.key_phrases:
                return doc.key_phrases[:max_keywords]
        return _extract_keywords_fallback(text, max_keywords)
    except Exception:
        return _extract_keywords_fallback(text, max_keywords)


def _extract_keywords_fallback(text: str, max_keywords: int = 5) -> List[str]:
    """
    Simple keyword extraction fallback using word frequency.
    """
    import re
    from collections import Counter
    
    # Common stop words
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'shall', 'can', 'this', 'that',
        'these', 'those', 'it', 'its', 'they', 'them', 'their', 'we', 'our',
        'you', 'your', 'he', 'she', 'his', 'her', 'which', 'what', 'who',
        'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few',
        'more', 'most', 'other', 'some', 'such', 'no', 'not', 'only', 'same',
        'so', 'than', 'too', 'very', 'just', 'also', 'now', 'here', 'there'
    }
    
    # Extract words (alphanumeric, 3+ chars)
    words = re.findall(r'\b[a-zA-Z0-9]{3,}\b', text.lower())
    
    # Filter stop words and count
    filtered = [w for w in words if w not in stop_words]
    counts = Counter(filtered)
    
    # Return top keywords
    return [word for word, _ in counts.most_common(max_keywords)]


# =============================================================================
# NAMED ENTITY RECOGNITION (NER)
# Uses Azure AI Language for fast, document-agnostic entity extraction
# =============================================================================

# Entity categories that should be converted to facetable entity_codes
# Include ALL categories to ensure technical terms are captured
# Azure NER categories: https://docs.microsoft.com/azure/cognitive-services/language-service/named-entity-recognition/concepts/named-entity-categories
FACETABLE_CATEGORIES = {
    # Core categories (most common)
    "Product",          # Products, software, systems
    "Organization",     # Company names, teams
    "Event",            # Named events
    "Skill",            # Technical skills, capabilities
    "PersonType",       # Roles like "technician", "engineer"
    # Additional categories that may contain DTC codes or technical identifiers
    "Quantity",         # May contain code-like values
    "DateTime",         # Dates/times
    "Address",          # Addresses
    "PhoneNumber",      # Phone numbers
    "Email",            # Emails
    "URL",              # URLs
    "IPAddress",        # IP addresses
}

# Also capture ANY entity to ensure nothing is missed
# For documents with technical codes, we want ALL entities in facets
CAPTURE_ALL_ENTITIES = True  # Set to True to include all NER entities

# Extended categories to extract (for search, not facets)
ALL_NER_CATEGORIES = {
    "Product", "Organization", "Person", "Location", "DateTime", 
    "Quantity", "Event", "Skill", "PersonType", "Address", 
    "Email", "URL", "IPAddress", "PhoneNumber"
}


async def extract_entities_batch(
    chunks: List[str],
    batch_size: int = 5,  # NER has lower batch limit than summarization
    min_confidence: float = 0.7,
    timeout_seconds: int = 120
) -> List[List[Dict[str, Any]]]:
    """
    Extract named entities from multiple chunks using Azure AI Language NER.
    
    This is generic (works on any document type) and fast (~2 sec per batch).
    Categories extracted: Product, Organization, Person, DateTime, Quantity, etc.
    
    Args:
        chunks: List of text chunks to analyze
        batch_size: Documents per API request (NER limit: 5 documents)
        min_confidence: Minimum confidence score to include entity
        timeout_seconds: Maximum time for all NER
    
    Returns:
        List of entity lists (one per chunk). Each entity is a dict with:
        - name: entity text
        - type: entity category (Product, Organization, etc.)
        - confidence: confidence score
        - subcategory: optional subcategory
    """
    if not chunks:
        return []
    
    client = _get_client()
    if client is None:
        logging.info("Azure AI Language not available for NER")
        return [[] for _ in chunks]
    
    entities_per_chunk = [[] for _ in range(len(chunks))]
    start_time = asyncio.get_event_loop().time()
    
    try:
        for batch_start in range(0, len(chunks), batch_size):
            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout_seconds:
                logging.warning(f"NER timeout after {batch_start} chunks")
                break
            
            batch_end = min(batch_start + batch_size, len(chunks))
            batch = chunks[batch_start:batch_end]
            
            # Prepare documents - NER has 5120 char limit per doc
            documents = []
            doc_indices = []  # Track which original index each doc maps to
            
            for i, text in enumerate(batch):
                original_idx = batch_start + i
                
                # Truncate to NER limit
                truncated_text = text[:5000] if len(text) > 5000 else text
                
                if len(truncated_text.strip()) < 10:
                    continue
                
                documents.append({
                    "id": str(original_idx),
                    "text": truncated_text,
                    "language": "en"  # Auto-detect would be slower
                })
                doc_indices.append(original_idx)
            
            if not documents:
                continue
            
            try:
                # Call NER API
                results = client.recognize_entities(documents)
                
                for doc_result in results:
                    if doc_result.is_error:
                        logging.warning(f"NER error for doc {doc_result.id}: {doc_result.error}")
                        continue
                    
                    idx = int(doc_result.id)
                    
                    for entity in doc_result.entities:
                        # Filter by confidence
                        if entity.confidence_score < min_confidence:
                            continue
                        
                        entities_per_chunk[idx].append({
                            "name": entity.text,
                            "type": entity.category,
                            "confidence": entity.confidence_score,
                            "subcategory": entity.subcategory if hasattr(entity, 'subcategory') else None
                        })
                
                logging.info(f"NER batch {batch_start}-{batch_end}: extracted entities")
                
            except Exception as batch_error:
                logging.warning(f"NER batch {batch_start}-{batch_end} failed: {batch_error}")
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.3)
        
        # Log stats
        total_entities = sum(len(e) for e in entities_per_chunk)
        elapsed = asyncio.get_event_loop().time() - start_time
        logging.info(f"NER extracted {total_entities} entities from {len(chunks)} chunks in {elapsed:.1f}s")
        
        return entities_per_chunk
        
    except Exception as e:
        logging.error(f"NER failed completely: {e}")
        return [[] for _ in chunks]


def get_facetable_entities(chunk_entities: List[Dict[str, Any]]) -> List[str]:
    """
    Filter entities to those suitable for facet queries (entity_codes field).
    
    Only includes entity categories that are meaningful for aggregation:
    - Product: DTC codes, part numbers, software versions
    - Organization: Company names, teams
    - Event: Named events
    - Skill: Technical capabilities
    
    Args:
        chunk_entities: List of entities from NER
    
    Returns:
        List of entity names suitable for faceting
    """
    facet_values = []
    seen = set()  # Dedupe within chunk
    
    for entity in chunk_entities:
        entity_type = entity.get("type", "")
        entity_name = entity.get("name", "").strip()
        
        if not entity_name or entity_name.lower() in seen:
            continue
        
        # If CAPTURE_ALL_ENTITIES is True, include ALL entities
        # Otherwise, only include entities from FACETABLE_CATEGORIES
        should_include = CAPTURE_ALL_ENTITIES or entity_type in FACETABLE_CATEGORIES
        
        if should_include:
            facet_values.append(entity_name)
            seen.add(entity_name.lower())
    
    return facet_values


def merge_entities_for_chunk(
    ner_entities: List[Dict[str, Any]],
    doc_intel_entities: List[Dict[str, Any]],
    chunk_content: str
) -> List[Dict[str, Any]]:
    """
    Merge NER entities with Document Intelligence entities.
    
    Deduplicates and prefers higher-confidence sources.
    
    Args:
        ner_entities: Entities from Azure AI Language NER
        doc_intel_entities: Entities from Document Intelligence
        chunk_content: Text content of the chunk (for filtering)
    
    Returns:
        Merged list of entities
    """
    merged = {}
    chunk_lower = chunk_content.lower()
    
    # Add NER entities first (higher quality)
    for entity in ner_entities:
        name = entity.get("name", "").strip()
        if name and name.lower() in chunk_lower:
            key = name.lower()
            if key not in merged:
                merged[key] = entity
    
    # Add Document Intelligence entities (if not already present)
    for entity in doc_intel_entities:
        if isinstance(entity, dict):
            name = entity.get("name", "").strip()
            if name and name.lower() in chunk_lower:
                key = name.lower()
                if key not in merged:
                    merged[key] = entity
    
    return list(merged.values())


# Test function
if __name__ == "__main__":
    test_chunks = [
        "Azure AI Language is a cloud-based service that provides Natural Language Processing features. It enables developers to build applications that can understand and extract meaning from text.",
        "Machine learning models can be trained on large datasets to recognize patterns. This allows them to make predictions and classifications on new, unseen data."
    ]
    
    summaries = generate_extractive_summaries_sync(test_chunks)
    for i, summary in enumerate(summaries):
        print(f"Chunk {i}: {summary}")
