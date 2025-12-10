"""
Azure Function: graph_query
Query the knowledge graph for entity details, relationships, and graph traversal.

Supports multiple query types:
- get_entity: Get entity details and connections
- count_type: Count entities of a specific type
- list_type: List all entities of a specific type
- get_related: Find related entities via relationships
- search_entities: Search entities by name pattern
"""
import azure.functions as func
import logging
import json
import os
import sys
import re
from typing import List, Dict, Any, Optional


async def main(req: func.HttpRequest) -> func.HttpResponse:
    # Path Setup
    site_packages = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.python_packages', 'lib', 'site-packages')
    if site_packages not in sys.path:
        sys.path.append(site_packages)
    
    logging.info('Graph Query Function triggered')
    
    try:
        from azure.search.documents.aio import SearchClient
        from azure.core.credentials import AzureKeyCredential
        
        req_body = req.get_json()
        workflow_id = req_body.get('workflow_id')
        query_type = req_body.get('type', 'get_entity')
        
        if not workflow_id:
            return func.HttpResponse(
                json.dumps({"error": "workflow_id is required", "success": False}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Config
        search_endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
        search_key = os.environ.get("AZURE_SEARCH_KEY") or os.environ.get("AZURE_SEARCH_API_KEY")
        index_name = os.environ.get("AZURE_SEARCH_INDEX", "schema-docs")
        
        if not search_endpoint or not search_key:
            return func.HttpResponse(
                json.dumps({"error": "Search configuration missing", "success": False}),
                status_code=500,
                mimetype="application/json"
            )
        
        credential = AzureKeyCredential(search_key)
        async with SearchClient(search_endpoint, index_name, credential) as client:
            
            # First, get the document summary which contains the entity graph
            filter_str = f"workflow_id eq '{workflow_id}' and doc_type eq 'document_summary'"
            
            results = await client.search(
                search_text="*",
                filter=filter_str,
                select=["entities", "relationships", "entity_stats", "file_name"],
                top=10
            )
            
            # Parse all entities and relationships from all documents
            all_entities = []
            all_relationships = []
            all_stats = {}
            
            async for doc in results:
                # Parse entities
                entities_str = doc.get("entities", "[]")
                try:
                    entities = json.loads(entities_str) if entities_str else []
                    all_entities.extend(entities)
                except:
                    pass
                
                # Parse relationships
                relationships_str = doc.get("relationships", "[]")
                try:
                    relationships = json.loads(relationships_str) if relationships_str else []
                    all_relationships.extend(relationships)
                except:
                    pass
                
                # Parse stats
                stats_str = doc.get("entity_stats", "{}")
                try:
                    stats = json.loads(stats_str) if stats_str else {}
                    for key, val in stats.items():
                        if key != "entity_types":
                            all_stats[key] = all_stats.get(key, 0) + val if isinstance(val, int) else val
                        else:
                            # Merge entity_types dict
                            if "entity_types" not in all_stats:
                                all_stats["entity_types"] = {}
                            for t, c in val.items():
                                all_stats["entity_types"][t] = all_stats["entity_types"].get(t, 0) + c
                except:
                    pass
            
            # Execute query based on type
            result = {}
            
            if query_type == "get_entity":
                # Get specific entity details
                entity_name = req_body.get("entity_name", "")
                entity = find_entity(all_entities, entity_name)
                if entity:
                    related = find_related_entities(all_relationships, entity_name, all_entities)
                    result = {
                        "entity": entity,
                        "related_entities": related,
                        "relationship_count": len(related)
                    }
                else:
                    result = {"entity": None, "message": f"Entity '{entity_name}' not found"}
            
            elif query_type == "count_type":
                # Count entities of a specific type
                entity_type = req_body.get("entity_type", "").upper()
                count = sum(1 for e in all_entities if e.get("type", "").upper() == entity_type)
                entities_of_type = [e.get("name") for e in all_entities if e.get("type", "").upper() == entity_type]
                result = {
                    "entity_type": entity_type,
                    "count": count,
                    "sample": entities_of_type[:20]  # First 20 examples
                }
            
            elif query_type == "list_type":
                # List all entities of a specific type
                entity_type = req_body.get("entity_type", "").upper()
                limit = req_body.get("limit", 100)
                entities_of_type = [e for e in all_entities if e.get("type", "").upper() == entity_type]
                # Sort by frequency if available
                entities_of_type.sort(key=lambda x: x.get("frequency", 1), reverse=True)
                result = {
                    "entity_type": entity_type,
                    "total": len(entities_of_type),
                    "entities": entities_of_type[:limit]
                }
            
            elif query_type == "get_related":
                # Find entities related to a given entity
                entity_name = req_body.get("entity_name", "")
                depth = req_body.get("depth", 1)
                related = find_related_entities(all_relationships, entity_name, all_entities, depth)
                result = {
                    "entity_name": entity_name,
                    "related_count": len(related),
                    "related_entities": related
                }
            
            elif query_type == "search_entities":
                # Search entities by name pattern
                pattern = req_body.get("pattern", "")
                limit = req_body.get("limit", 50)
                matching = search_entities_by_pattern(all_entities, pattern, limit)
                result = {
                    "pattern": pattern,
                    "match_count": len(matching),
                    "matches": matching
                }
            
            elif query_type == "get_stats":
                # Get overall entity statistics
                result = {
                    "total_entities": len(all_entities),
                    "total_relationships": len(all_relationships),
                    "stats": all_stats
                }
            
            elif query_type == "get_relationships":
                # Get relationships involving an entity
                entity_name = req_body.get("entity_name", "")
                rels = [r for r in all_relationships 
                        if normalize(r.get("source", "")) == normalize(entity_name) or 
                           normalize(r.get("target", "")) == normalize(entity_name)]
                result = {
                    "entity_name": entity_name,
                    "relationship_count": len(rels),
                    "relationships": rels[:50]
                }
            
            else:
                return func.HttpResponse(
                    json.dumps({"error": f"Unknown query type: {query_type}", "success": False}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "query_type": query_type,
                    "workflow_id": workflow_id,
                    "result": result
                }),
                mimetype="application/json",
                status_code=200
            )

    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": str(e), "success": False}),
            status_code=500,
            mimetype="application/json"
        )


