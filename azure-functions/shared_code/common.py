
import json
import logging
from pathlib import Path

async def get_config():
    """Reads agents config."""
    config_path = Path(__file__).parent.parent / "azure_agents_config.json"
    if not config_path.exists():
        return {}
    with open(config_path, "r") as f:
        return json.load(f)

async def tool_list_available_agents() -> list:
    """Returns list of agents."""
    config = await get_config()
    agents = []
    for key, data in config.get("agents", {}).items():
        agents.append({
            "name": data.get("name", key),
            "role": key,
            "id": data.get("id"),
            "description": data.get("name") 
        })
    return agents

async def tool_validate_data_source(source_type: str) -> dict:
    """Validates data source type."""
    valid_types = ["database", "documents", "api", "file"]
    is_valid = source_type.lower() in valid_types
    return {
        "valid": is_valid,
        "message": f"{source_type} is {'supported' if is_valid else 'not supported'}.",
        "source_type": source_type
    }

async def tool_extract_citations(outputs: list) -> list:
    """Extracts citations."""
    citations = []
    for output in outputs:
        if isinstance(output, dict):
            if "citations" in output:
                citations.extend(output["citations"])
            # Check for strings that look like citations
            for k, v in output.items():
                if isinstance(v, str) and "[" in v and "]" in v:
                    pass # TODO: Regex extraction
    return list(set(citations))

async def tool_generate_followup_questions(context: dict, count: int = 3) -> list:
    """Generates follow up questions (Placeholder logic)."""
    # In a real app, this would call GPT-4o-mini to generate questions based on context
    return [
        "What are the next steps?",
        "How does this affect the budget?",
        "Are there alternative approaches?"
    ][:count]
