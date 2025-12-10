"""
Query Enhancement module for RAG system.
Implements query expansion and multi-query retrieval for better recall.
"""
import json
import logging
import os
from typing import List, Dict, Any


async def expand_query(query: str, num_variations: int = 3) -> List[str]:
    """
    Generate query variations using LLM for multi-query retrieval.
    
    This implements industry best practice of query expansion:
    - Original query may miss relevant documents due to terminology differences
    - LLM generates alternative phrasings that capture the same intent
    - Multiple queries improve recall without sacrificing precision
    
    Args:
        query: The original user query
        num_variations: Number of alternative queries to generate
        
    Returns:
        List of query strings including the original
    """
    try:
        from openai import AsyncAzureOpenAI
        
        client = AsyncAzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
        )
        
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        
        prompt = f"""Generate {num_variations} alternative search queries that capture the same information need as the original query.
Each alternative should:
- Use different words or phrases
- Approach the topic from a different angle
- Be a valid search query (not a question necessarily)

Original query: {query}

Return a JSON object with key "queries" containing an array of {num_variations} alternative query strings.
Example: {{"queries": ["alternative 1", "alternative 2", "alternative 3"]}}"""

        response = await client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        alternatives = result.get("queries", [])
        
        # Include original query + alternatives
        all_queries = [query] + alternatives
        
        logging.info(f"Query expanded: '{query}' -> {len(all_queries)} variations")
        return all_queries
        
    except Exception as e:
        logging.warning(f"Query expansion failed: {e}")
        return [query]  # Fallback to original query only


async def extract_query_keywords(query: str) -> Dict[str, Any]:
    """
    Extract key entities and keywords from a query for more targeted retrieval.
    
    Returns:
        Dict with 'entities', 'keywords', and 'intent' fields
    """
    try:
        from openai import AsyncAzureOpenAI
        
        client = AsyncAzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
        )
        
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        
        prompt = f"""Analyze this query and extract key information for document retrieval.

Query: {query}

Return a JSON object with:
- "entities": Array of named entities (codes, names, components)
- "keywords": Array of important search terms
- "intent": One of ["lookup", "count", "explain", "compare", "troubleshoot", "list"]
- "filters": Any specific filters implied (e.g., document type, date range)

Example: {{"entities": ["TCU", "0x8EF4"], "keywords": ["temperature", "error"], "intent": "troubleshoot", "filters": {{}}}}"""

        response = await client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=150,
            response_format={"type": "json_object"}
        )
        
        return json.loads(response.choices[0].message.content)
        
    except Exception as e:
        logging.warning(f"Query keyword extraction failed: {e}")
        return {"entities": [], "keywords": [], "intent": "lookup", "filters": {}}


def build_enhanced_search_text(query: str, keywords: Dict[str, Any]) -> str:
    """
    Build an enhanced search text that includes extracted keywords.
    This helps with keyword/BM25 matching.
    """
    parts = [query]
    
    # Add entities as exact match terms
    for entity in keywords.get("entities", []):
        if entity not in query:
            parts.append(entity)
    
    # Add keywords for broader matching
    for keyword in keywords.get("keywords", []):
        if keyword not in query.lower():
            parts.append(keyword)
    
    return " ".join(parts)


async def hypothetical_document_embedding(query: str) -> str:
    """
    Generate a hypothetical document that would answer the query (HyDE technique).
    
    This is useful for semantic search when the query terms don't match
    document terminology, but a hypothetical answer would.
    """
    try:
        from openai import AsyncAzureOpenAI
        
        client = AsyncAzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
        )
        
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        
        prompt = f"""Write a short paragraph (2-3 sentences) that would be the ideal answer to this question/query. 
Write as if from a technical document, not as a conversational response.

Query: {query}

Answer paragraph:"""

        response = await client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=150
        )
        
        hypothetical = response.choices[0].message.content.strip()
        logging.info(f"HyDE generated hypothetical document for: {query[:50]}...")
        return hypothetical
        
    except Exception as e:
        logging.warning(f"HyDE generation failed: {e}")
        return query  # Fallback to original query
