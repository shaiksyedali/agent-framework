"""
LLM-based Entity Extraction for Knowledge Graph construction.
Uses Azure OpenAI to extract entities and relationships from text chunks.
Designed for use with Azure Durable Functions for parallel processing.
"""
import logging
import os
import json
from typing import List, Dict, Any, Optional
from openai import AsyncAzureOpenAI


# Entity extraction prompt template - GENERIC for all document types
ENTITY_EXTRACTION_PROMPT = """Analyze this text and extract key entities and their relationships.

## Entity Types to Extract:
1. **IDENTIFIER**: Codes, IDs, reference numbers, serial numbers, alphanumeric identifiers
2. **COMPONENT**: Named objects, systems, parts, modules, tools, products, services
3. **CONCEPT**: Abstract ideas, states, conditions, categories, types, classifications
4. **VALUE**: Numbers with units, measurements, thresholds, specifications, quantities
5. **ACTION**: Processes, procedures, operations, steps, methods, activities
6. **ACTOR**: People, organizations, roles, departments, teams mentioned by name

## Output Format:
Return ONLY valid JSON with this structure:
{
    "entities": [
        {"name": "EXACT_TEXT", "type": "IDENTIFIER|COMPONENT|CONCEPT|VALUE|ACTION|ACTOR", "description": "1-line description"}
    ],
    "relationships": [
        {"source": "ENTITY1_NAME", "target": "ENTITY2_NAME", "type": "RELATES_TO|CAUSES|CONTAINS|USES|AFFECTS", "description": "how they relate"}
    ]
}

## Rules:
- Extract up to 15 most important/unique entities per text
- Use EXACT text as it appears (preserve case, formatting)
- Skip common words (the, a, is, system, data) unless part of a proper name
- Prioritize specific, identifiable items over generic terms
- Only include relationships explicitly stated in the text
- If no clear entities found, return empty arrays

## Text to analyze:
---
{text}
---

JSON:"""


async def extract_entities_llm(
    text: str,
    model: str = None,
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    Extract entities and relationships from text using Azure OpenAI.
    
    Args:
        text: The text chunk to analyze
        model: The model to use (defaults to AZURE_OPENAI_DEPLOYMENT env var)
        max_retries: Number of retries on failure
    
    Returns:
        Dict with 'entities' and 'relationships' lists
    """
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    # Support both AZURE_OPENAI_API_KEY (standard) and AZURE_OPENAI_KEY (legacy)
    api_key = os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_KEY")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    
    # Use environment variable for model deployment, with fallback
    if not model:
        model = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    
    if not endpoint or not api_key:
        logging.warning("Azure OpenAI not configured, skipping LLM entity extraction")
        return {"entities": [], "relationships": [], "error": "Not configured"}
    
    # Truncate very long text to avoid token limits
    max_chars = 8000  # ~2000-3000 tokens
    if len(text) > max_chars:
        text = text[:max_chars]
    
    client = AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version
    )
    
    prompt = ENTITY_EXTRACTION_PROMPT.format(text=text)
    
    for attempt in range(max_retries + 1):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a technical document analyzer that extracts entities and relationships. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Low temperature for consistent extraction
                max_tokens=2000,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content
            
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
                
                return {
                    "entities": valid_entities,
                    "relationships": valid_relationships,
                    "success": True
                }
                
            except json.JSONDecodeError as e:
                logging.warning(f"Failed to parse LLM response as JSON: {e}")
                if attempt < max_retries:
                    continue
                return {"entities": [], "relationships": [], "error": f"JSON parse error: {e}"}
                
        except Exception as e:
            logging.warning(f"LLM entity extraction failed (attempt {attempt + 1}): {e}")
            if attempt < max_retries:
                continue
            return {"entities": [], "relationships": [], "error": str(e)}
    
    return {"entities": [], "relationships": [], "error": "Max retries exceeded"}


async def extract_entities_batch(
    chunks: List[Dict[str, Any]],
    model: str = "gpt-4o-mini",
    batch_size: int = 10
) -> List[Dict[str, Any]]:
    """
    Extract entities from multiple chunks in parallel.
    
    Args:
        chunks: List of chunk dictionaries with 'content' field
        model: The model to use
        batch_size: Number of concurrent requests
    
    Returns:
        List of extraction results (same order as input chunks)
    """
    import asyncio
    
    results = []
    
    # Process in batches to avoid overwhelming the API
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        
        # Create tasks for parallel execution
        tasks = [
            extract_entities_llm(chunk.get("content", ""), model)
            for chunk in batch
        ]
        
        # Execute batch in parallel
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        for j, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logging.warning(f"Chunk {i + j} extraction failed: {result}")
                results.append({"entities": [], "relationships": [], "error": str(result)})
            else:
                results.append(result)
    
    return results


def merge_entities(all_extractions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge entities and relationships from multiple chunks.
    Deduplicates by entity name (case-insensitive).
    
    Args:
        all_extractions: List of extraction results from each chunk
    
    Returns:
        Merged dict with deduplicated entities and relationships
    """
    seen_entities = {}
    all_relationships = []
    
    # Entity type priority (higher = preferred when merging)
    # IDENTIFIER is highest priority (most specific), CONCEPT is lowest
    type_priority = {
        "IDENTIFIER": 4, 
        "COMPONENT": 3, 
        "ACTOR": 3,
        "ACTION": 2, 
        "VALUE": 2, 
        "CONCEPT": 1
    }
    
    for extraction in all_extractions:
        entities = extraction.get("entities", [])
        relationships = extraction.get("relationships", [])
        
        for entity in entities:
            name = entity.get("name", "").strip()
            name_lower = name.lower()
            
            if not name or len(name) < 2:
                continue
            
            entity_type = entity.get("type", "CONCEPT")
            priority = type_priority.get(entity_type, 0)
            
            # Keep the entity with higher priority type
            if name_lower not in seen_entities or priority > seen_entities[name_lower]["priority"]:
                seen_entities[name_lower] = {
                    "entity": entity,
                    "priority": priority
                }
        
        # Add relationships (allow duplicates for now, could deduplicate later)
        all_relationships.extend(relationships)
    
    return {
        "entities": [item["entity"] for item in seen_entities.values()],
        "relationships": all_relationships,
        "total_unique_entities": len(seen_entities)
    }
