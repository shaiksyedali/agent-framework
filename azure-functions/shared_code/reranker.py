"""
Reranker module for RAG system.
Uses LLM to score and rerank retrieved documents by relevance to query.
"""
import json
import logging
import os
from typing import List, Dict, Any


async def rerank_documents(
    query: str, 
    documents: List[Dict[str, Any]], 
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """
    Rerank documents using LLM-based relevance scoring.
    
    This implements industry best practice of re-ranking after initial retrieval
    to improve precision and ensure most relevant documents are prioritized.
    
    Args:
        query: The user's search query
        documents: List of documents from initial retrieval
        top_k: Number of top documents to return after reranking
        
    Returns:
        Reranked list of documents with added relevance scores
    """
    if not documents:
        return []
    
    # Skip reranking if we have few documents
    if len(documents) <= 3:
        return documents
        
    try:
        from openai import AsyncAzureOpenAI
        
        client = AsyncAzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
        )
        
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        
        # Prepare document summaries for scoring
        doc_summaries = []
        for i, doc in enumerate(documents[:20]):  # Limit to 20 for token efficiency
            summary = doc.get("summary") or doc.get("content", "")[:500]
            title = doc.get("title", f"Document {i+1}")
            doc_summaries.append(f"[{i}] {title}: {summary}")
        
        prompt = f"""You are a document relevance scorer. Score each document's relevance to the query on a scale of 0-10.

Query: {query}

Documents:
{chr(10).join(doc_summaries)}

Return a JSON object with document indices as keys and relevance scores as values.
Only include documents with score >= 3.
Example: {{"0": 8, "2": 7, "5": 6}}

Score based on:
- Direct relevance to the query
- Completeness of information
- Specificity to the question asked

Return ONLY the JSON object, no explanation."""

        response = await client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
            response_format={"type": "json_object"}
        )
        
        scores = json.loads(response.choices[0].message.content)
        
        # Apply scores to documents
        scored_docs = []
        for idx_str, score in scores.items():
            try:
                idx = int(idx_str)
                if 0 <= idx < len(documents):
                    doc = documents[idx].copy()
                    doc["rerank_score"] = score
                    scored_docs.append(doc)
            except (ValueError, IndexError):
                continue
        
        # Sort by rerank score descending
        scored_docs.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        
        # Add any documents not scored (with low priority)
        scored_indices = {int(k) for k in scores.keys() if k.isdigit()}
        for i, doc in enumerate(documents):
            if i not in scored_indices and len(scored_docs) < top_k:
                doc_copy = doc.copy()
                doc_copy["rerank_score"] = 0
                scored_docs.append(doc_copy)
        
        logging.info(f"Reranked {len(documents)} documents, returning top {min(top_k, len(scored_docs))}")
        return scored_docs[:top_k]
        
    except Exception as e:
        logging.warning(f"Reranking failed, returning original order: {e}")
        return documents[:top_k]


async def score_single_document(query: str, document: Dict[str, Any]) -> float:
    """
    Score a single document's relevance to a query.
    Useful for filtering or threshold-based decisions.
    
    Args:
        query: The search query
        document: The document to score
        
    Returns:
        Relevance score from 0.0 to 1.0
    """
    try:
        from openai import AsyncAzureOpenAI
        
        client = AsyncAzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
        )
        
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        
        content = document.get("content", "")[:1000]
        title = document.get("title", "Untitled")
        
        prompt = f"""Rate the relevance of this document to the query on a scale of 0.0 to 1.0.
        
Query: {query}

Document Title: {title}
Document Content: {content}

Return only a number between 0.0 and 1.0."""

        response = await client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10
        )
        
        score_text = response.choices[0].message.content.strip()
        return float(score_text)
        
    except Exception as e:
        logging.warning(f"Single document scoring failed: {e}")
        return 0.5  # Default neutral score
