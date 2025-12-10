"""
Document Indexer for Azure AI Search
Handles PDF parsing, text chunking, embedding generation, and indexing.
"""

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from azure.core.credentials import AzureKeyCredential

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 200) -> List[Dict[str, Any]]:
    """
    Split text into overlapping chunks for better RAG retrieval.
    
    Args:
        text: Full text to chunk
        chunk_size: Target size of each chunk in tokens (approx 4 chars per token)
        overlap: Number of characters to overlap between chunks
    
    Returns:
        List of chunk dictionaries with content and metadata
    """
    # Approximate: 4 characters per token
    char_chunk_size = chunk_size * 4
    char_overlap = overlap * 4
    
    chunks = []
    start = 0
    chunk_id = 0
    
    while start < len(text):
        end = start + char_chunk_size
        chunk_content = text[start:end]
        
        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence ending within last 200 chars
            for sep in ['. ', '.\n', '? ', '!\n', '\n\n']:
                last_sep = chunk_content.rfind(sep)
                if last_sep > char_chunk_size - 200:
                    end = start + last_sep + len(sep)
                    chunk_content = text[start:end]
                    break
        
        chunks.append({
            "chunk_id": chunk_id,
            "content": chunk_content.strip(),
            "char_start": start,
            "char_end": end
        })
        
        chunk_id += 1
        start = end - char_overlap
        
        if start >= len(text):
            break
    
    return chunks


def extract_text_from_pdf(file_path: str) -> List[Dict[str, Any]]:
    """
    Extract text from PDF file, page by page.
    
    Returns:
        List of pages with content and page numbers
    """
    try:
        import pypdf
    except ImportError:
        logger.warning("pypdf not installed, trying PyPDF2")
        try:
            import PyPDF2 as pypdf
        except ImportError:
            raise ImportError("Neither pypdf nor PyPDF2 is installed. Run: pip install pypdf")
    
    pages = []
    
    with open(file_path, 'rb') as f:
        reader = pypdf.PdfReader(f)
        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append({
                    "page_number": page_num,
                    "content": text
                })
    
    return pages


async def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding for text using Azure OpenAI.
    """
    from openai import AsyncAzureOpenAI
    
    client = AsyncAzureOpenAI(
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
    )
    
    response = await client.embeddings.create(
        input=text[:8000],  # Limit input to avoid token limits
        model=os.environ.get("AZURE_EMBED_DEPLOYMENT", "text-embedding-3-small"),
        dimensions=int(os.environ.get("AZURE_EMBED_DIM", "1536"))
    )
    
    await client.close()
    return response.data[0].embedding


async def index_document(
    file_path: str,
    workflow_id: str,
    file_name: Optional[str] = None,
    index_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parse, chunk, embed, and index a document into Azure AI Search.
    
    Args:
        file_path: Path to the document file
        workflow_id: Workflow ID for filtering
        file_name: Optional display name for the file
        index_name: Target index (defaults to env var)
    
    Returns:
        Dictionary with indexing results
    """
    from azure.search.documents.aio import SearchClient
    
    # Configuration
    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    search_key = os.environ.get("AZURE_SEARCH_KEY") or os.environ.get("AZURE_SEARCH_API_KEY")
    
    if not index_name:
        index_name = os.environ.get("AZURE_SEARCH_INDEX", "schema-docs")
    
    if not search_endpoint or not search_key:
        return {"success": False, "error": "AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_KEY not set"}
    
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}
    
    if not file_name:
        file_name = path.name
    
    logger.info(f"Indexing document: {file_name} for workflow {workflow_id}")
    
    try:
        # 1. Extract text based on file type
        ext = path.suffix.lower()
        
        if ext == ".pdf":
            pages = extract_text_from_pdf(file_path)
        elif ext in [".txt", ".md", ".csv"]:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            pages = [{"page_number": 1, "content": content}]
        else:
            return {"success": False, "error": f"Unsupported file type: {ext}"}
        
        if not pages:
            return {"success": False, "error": "No text content extracted from file"}
        
        # 2. Chunk and prepare documents
        documents = []
        created_at = datetime.utcnow().isoformat()
        
        for page in pages:
            chunks = chunk_text(page["content"])
            
            for chunk in chunks:
                doc_id = f"{workflow_id}-{file_name}-p{page['page_number']}-c{chunk['chunk_id']}"
                doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))
                
                # Generate embedding
                embedding = await generate_embedding(chunk["content"])
                
                documents.append({
                    "id": doc_id,
                    "workflow_id": workflow_id,
                    "file_name": file_name,
                    "title": f"{file_name} - Page {page['page_number']}",
                    "content": chunk["content"],
                    "content_vector": embedding,
                    "source": file_path,
                    "page_number": page["page_number"],
                    "chunk_id": str(chunk["chunk_id"]),
                    "created_at": created_at
                })
        
        logger.info(f"Generated {len(documents)} chunks from {len(pages)} pages")
        
        # 3. Upload to Azure AI Search
        credential = AzureKeyCredential(search_key)
        async with SearchClient(search_endpoint, index_name, credential) as client:
            # Upload in batches of 100
            batch_size = 100
            uploaded = 0
            
            for i in range(0, len(documents), batch_size):
                batch = documents[i:i + batch_size]
                result = await client.upload_documents(batch)
                uploaded += len([r for r in result if r.succeeded])
        
        logger.info(f"Successfully indexed {uploaded}/{len(documents)} chunks")
        
        return {
            "success": True,
            "workflow_id": workflow_id,
            "file_name": file_name,
            "pages": len(pages),
            "chunks": len(documents),
            "indexed": uploaded
        }
    
    except Exception as e:
        logger.error(f"Error indexing document: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def delete_workflow_documents(workflow_id: str, index_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Delete all documents for a specific workflow (cleanup).
    """
    from azure.search.documents.aio import SearchClient
    
    search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    search_key = os.environ.get("AZURE_SEARCH_KEY") or os.environ.get("AZURE_SEARCH_API_KEY")
    
    if not index_name:
        index_name = os.environ.get("AZURE_SEARCH_INDEX", "schema-docs")
    
    try:
        credential = AzureKeyCredential(search_key)
        async with SearchClient(search_endpoint, index_name, credential) as client:
            # Find all documents for this workflow
            results = client.search(
                search_text="*",
                filter=f"workflow_id eq '{workflow_id}'",
                select=["id"]
            )
            
            doc_ids = [doc["id"] async for doc in results]
            
            if doc_ids:
                # Delete documents
                await client.delete_documents([{"id": doc_id} for doc_id in doc_ids])
                return {"success": True, "deleted": len(doc_ids)}
            
            return {"success": True, "deleted": 0}
    
    except Exception as e:
        logger.error(f"Error deleting workflow documents: {e}")
        return {"success": False, "error": str(e)}
