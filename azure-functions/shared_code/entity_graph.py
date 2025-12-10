"""
Entity Graph Module for GraphRAG-style extraction.

Supports:
- Document-agnostic entity extraction
- Relationship extraction
- Entity deduplication and merging
- Optional Cosmos DB Gremlin storage
"""

import json
import re
import os
import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """Represents an extracted entity."""
    name: str
    entity_type: str
    description: str = ""
    chunk_ids: List[str] = field(default_factory=list)
    frequency: int = 1
    aliases: Set[str] = field(default_factory=set)
    
    def merge(self, other: 'Entity'):
        """Merge another entity into this one."""
        if other.description and len(other.description) > len(self.description):
            self.description = other.description
        self.chunk_ids.extend(other.chunk_ids)
        self.frequency += other.frequency
        self.aliases.add(other.name)
        self.aliases.update(other.aliases)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.entity_type,
            "description": self.description,
            "chunk_ids": list(set(self.chunk_ids)),
            "frequency": self.frequency,
            "aliases": list(self.aliases)
        }


@dataclass
class Relationship:
    """Represents a relationship between entities."""
    source: str
    target: str
    rel_type: str
    description: str = ""
    chunk_id: str = ""
    
    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.rel_type,
            "description": self.description
        }


class EntityGraph:
    """
    Manages entity extraction, deduplication, and graph construction.
    """
    
    # Document-agnostic entity types
    ENTITY_TYPES = [
        "CODE",       # Error codes, identifiers, hex values
        "COMPONENT",  # Hardware, software, systems, modules
        "CONDITION",  # Failure modes, states, symptoms
        "VALUE",      # Thresholds, measurements, parameters  
        "PROCEDURE",  # Steps, methods, troubleshooting actions
        "CONCEPT",    # Abstract ideas, categories, types
        "PERSON",     # Names of people
        "ORG",        # Organizations, companies
        "LOCATION",   # Places, positions
    ]
    
    # Document-agnostic relationship types
    RELATIONSHIP_TYPES = [
        "CAUSES",     # X causes Y
        "TRIGGERS",   # X triggers Y
        "AFFECTS",    # X affects Y
        "HAS",        # X has Y
        "RELATED_TO", # X is related to Y
        "FIXES",      # X fixes Y
        "REQUIRES",   # X requires Y
        "INCLUDES",   # X includes Y
    ]
    
    def __init__(self):
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self._name_index: Dict[str, str] = {}  # normalized -> canonical
    
    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize entity name for deduplication."""
        # Lowercase, remove extra whitespace
        normalized = name.lower().strip()
        # Remove common prefixes/suffixes
        normalized = re.sub(r'^(the|a|an)\s+', '', normalized)
        # Replace multiple spaces with single
        normalized = re.sub(r'\s+', ' ', normalized)
        # For hex codes, standardize format
        if re.match(r'0x[a-fA-F0-9]+', name):
            normalized = name.upper()
        return normalized
    
    def add_entity(self, name: str, entity_type: str, description: str = "", chunk_id: str = ""):
        """Add or merge an entity."""
        normalized = self.normalize_name(name)
        
        if normalized in self._name_index:
            # Merge with existing entity
            canonical = self._name_index[normalized]
            existing = self.entities[canonical]
            new_entity = Entity(
                name=name,
                entity_type=entity_type,
                description=description,
                chunk_ids=[chunk_id] if chunk_id else []
            )
            existing.merge(new_entity)
        else:
            # New entity
            self._name_index[normalized] = normalized
            self.entities[normalized] = Entity(
                name=name,
                entity_type=entity_type,
                description=description,
                chunk_ids=[chunk_id] if chunk_id else [],
                frequency=1
            )
    
    def add_relationship(self, source: str, target: str, rel_type: str, 
                        description: str = "", chunk_id: str = ""):
        """Add a relationship between entities."""
        # Ensure both entities exist
        source_norm = self.normalize_name(source)
        target_norm = self.normalize_name(target)
        
        if source_norm not in self.entities:
            self.add_entity(source, "CONCEPT", chunk_id=chunk_id)
        if target_norm not in self.entities:
            self.add_entity(target, "CONCEPT", chunk_id=chunk_id)
        
        # Check for duplicate relationships
        for rel in self.relationships:
            if (self.normalize_name(rel.source) == source_norm and 
                self.normalize_name(rel.target) == target_norm and
                rel.rel_type == rel_type):
                return  # Already exists
        
        self.relationships.append(Relationship(
            source=source,
            target=target,
            rel_type=rel_type,
            description=description,
            chunk_id=chunk_id
        ))
    
    def get_entity(self, name: str) -> Optional[Entity]:
        """Get entity by name."""
        normalized = self.normalize_name(name)
        if normalized in self._name_index:
            return self.entities.get(self._name_index[normalized])
        return None
    
    def get_related_entities(self, name: str, depth: int = 1) -> List[Dict[str, Any]]:
        """Get entities related to the given entity."""
        normalized = self.normalize_name(name)
        related = []
        visited = {normalized}
        
        def traverse(entity_name: str, current_depth: int):
            if current_depth > depth:
                return
            
            for rel in self.relationships:
                source_norm = self.normalize_name(rel.source)
                target_norm = self.normalize_name(rel.target)
                
                if source_norm == entity_name and target_norm not in visited:
                    visited.add(target_norm)
                    entity = self.entities.get(target_norm)
                    if entity:
                        related.append({
                            "entity": entity.to_dict(),
                            "relationship": rel.to_dict(),
                            "direction": "outgoing"
                        })
                    traverse(target_norm, current_depth + 1)
                
                elif target_norm == entity_name and source_norm not in visited:
                    visited.add(source_norm)
                    entity = self.entities.get(source_norm)
                    if entity:
                        related.append({
                            "entity": entity.to_dict(),
                            "relationship": rel.to_dict(),
                            "direction": "incoming"
                        })
                    traverse(source_norm, current_depth + 1)
        
        traverse(normalized, 1)
        return related
    
    def count_by_type(self, entity_type: str) -> int:
        """Count entities of a specific type."""
        return sum(1 for e in self.entities.values() 
                   if e.entity_type.upper() == entity_type.upper())
    
    def get_all_of_type(self, entity_type: str) -> List[Entity]:
        """Get all entities of a specific type."""
        return [e for e in self.entities.values() 
                if e.entity_type.upper() == entity_type.upper()]
    
    def to_dict(self) -> dict:
        """Export graph as dictionary."""
        return {
            "entities": [e.to_dict() for e in self.entities.values()],
            "relationships": [r.to_dict() for r in self.relationships],
            "stats": {
                "total_entities": len(self.entities),
                "total_relationships": len(self.relationships),
                "entity_types": dict(self._count_by_types())
            }
        }
    
    def _count_by_types(self) -> Dict[str, int]:
        """Count entities by type."""
        type_counts = defaultdict(int)
        for entity in self.entities.values():
            type_counts[entity.entity_type] += 1
        return type_counts
    
    def to_json(self) -> str:
        """Export graph as JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'EntityGraph':
        """Create EntityGraph from dictionary."""
        graph = cls()
        
        for entity_data in data.get("entities", []):
            entity = Entity(
                name=entity_data["name"],
                entity_type=entity_data["type"],
                description=entity_data.get("description", ""),
                chunk_ids=entity_data.get("chunk_ids", []),
                frequency=entity_data.get("frequency", 1),
                aliases=set(entity_data.get("aliases", []))
            )
            normalized = cls.normalize_name(entity.name)
            graph.entities[normalized] = entity
            graph._name_index[normalized] = normalized
        
        for rel_data in data.get("relationships", []):
            graph.relationships.append(Relationship(
                source=rel_data["source"],
                target=rel_data["target"],
                rel_type=rel_data["type"],
                description=rel_data.get("description", "")
            ))
        
        return graph


