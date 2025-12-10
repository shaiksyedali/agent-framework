"""
Semantic Chunking module for RAG system.
Splits documents at natural semantic boundaries instead of fixed character counts.
"""
import logging
import os
import re
from typing import List, Dict, Any, Tuple


def split_into_sentences(text: str) -> List[str]:
    """
    Split text into sentences using regex patterns.
    Handles common abbreviations and edge cases.
    """
    # Pattern for sentence boundaries
    sentence_pattern = r'(?<=[.!?])\s+(?=[A-Z])'
    
    # Split on sentence boundaries
    sentences = re.split(sentence_pattern, text)
    
    # Clean and filter
    sentences = [s.strip() for s in sentences if s.strip()]
    
    return sentences


async def compute_sentence_embeddings(sentences: List[str]) -> List[List[float]]:
    """
    Generate embeddings for sentences using Azure OpenAI.
    """
    from openai import AsyncAzureOpenAI
    
    client = AsyncAzureOpenAI(
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
    )
    
    # Batch embed sentences
    response = await client.embeddings.create(
        input=sentences,
        model=os.environ.get("AZURE_EMBED_DEPLOYMENT", "text-embedding-3-small"),
        dimensions=int(os.environ.get("AZURE_EMBED_DIM", "1536"))
    )
    
    await client.close()
    return [item.embedding for item in response.data]


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / (norm1 * norm2)


def find_semantic_breakpoints(
    similarities: List[float], 
    threshold: float = 0.5,
    min_chunk_size: int = 3
) -> List[int]:
    """
    Find indices where semantic similarity drops below threshold.
    These are natural breakpoints for chunking.
    
    Args:
        similarities: List of similarity scores between adjacent sentences
        threshold: Similarity threshold below which to create a breakpoint
        min_chunk_size: Minimum number of sentences per chunk
        
    Returns:
        List of indices where chunks should be split
    """
    breakpoints = []
    last_breakpoint = 0
    
    for i, sim in enumerate(similarities):
        # Check if similarity is below threshold and min chunk size is met
        if sim < threshold and (i - last_breakpoint) >= min_chunk_size:
            breakpoints.append(i + 1)  # +1 because we want to split after this sentence
            last_breakpoint = i + 1
    
    return breakpoints


async def semantic_chunk_text(
    text: str,
    threshold: float = 0.5,
    min_chunk_sentences: int = 3,
    max_chunk_sentences: int = 20,
    fallback_chunk_chars: int = 2000
) -> List[Dict[str, Any]]:
    """
    Split text into chunks at natural semantic boundaries.
    
    This implements industry best practice semantic chunking:
    1. Split text into sentences
    2. Compute embeddings for each sentence
    3. Find points where semantic similarity drops (topic changes)
    4. Create chunks at these natural boundaries
    
    Args:
        text: The text to chunk
        threshold: Similarity threshold (0-1). Lower = more aggressive splitting
        min_chunk_sentences: Minimum sentences per chunk
        max_chunk_sentences: Maximum sentences per chunk (force break)
        fallback_chunk_chars: Fallback character-based chunking if semantic fails
        
    Returns:
        List of chunk dicts with chunk_id and content
    """
    try:
        # 1. Split into sentences
        sentences = split_into_sentences(text)
        
        if len(sentences) <= 3:
            # Too few sentences for semantic chunking, return as single chunk
            return [{"chunk_id": 0, "content": text.strip()}]
        
        # 2. Compute embeddings for all sentences (batched)
        embeddings = await compute_sentence_embeddings(sentences)
        
        # 3. Calculate similarity between adjacent sentences
        similarities = []
        for i in range(len(embeddings) - 1):
            sim = cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append(sim)
        
        # 4. Find semantic breakpoints
        breakpoints = find_semantic_breakpoints(
            similarities, 
            threshold=threshold,
            min_chunk_size=min_chunk_sentences
        )
        
        # 5. Create chunks from breakpoints
        chunks = []
        chunk_id = 0
        prev_break = 0
        
        for breakpoint in breakpoints:
            # Handle max chunk size
            while breakpoint - prev_break > max_chunk_sentences:
                end_idx = prev_break + max_chunk_sentences
                chunk_content = " ".join(sentences[prev_break:end_idx])
                chunks.append({
                    "chunk_id": chunk_id,
                    "content": chunk_content.strip()
                })
                chunk_id += 1
                prev_break = end_idx
            
            chunk_content = " ".join(sentences[prev_break:breakpoint])
            if chunk_content.strip():
                chunks.append({
                    "chunk_id": chunk_id,
                    "content": chunk_content.strip()
                })
                chunk_id += 1
            prev_break = breakpoint
        
        # Add remaining sentences as final chunk
        if prev_break < len(sentences):
            chunk_content = " ".join(sentences[prev_break:])
            if chunk_content.strip():
                chunks.append({
                    "chunk_id": chunk_id,
                    "content": chunk_content.strip()
                })
        
        logging.info(f"Semantic chunking: {len(sentences)} sentences -> {len(chunks)} chunks")
        return chunks
        
    except Exception as e:
        logging.warning(f"Semantic chunking failed, falling back to character-based: {e}")
        return fallback_character_chunk(text, fallback_chunk_chars)


def fallback_character_chunk(text: str, chunk_size: int = 2000, overlap: int = 200) -> List[Dict[str, Any]]:
    """
    Fallback character-based chunking when semantic chunking fails.
    Uses sentence boundaries when possible.
    """
    chunks = []
    start = 0
    chunk_id = 0
    
    while start < len(text):
        end = start + chunk_size
        chunk_content = text[start:end]
        
        # Try to end at a sentence boundary
        if end < len(text):
            for sep in ['. ', '.\n', '? ', '!\n', '\n\n']:
                last_sep = chunk_content.rfind(sep)
                if last_sep > chunk_size - 200:
                    end = start + last_sep + len(sep)
                    chunk_content = text[start:end]
                    break
        
        chunks.append({
            "chunk_id": chunk_id,
            "content": chunk_content.strip()
        })
        
        chunk_id += 1
        start = end - overlap
        
        if start >= len(text):
            break
    
    return chunks


def paragraph_chunk_text(text: str, min_chunk_chars: int = 500, max_chunk_chars: int = 3000) -> List[Dict[str, Any]]:
    """
    Alternative chunking strategy: Split on paragraph boundaries.
    Good for well-structured documents.
    
    Args:
        text: Text to chunk
        min_chunk_chars: Minimum characters per chunk (combines small paragraphs)
        max_chunk_chars: Maximum characters per chunk (splits large paragraphs)
    """
    # Split on double newlines (paragraphs)
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    
    chunks = []
    current_chunk = ""
    chunk_id = 0
    
    for para in paragraphs:
        # If adding this paragraph would exceed max, save current and start new
        if len(current_chunk) + len(para) > max_chunk_chars and current_chunk:
            chunks.append({
                "chunk_id": chunk_id,
                "content": current_chunk.strip()
            })
            chunk_id += 1
            current_chunk = para
        else:
            current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
        
        # If we've reached min size and paragraph ends, that's a natural break
        if len(current_chunk) >= min_chunk_chars:
            chunks.append({
                "chunk_id": chunk_id,
                "content": current_chunk.strip()
            })
            chunk_id += 1
            current_chunk = ""
    
    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            "chunk_id": chunk_id,
            "content": current_chunk.strip()
        })
    
    return chunks
