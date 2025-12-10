"""
Azure Document Intelligence module for robust document extraction.
Supports multiple formats: PDF, images, Office docs, and text files.
Uses Azure's prebuilt-layout model for comprehensive extraction.
"""
import logging
import os
import asyncio
from typing import List, Dict, Any, Optional, Tuple
import json


# Supported file formats by category
STRUCTURED_FORMATS = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
    "bmp": "image/bmp",
    "heif": "image/heif"
}

OFFICE_FORMATS = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
}

TEXT_FORMATS = {"txt", "md", "csv", "json", "xml", "html", "yml", "yaml"}


def get_format_category(file_type: str) -> str:
    """
    Determine the processing category for a file type.
    Returns: 'structured', 'office', 'text', or 'unsupported'
    """
    file_type = file_type.lower().strip('.')
    
    if file_type in STRUCTURED_FORMATS:
        return "structured"
    elif file_type in OFFICE_FORMATS:
        return "office"
    elif file_type in TEXT_FORMATS:
        return "text"
    else:
        return "unsupported"


async def extract_with_document_intelligence(
    content: bytes,
    file_type: str,
    file_name: str = "document"
) -> Dict[str, Any]:
    """
    Extract content and entities from documents using Azure Document Intelligence.
    
    This uses the prebuilt-layout model which extracts:
    - Text content with reading order
    - Tables with rows and cells
    - Key-value pairs
    - Selection marks (checkboxes)
    - Figures and their captions
    
    Args:
        content: Raw bytes of the document
        file_type: File extension (pdf, png, docx, etc.)
        file_name: Name of the file for logging
        
    Returns:
        Dict with extracted content, tables, key_value_pairs, and entities
    """
    endpoint = os.environ.get("AZURE_DOC_INTELLIGENCE_ENDPOINT")
    key = os.environ.get("AZURE_DOC_INTELLIGENCE_KEY")
    
    # Check if Document Intelligence is configured
    if not endpoint or not key:
        logging.warning("Azure Document Intelligence not configured, falling back to basic extraction")
        return {"success": False, "error": "Document Intelligence not configured"}
    
    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentAnalysisFeature
        from azure.core.credentials import AzureKeyCredential
        
        client = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key)
        )
        
        # Choose the appropriate content type
        file_type_lower = file_type.lower().strip('.')
        
        if file_type_lower in STRUCTURED_FORMATS:
            content_type = STRUCTURED_FORMATS[file_type_lower]
        elif file_type_lower in OFFICE_FORMATS:
            content_type = OFFICE_FORMATS[file_type_lower]
        else:
            logging.warning(f"Unsupported format {file_type} for Document Intelligence")
            return {"success": False, "error": f"Unsupported format: {file_type}"}
        
        # Analyze document with prebuilt-layout model
        # This extracts text, tables, key-value pairs, and more
        poller = client.begin_analyze_document(
            model_id="prebuilt-layout",
            analyze_request=AnalyzeDocumentRequest(bytes_source=content),
            content_type=content_type,
            features=[DocumentAnalysisFeature.KEY_VALUE_PAIRS]  # Enable KV extraction
        )
        
        result = poller.result()
        
        # Extract all content
        extracted = {
            "success": True,
            "pages": [],
            "tables": [],
            "key_value_pairs": [],
            "entities": [],
            "full_text": ""
        }
        
        # 1. Extract text content per page
        all_text = []
        if result.pages:
            for page in result.pages:
                page_text = ""
                if page.lines:
                    page_text = "\n".join(line.content for line in page.lines)
                extracted["pages"].append({
                    "page_number": page.page_number,
                    "content": page_text,
                    "width": page.width,
                    "height": page.height
                })
                all_text.append(page_text)
        
        extracted["full_text"] = "\n\n".join(all_text)
        
        # 2. Extract tables as structured data
        if result.tables:
            for table_idx, table in enumerate(result.tables):
                table_data = {
                    "table_id": table_idx,
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                    "cells": [],
                    "rows": []
                }
                
                # Organize cells into rows
                rows = {}
                for cell in table.cells:
                    row_idx = cell.row_index
                    if row_idx not in rows:
                        rows[row_idx] = {}
                    rows[row_idx][cell.column_index] = cell.content
                    
                    table_data["cells"].append({
                        "row": row_idx,
                        "column": cell.column_index,
                        "content": cell.content,
                        "is_header": getattr(cell, 'kind', None) == 'columnHeader'
                    })
                
                # Convert to row list
                for row_idx in sorted(rows.keys()):
                    row_cells = [rows[row_idx].get(i, "") for i in range(table.column_count)]
                    table_data["rows"].append(row_cells)
                
                extracted["tables"].append(table_data)
                
                # Extract entities from table cells
                extract_entities_from_table(table_data, extracted["entities"])
        
        # 3. Extract key-value pairs
        if result.key_value_pairs:
            for kv in result.key_value_pairs:
                key_content = kv.key.content if kv.key else ""
                value_content = kv.value.content if kv.value else ""
                
                extracted["key_value_pairs"].append({
                    "key": key_content,
                    "value": value_content,
                    "confidence": kv.confidence
                })
                
                # Add key-value pairs as entities
                if value_content.strip():
                    extracted["entities"].append({
                        "name": value_content.strip(),
                        "type": categorize_entity(value_content, key_content),
                        "description": f"Value for: {key_content}",
                        "source": "document_intelligence_kv"
                    })
        
        # 4. Build table_text for chunk detection
        # This contains all unique text from table cells
        table_text_set = set()
        for table in extracted["tables"]:
            for row in table.get("rows", []):
                for cell in row:
                    if cell and len(cell.strip()) > 3:  # Skip short/empty cells
                        table_text_set.add(cell.strip().lower())
        extracted["table_text"] = table_text_set
        
        # 5. Build structured_phrases for matching (longer identifiers)
        structured_phrases = set()
        for entity in extracted["entities"]:
            name = entity.get("name", "").strip()
            if len(name) > 5:  # Only significant identifiers
                structured_phrases.add(name.lower())
        extracted["structured_phrases"] = structured_phrases
        
        logging.info(f"Document Intelligence extracted: {len(extracted['pages'])} pages, "
                    f"{len(extracted['tables'])} tables, {len(extracted['key_value_pairs'])} KV pairs, "
                    f"{len(extracted['entities'])} entities, {len(table_text_set)} table phrases from {file_name}")
        
        return extracted
        
    except ImportError:
        logging.warning("azure-ai-documentintelligence not installed")
        return {"success": False, "error": "azure-ai-documentintelligence package not installed"}
    except Exception as e:
        logging.error(f"Document Intelligence extraction failed: {e}")
        return {"success": False, "error": str(e)}