# ============================================================================
# EXTRACTION PROMPT - Document Agnostic
# ============================================================================

ENTITY_EXTRACTION_PROMPT = """Extract ALL named entities and relationships from this text.

ENTITY TYPES (extract ANY that appear):
- CODE: Error codes, identifiers, hex values, DTC numbers (e.g., 0x8EF4EE)
- COMPONENT: Hardware, software, systems, modules, sensors, valves
- CONDITION: Failure modes, states, symptoms, error conditions
- VALUE: Thresholds, measurements, parameters, specifications
- PROCEDURE: Steps, methods, troubleshooting actions, tests
- CONCEPT: Abstract ideas, categories, failure types

RELATIONSHIP TYPES:
- CAUSES: X causes Y (failure causation)
- TRIGGERS: X triggers Y 
- AFFECTS: X affects Y (impact)
- HAS: X has Y (composition)
- RELATED_TO: X is related to Y
- FIXES: X fixes Y (resolution)
- REQUIRES: X requires Y

IMPORTANT RULES:
1. Extract EVERY entity you find, even if similar ones exist
2. For hex codes, preserve exact format (0x prefix, uppercase)
3. Include entity descriptions that explain what it is
4. Capture relationships between entities when explicit or implied

Text to analyze:
{text}

Respond in JSON format ONLY:
{{
  "entities": [
    {{"name": "0x8EF4EE", "type": "CODE", "description": "TCU hardware error code"}},
    {{"name": "TCU", "type": "COMPONENT", "description": "Transmission Control Unit"}}
  ],
  "relationships": [
    {{"source": "0x8EF4EE", "target": "transmission_failure", "type": "CAUSES", "description": "This error causes transmission to fail"}}
  ]
}}"""


