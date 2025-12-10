"""
LLM Response Cache for Entity Extraction

Simple file-based caching to avoid re-processing identical chunks.
Uses content hash as cache key.
"""
import os
import json
import hashlib
import logging
from typing import Optional, Dict, Any
from azure.storage.blob import BlobServiceClient


# Cache settings from environment
CACHE_ENABLED = os.environ.get("ENABLE_LLM_CACHE", "true").lower() == "true"
CACHE_CONTAINER = os.environ.get("LLM_CACHE_CONTAINER", "llm-cache")


def _get_content_hash(content: str) -> str:
    """Generate a hash for content to use as cache key."""
    return hashlib.md5(content.encode()).hexdigest()


def _get_blob_client():
    """Get Azure Blob Storage client for caching."""
    connection_string = os.environ.get("AzureWebJobsStorage")
    if not connection_string:
        return None
    
    try:
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service.get_container_client(CACHE_CONTAINER)
        
        # Create container if it doesn't exist
        if not container_client.exists():
            container_client.create_container()
        
        return container_client
    except Exception as e:
        logging.warning(f"Failed to initialize blob cache: {e}")
        return None


def get_cached_extraction(content: str) -> Optional[Dict[str, Any]]:
    """
    Get cached entity extraction result for content.
    
    Args:
        content: The text content to look up
        
    Returns:
        Cached result dict or None if not found
    """
    if not CACHE_ENABLED:
        return None
    
    try:
        container = _get_blob_client()
        if not container:
            return None
        
        content_hash = _get_content_hash(content)
        blob_name = f"entity_cache/{content_hash}.json"
        
        blob_client = container.get_blob_client(blob_name)
        if blob_client.exists():
            data = blob_client.download_blob().readall()
            result = json.loads(data)
            logging.info(f"Cache HIT for content hash {content_hash[:8]}...")
            return result
        
        return None
        
    except Exception as e:
        logging.warning(f"Cache read error: {e}")
        return None


def cache_extraction(content: str, result: Dict[str, Any]) -> bool:
    """
    Cache an entity extraction result.
    
    Args:
        content: The text content
        result: The extraction result to cache
        
    Returns:
        True if cached successfully
    """
    if not CACHE_ENABLED:
        return False
    
    try:
        container = _get_blob_client()
        if not container:
            return False
        
        content_hash = _get_content_hash(content)
        blob_name = f"entity_cache/{content_hash}.json"
        
        blob_client = container.get_blob_client(blob_name)
        blob_client.upload_blob(
            json.dumps(result),
            overwrite=True
        )
        logging.info(f"Cache WRITE for content hash {content_hash[:8]}...")
        return True
        
    except Exception as e:
        logging.warning(f"Cache write error: {e}")
        return False


def clear_cache() -> int:
    """
    Clear all cached extraction results.
    
    Returns:
        Number of cached items deleted
    """
    try:
        container = _get_blob_client()
        if not container:
            return 0
        
        deleted = 0
        blobs = container.list_blobs(name_starts_with="entity_cache/")
        for blob in blobs:
            container.delete_blob(blob.name)
            deleted += 1
        
        logging.info(f"Cleared {deleted} cached extraction results")
        return deleted
        
    except Exception as e:
        logging.warning(f"Cache clear error: {e}")
        return 0