def extract_entities_from_table(table_data: Dict, entities: List[Dict]) -> None:
    """
    Extract entities from table cells.
    Uses headers to determine entity types.
    """
    if not table_data.get("rows") or len(table_data["rows"]) < 2:
        return
    
    # First row is typically headers
    headers = table_data["rows"][0]
    
    # Process remaining rows
    for row_idx, row in enumerate(table_data["rows"][1:], start=1):
        for col_idx, cell_value in enumerate(row):
            if not cell_value or not cell_value.strip():
                continue
            
            # Get header for context
            header = headers[col_idx] if col_idx < len(headers) else ""
            
            # Categorize based on header and value
            entity_type = categorize_entity(cell_value, header)
            
            # Skip generic values
            if entity_type == "SKIP":
                continue
            
            entities.append({
                "name": cell_value.strip(),
                "type": entity_type,
                "description": f"From table column: {header}" if header else "Table cell value",
                "source": "document_intelligence_table"
            })


def categorize_entity(value: str, context: str = "") -> str:
    """
    Categorize an entity based on its value and context.
    Returns entity type or 'SKIP' if not a meaningful entity.
    """
    value = value.strip()
    context = context.lower() if context else ""
    
    # Skip common non-entity values
    skip_patterns = {
        "", "n/a", "na", "none", "-", "/", "yes", "no", "true", "false",
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"
    }
    if value.lower() in skip_patterns:
        return "SKIP"
    
    # Check for patterns that indicate codes
    # Hex values
    if value.startswith("0x") or value.startswith("0X"):
        return "CODE"
    
    # Contains underscore (likely an identifier)
    if "_" in value and len(value) > 3:
        return "CODE"
    
    # Contains dots with uppercase (like J1939.Component.Error)
    if "." in value and any(c.isupper() for c in value):
        return "CODE"
    
    # All uppercase with numbers (likely an identifier)
    if value.isupper() and any(c.isdigit() for c in value):
        return "CODE"
    
    # Check context for hints
    code_hints = {"code", "dtc", "error", "fault", "id", "identifier", "number", "hex"}
    if any(hint in context for hint in code_hints):
        return "CODE"
    
    component_hints = {"component", "module", "sensor", "controller", "unit", "system"}
    if any(hint in context for hint in component_hints):
        return "COMPONENT"
    
    value_hints = {"value", "voltage", "current", "temperature", "pressure", "threshold"}
    if any(hint in context for hint in value_hints):
        return "VALUE"
    
    # Default to CONCEPT for other text
    if len(value) > 2 and any(c.isalpha() for c in value):
        return "CONCEPT"
    
    return "SKIP"


