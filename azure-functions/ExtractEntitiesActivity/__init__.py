"""
Extract Entities Activity - Durable Activity Function

Extracts entities from a single chunk using LLM.
Called in parallel by the orchestrator.
"""
import logging
import os
import json
from openai import AzureOpenAI  # Use sync client instead of async


def main(input: dict) -> dict:
    """
    Activity function that extracts entities from a single chunk using LLM.
    
    Input:
    {
        "content": "text content",
        "chunk_id": "chunk_0",
        "page_number": 1
    }
    
    Output:
    {
        "chunk_id": "chunk_0",
        "page_number": 1,
        "entities": [...],
        "relationships": [...],
        "success": true
    }
    """
    content = input.get("content", "")
    chunk_id = input.get("chunk_id", "unknown")
    page_number = input.get("page_number", 0)
    
    # Skip very short chunks
    if not content or len(content.strip()) < 50:
        logging.info(f"Chunk {chunk_id}: Content too short ({len(content)} chars), skipping")
        return {
            "chunk_id": chunk_id,
            "page_number": page_number,
            "entities": [],
            "relationships": [],
            "skipped": True,
            "reason": "Content too short"
        }
    
    # Check cache first (LightRAG-style optimization)
    try:
        from shared_code.llm_cache import get_cached_extraction, cache_extraction
        cached_result = get_cached_extraction(content)
        if cached_result:
            logging.info(f"Chunk {chunk_id}: Cache HIT - skipping LLM call")
            return {
                "chunk_id": chunk_id,
                "page_number": page_number,
                "entities": cached_result.get("entities", []),
                "relationships": cached_result.get("relationships", []),
                "success": True,
                "cached": True
            }
    except Exception as cache_err:
        logging.warning(f"Cache check failed: {cache_err}")
    
    # Get configuration from environment
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_KEY")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    model = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    
    if not endpoint or not api_key:
        logging.error(f"Chunk {chunk_id}: Azure OpenAI not configured (endpoint={bool(endpoint)}, key={bool(api_key)})")
        return {
            "chunk_id": chunk_id,
            "page_number": page_number,
            "entities": [],
            "relationships": [],
            "error": "Azure OpenAI not configured"
        }
    
    # Truncate very long text to avoid token limits
    max_chars = 6000  # ~1500-2000 tokens
    if len(content) > max_chars:
        content = content[:max_chars]
    
    # Entity extraction prompt
    prompt = f"""Analyze this text and extract key entities and their relationships.

## Entity Types to Extract:
1. **IDENTIFIER**: Codes, IDs, reference numbers, serial numbers, alphanumeric identifiers
2. **COMPONENT**: Named objects, systems, parts, modules, tools, products, services
3. **CONCEPT**: Abstract ideas, states, conditions, categories, types, classifications
4. **VALUE**: Numbers with units, measurements, thresholds, specifications, quantities
5. **ACTION**: Processes, procedures, operations, steps, methods, activities
6. **ACTOR**: People, organizations, roles, departments, teams mentioned by name

## Output Format:
Return ONLY valid JSON with this structure:
{{
    "entities": [
        {{"name": "EXACT_TEXT", "type": "IDENTIFIER|COMPONENT|CONCEPT|VALUE|ACTION|ACTOR", "description": "1-line description"}}
    ],
    "relationships": [
        {{"source": "ENTITY1_NAME", "target": "ENTITY2_NAME", "type": "RELATES_TO|CAUSES|CONTAINS|USES|AFFECTS", "description": "how they relate"}}
    ]
}}

## Rules:
- Extract up to 15 most important/unique entities per text
- Use EXACT text as it appears (preserve case, formatting)
- Skip common words (the, a, is, system, data) unless part of a proper name
- Prioritize specific, identifiable items over generic terms
- Only include relationships explicitly stated in the text
- If no clear entities found, return empty arrays

## Text to analyze:
---
{content}
---

JSON:"""

    try:
        # Use synchronous client (works better in Durable Functions activities)
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version
        )
        
        logging.info(f"Chunk {chunk_id}: Calling LLM ({model}) with {len(content)} chars")
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a document analyzer that extracts entities and relationships. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1000,  # Reduced for faster responses
            response_format={"type": "json_object"}
        )
        
        result_text = response.choices[0].message.content
        logging.info(f"Chunk {chunk_id}: LLM response received ({len(result_text)} chars)")
        
        # Parse JSON response
        try:
            result = json.loads(result_text)
            entities = result.get("entities", [])
            relationships = result.get("relationships", [])
            
            # Validate entity structure
            valid_entities = []
            for e in entities:
                if isinstance(e, dict) and e.get("name") and e.get("type"):
                    valid_entities.append({
                        "name": str(e["name"]).strip(),
                        "type": str(e["type"]).upper(),
                        "description": str(e.get("description", "")),
                        "source": "llm_extraction"
                    })
            
            # Validate relationship structure
            valid_relationships = []
            for r in relationships:
                if isinstance(r, dict) and r.get("source") and r.get("target"):
                    valid_relationships.append({
                        "source": str(r["source"]).strip(),
                        "target": str(r["target"]).strip(),
                        "type": str(r.get("type", "RELATES_TO")).upper(),
                        "description": str(r.get("description", ""))
                    })
            
            logging.info(f"Chunk {chunk_id}: Extracted {len(valid_entities)} entities, {len(valid_relationships)} relationships")
            
            # Cache the result for future use
            try:
                cache_extraction(content, {
                    "entities": valid_entities,
                    "relationships": valid_relationships
                })
            except Exception as cache_err:
                logging.warning(f"Failed to cache result: {cache_err}")
            
            return {
                "chunk_id": chunk_id,
                "page_number": page_number,
                "entities": valid_entities,
                "relationships": valid_relationships,
                "success": True
            }
            
        except json.JSONDecodeError as e:
            logging.warning(f"Chunk {chunk_id}: JSON parse error: {e}")
            return {
                "chunk_id": chunk_id,
                "page_number": page_number,
                "entities": [],
                "relationships": [],
                "error": f"JSON parse error: {e}"
            }
            
    except Exception as e:
        logging.error(f"Chunk {chunk_id}: LLM extraction failed: {e}")
        return {
            "chunk_id": chunk_id,
            "page_number": page_number,
            "entities": [],
            "relationships": [],
            "error": str(e)
        }
