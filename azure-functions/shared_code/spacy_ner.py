"""
spaCy Named Entity Recognition (NER) for fast, generic entity extraction.
Uses pre-trained statistical models - no LLM needed.
Optimized for Azure Functions with lazy loading and batch processing.
"""
import logging
from typing import List, Dict, Any, Optional
import os

# Global model cache to avoid reloading on each function call
_nlp_model = None


def get_nlp_model():
    """
    Lazily load and cache the spaCy model.
    Uses en_core_web_sm for speed, but can be configured via environment variable.
    """
    global _nlp_model
    
    if _nlp_model is not None:
        return _nlp_model
    
    try:
        import spacy
        
        # Allow model override via environment variable
        model_name = os.environ.get("SPACY_MODEL", "en_core_web_sm")
        
        try:
            _nlp_model = spacy.load(model_name, disable=["parser", "lemmatizer"])
            logging.info(f"Loaded spaCy model: {model_name}")
        except OSError:
            # Model not installed, try to download it
            logging.info(f"spaCy model {model_name} not found, downloading...")
            from spacy.cli import download
            download(model_name)
            _nlp_model = spacy.load(model_name, disable=["parser", "lemmatizer"])
            logging.info(f"Downloaded and loaded spaCy model: {model_name}")
        
        return _nlp_model
        
    except ImportError:
        logging.warning("spaCy not installed, entity extraction disabled")
        return None
    except Exception as e:
        logging.warning(f"Failed to load spaCy model: {e}")
        return None


def extract_entities_from_text(text: str, max_length: int = 100000) -> List[Dict[str, Any]]:
    """
    Extract named entities from text using spaCy NER.
    
    Args:
        text: Input text to extract entities from
        max_length: Maximum text length to process (for memory safety)
    
    Returns:
        List of entity dictionaries with name, type, and description
    """
    nlp = get_nlp_model()
    
    if nlp is None:
        return []
    
    # Truncate very long text to avoid memory issues
    if len(text) > max_length:
        text = text[:max_length]
    
    try:
        doc = nlp(text)
        
        entities = []
        seen = set()
        
        for ent in doc.ents:
            # Skip very short entities
            if len(ent.text.strip()) < 2:
                continue
            
            # Deduplicate by lowercase name
            key = ent.text.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            
            # Map spaCy entity labels to our schema
            entity_type = map_spacy_label(ent.label_)
            
            entities.append({
                "name": ent.text.strip(),
                "type": entity_type,
                "description": f"Named entity ({ent.label_})",
                "source": "spacy_ner"
            })
        
        return entities
        
    except Exception as e:
        logging.warning(f"spaCy entity extraction failed: {e}")
        return []


def extract_entities_batch(texts: List[str], batch_size: int = 50) -> List[List[Dict[str, Any]]]:
    """
    Extract entities from multiple texts using spaCy's efficient batch processing.
    
    Args:
        texts: List of text strings to process
        batch_size: Number of texts to process at once
    
    Returns:
        List of entity lists (one per input text)
    """
    nlp = get_nlp_model()
    
    if nlp is None:
        return [[] for _ in texts]
    
    try:
        results = []
        
        # Process in batches using nlp.pipe for efficiency
        for doc in nlp.pipe(texts, batch_size=batch_size):
            entities = []
            seen = set()
            
            for ent in doc.ents:
                if len(ent.text.strip()) < 2:
                    continue
                
                key = ent.text.strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                
                entity_type = map_spacy_label(ent.label_)
                
                entities.append({
                    "name": ent.text.strip(),
                    "type": entity_type,
                    "description": f"Named entity ({ent.label_})",
                    "source": "spacy_ner"
                })
            
            results.append(entities)
        
        return results
        
    except Exception as e:
        logging.warning(f"spaCy batch extraction failed: {e}")
        return [[] for _ in texts]


def map_spacy_label(label: str) -> str:
    """
    Map spaCy entity labels to our entity type schema.
    
    spaCy labels include:
    - PERSON, ORG, GPE (geo-political entity), LOC, DATE, TIME, MONEY
    - PRODUCT, EVENT, WORK_OF_ART, LAW, LANGUAGE
    - NORP (nationalities, religious, political groups)
    - FAC (facilities), CARDINAL, ORDINAL, QUANTITY, PERCENT
    
    We map these to: CODE, COMPONENT, CONDITION, VALUE, PROCEDURE, CONCEPT
    """
    mapping = {
        # Technical/Product entities → CODE or COMPONENT
        "PRODUCT": "CODE",
        "ORG": "COMPONENT",
        "FAC": "COMPONENT",
        
        # Numeric/Value entities → VALUE
        "CARDINAL": "VALUE",
        "ORDINAL": "VALUE",
        "QUANTITY": "VALUE",
        "PERCENT": "VALUE",
        "MONEY": "VALUE",
        
        # Time/Date → VALUE
        "DATE": "VALUE",
        "TIME": "VALUE",
        
        # Location/Political → CONCEPT
        "GPE": "CONCEPT",
        "LOC": "CONCEPT",
        "NORP": "CONCEPT",
        
        # People → CONCEPT
        "PERSON": "CONCEPT",
        
        # Other → CONCEPT
        "EVENT": "CONCEPT",
        "WORK_OF_ART": "CONCEPT",
        "LAW": "CONCEPT",
        "LANGUAGE": "CONCEPT",
    }
    
    return mapping.get(label, "CONCEPT")


def get_entity_names(entities: List[Dict[str, Any]]) -> List[str]:
    """
    Extract just the entity names from a list of entity dictionaries.
    Used for populating the facetable entity_codes field.
    """
    return [e.get("name", "") for e in entities if e.get("name")]