def chunk_has_structured_content(
    chunk_content: str,
    table_text: set,
    structured_phrases: set,
    threshold: float = 0.3
) -> bool:
    """
    Determine if a chunk contains primarily structured content (tables/KV pairs).
    
    If a significant portion of the chunk's content matches table text,
    we can skip LLM entity extraction since Doc Intelligence already extracted entities.
    
    Args:
        chunk_content: The text content of the chunk
        table_text: Set of lowercased text from table cells (from Doc Intelligence)
        structured_phrases: Set of entity names from structured extraction
        threshold: Minimum ratio of matches to consider chunk as structured
        
    Returns:
        True if chunk appears to be primarily structured content
    """
    if not table_text and not structured_phrases:
        return False
    
    chunk_lower = chunk_content.lower()
    chunk_words = set(chunk_lower.split())
    
    # Count how many table phrases appear in the chunk
    matches = 0
    total_phrases = len(table_text) + len(structured_phrases)
    
    # Check table text matches
    for phrase in table_text:
        if phrase in chunk_lower:
            matches += 1
    
    # Check structured phrase matches
    for phrase in structured_phrases:
        if phrase in chunk_lower:
            matches += 1
    
    # Also check for patterns that indicate tabular data
    # Tables often have repeated patterns like "0x" prefixes or underscore identifiers
    table_indicators = 0
    if chunk_content.count("0x") > 3:  # Multiple hex values
        table_indicators += 2
    if chunk_content.count("_") > 5:  # Multiple underscore identifiers
        table_indicators += 1
    if chunk_content.count("|") > 3:  # Pipe characters (table formatting)
        table_indicators += 2
    
    # If we have significant table indicators, consider it structured
    if table_indicators >= 3:
        return True
    
    # Calculate match ratio
    if total_phrases == 0:
        return table_indicators >= 2
    
    match_ratio = matches / min(total_phrases, 20)  # Cap to avoid small denominator issues
    
    return match_ratio >= threshold


def get_entities_for_chunk(
    chunk_content: str,
    all_entities: List[Dict],
    structured_phrases: set
) -> List[Dict]:
    """
    Get Document Intelligence entities that appear in a specific chunk.
    
    Since Doc Intel extracts entities from the entire document, this filters
    to only include entities that actually appear in this chunk.
    
    Args:
        chunk_content: The text content of the chunk
        all_entities: All entities extracted by Document Intelligence
        structured_phrases: Set of entity names for fast lookup
        
    Returns:
        List of entities that appear in this chunk
    """
    chunk_lower = chunk_content.lower()
    chunk_entities = []
    seen = set()
    
    for entity in all_entities:
        name = entity.get("name", "").strip()
        name_lower = name.lower()
        
        # Check if entity appears in chunk
        if name_lower in chunk_lower and name_lower not in seen:
            chunk_entities.append(entity)
            seen.add(name_lower)
    
    return chunk_entities


async def extract_from_any_format(
    content: bytes,
    file_type: str,
    file_name: str = "document"
) -> Dict[str, Any]:
    """
    Intelligent extraction that routes to the best extraction method.
    
    Routes:
    - PDF/Images → Azure Document Intelligence (if available) → fallback to basic
    - Office docs → Azure Document Intelligence
    - Text files → Direct text processing
    """
    category = get_format_category(file_type)
    
    if category == "text":
        # Text files are processed directly
        try:
            text_content = content.decode('utf-8', errors='ignore')
            return {
                "success": True,
                "pages": [{"page_number": 1, "content": text_content}],
                "tables": [],
                "key_value_pairs": [],
                "entities": [],
                "full_text": text_content
            }
        except Exception as e:
            return {"success": False, "error": f"Text decoding failed: {e}"}
    
    elif category in ["structured", "office"]:
        # Try Azure Document Intelligence first
        result = await extract_with_document_intelligence(content, file_type, file_name)
        
        if result.get("success"):
            return result
        
        # Fallback to basic extraction for PDFs
        if file_type.lower() == "pdf":
            logging.info("Falling back to basic PDF extraction")
            return extract_pdf_basic(content)
        
        return result
    
    else:
        return {"success": False, "error": f"Unsupported format: {file_type}"}


def extract_pdf_basic(content: bytes) -> Dict[str, Any]:
    """
    Basic PDF extraction fallback when Document Intelligence is not available.
    Uses pypdf for text extraction.
    """
    try:
        import pypdf
        import io
        
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages = []
        all_text = []
        
        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append({
                    "page_number": page_num,
                    "content": text
                })
                all_text.append(text)
        
        return {
            "success": True,
            "pages": pages,
            "tables": [],  # Basic extraction can't extract tables
            "key_value_pairs": [],
            "entities": [],
            "full_text": "\n\n".join(all_text)
        }
        
    except Exception as e:
        return {"success": False, "error": f"Basic PDF extraction failed: {e}"}


def deduplicate_entities(entities: List[Dict]) -> List[Dict]:
    """
    Deduplicate entities by name, preferring richer entity types.
    """
    seen = {}
    priority = {"CODE": 3, "COMPONENT": 2, "CONDITION": 2, "VALUE": 1, "PROCEDURE": 1, "CONCEPT": 0}
    
    for entity in entities:
        name = entity.get("name", "").strip().lower()
        if not name:
            continue
            
        entity_type = entity.get("type", "CONCEPT")
        entity_priority = priority.get(entity_type, 0)
        
        if name not in seen or entity_priority > seen[name]["priority"]:
            seen[name] = {
                "entity": entity,
                "priority": entity_priority
            }
    
    return [item["entity"] for item in seen.values()]