def normalize(name: str) -> str:
    """Normalize entity name for matching."""
    return name.lower().strip()


def find_entity(entities: List[Dict], name: str) -> Optional[Dict]:
    """Find entity by name (case-insensitive)."""
    name_norm = normalize(name)
    for entity in entities:
        if normalize(entity.get("name", "")) == name_norm:
            return entity
    return None


def find_related_entities(relationships: List[Dict], entity_name: str, 
                          all_entities: List[Dict], depth: int = 1) -> List[Dict]:
    """Find entities related to the given entity."""
    entity_norm = normalize(entity_name)
    related = []
    visited = {entity_norm}
    
    def get_entity_by_name(name: str) -> Optional[Dict]:
        return find_entity(all_entities, name)
    
    def traverse(current_name: str, current_depth: int):
        if current_depth > depth:
            return
        
        current_norm = normalize(current_name)
        
        for rel in relationships:
            source_norm = normalize(rel.get("source", ""))
            target_norm = normalize(rel.get("target", ""))
            
            if source_norm == current_norm and target_norm not in visited:
                visited.add(target_norm)
                target_entity = get_entity_by_name(target_norm)
                related.append({
                    "entity": target_entity or {"name": rel.get("target")},
                    "relationship": {
                        "type": rel.get("type"),
                        "description": rel.get("description", ""),
                        "direction": "outgoing"
                    }
                })
                traverse(target_norm, current_depth + 1)
            
            elif target_norm == current_norm and source_norm not in visited:
                visited.add(source_norm)
                source_entity = get_entity_by_name(source_norm)
                related.append({
                    "entity": source_entity or {"name": rel.get("source")},
                    "relationship": {
                        "type": rel.get("type"),
                        "description": rel.get("description", ""),
                        "direction": "incoming"
                    }
                })
                traverse(source_norm, current_depth + 1)
    
    traverse(entity_name, 1)
    return related


def search_entities_by_pattern(entities: List[Dict], pattern: str, limit: int = 50) -> List[Dict]:
    """Search entities by name pattern (supports regex)."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        matches = [e for e in entities if regex.search(e.get("name", ""))]
        # Sort by frequency
        matches.sort(key=lambda x: x.get("frequency", 1), reverse=True)
        return matches[:limit]
    except re.error:
        # Fall back to simple substring match
        pattern_lower = pattern.lower()
        matches = [e for e in entities if pattern_lower in e.get("name", "").lower()]
        matches.sort(key=lambda x: x.get("frequency", 1), reverse=True)
        return matches[:limit]