# ============================================================================
# COSMOS DB GREMLIN SUPPORT (Optional)
# ============================================================================

class CosmosDBGraphStore:
    """
    Optional Cosmos DB Gremlin storage for persistent graph.
    Requires: gremlinpython package and Cosmos DB Gremlin account.
    """
    
    def __init__(self, endpoint: str = None, key: str = None, 
                 database: str = "graphrag", graph: str = "entities"):
        self.endpoint = endpoint or os.environ.get("COSMOS_GREMLIN_ENDPOINT")
        self.key = key or os.environ.get("COSMOS_GREMLIN_KEY")
        self.database = database
        self.graph = graph
        self._client = None
    
    @property
    def is_configured(self) -> bool:
        """Check if Cosmos DB is configured."""
        return bool(self.endpoint and self.key)
    
    def connect(self):
        """Connect to Cosmos DB Gremlin API."""
        if not self.is_configured:
            logger.warning("Cosmos DB Gremlin not configured. Graph will be in-memory only.")
            return False
        
        try:
            from gremlin_python.driver import client, serializer
            
            self._client = client.Client(
                url=self.endpoint,
                traversal_source='g',
                username=f"/dbs/{self.database}/colls/{self.graph}",
                password=self.key,
                message_serializer=serializer.GraphSONSerializersV2d0()
            )
            logger.info("Connected to Cosmos DB Gremlin API")
            return True
        except ImportError:
            logger.warning("gremlinpython not installed. Run: pip install gremlinpython")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Cosmos DB: {e}")
            return False
    
    def store_entity(self, entity: Entity, workflow_id: str):
        """Store entity as vertex in Cosmos DB."""
        if not self._client:
            return
        
        query = """
        g.addV('entity')
            .property('id', entityId)
            .property('name', name)
            .property('type', entityType)
            .property('description', description)
            .property('frequency', frequency)
            .property('workflow_id', workflowId)
            .property('partitionKey', workflowId)
        """
        
        try:
            self._client.submit(query, {
                'entityId': f"{workflow_id}_{EntityGraph.normalize_name(entity.name)}",
                'name': entity.name,
                'entityType': entity.entity_type,
                'description': entity.description,
                'frequency': entity.frequency,
                'workflowId': workflow_id
            })
        except Exception as e:
            logger.error(f"Failed to store entity: {e}")
    
    def store_relationship(self, rel: Relationship, workflow_id: str):
        """Store relationship as edge in Cosmos DB."""
        if not self._client:
            return
        
        source_id = f"{workflow_id}_{EntityGraph.normalize_name(rel.source)}"
        target_id = f"{workflow_id}_{EntityGraph.normalize_name(rel.target)}"
        
        query = """
        g.V(sourceId).addE(relType).to(g.V(targetId))
            .property('description', description)
            .property('workflow_id', workflowId)
        """
        
        try:
            self._client.submit(query, {
                'sourceId': source_id,
                'targetId': target_id,
                'relType': rel.rel_type,
                'description': rel.description,
                'workflowId': workflow_id
            })
        except Exception as e:
            logger.error(f"Failed to store relationship: {e}")
    
    def store_graph(self, graph: EntityGraph, workflow_id: str):
        """Store entire graph in Cosmos DB."""
        if not self.connect():
            return False
        
        # Store all entities
        for entity in graph.entities.values():
            self.store_entity(entity, workflow_id)
        
        # Store all relationships
        for rel in graph.relationships:
            self.store_relationship(rel, workflow_id)
        
        logger.info(f"Stored graph with {len(graph.entities)} entities, {len(graph.relationships)} relationships")
        return True
    
    def close(self):
        """Close connection."""
        if self._client:
            self._client.close()
