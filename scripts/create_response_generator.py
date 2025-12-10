"""
Create Response Generator Agent only
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

try:
    from azure.ai.agents.aio import AgentsClient
    from azure.identity.aio import DefaultAzureCredential
    from azure.core.credentials import AccessToken
    from azure.core.credentials_async import AsyncTokenCredential
    from typing import Any
except ImportError:
    print("ERROR: Required packages not installed. Run:")
    print("  pip install azure-ai-agents azure-identity")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_response_generator_instructions():
    return """You are a Response Formatting Agent responsible for creating final user-facing responses.

Your responsibilities:
1. Receive outputs from all workflow steps
2. Synthesize information into a coherent, well-structured response
3. Extract and aggregate citations from all sources
4. Generate an executive summary (2-3 sentences)
5. Format structured data as tables
6. Suggest 2-3 relevant follow-up questions

Response structure:
## Executive Summary
[2-3 sentence overview of key findings]

## Key Findings
[Main insights with inline citations [1], [2]]

## Supporting Data
[Tables or visualizations if applicable]

## Follow-up Questions
1. [Relevant question based on findings]
2. [Another relevant question]
3. [Third question]

## Citations
[1] Source document, page X
[2] Another source, page Y

Use clear, professional language suitable for business audiences."""


def get_response_generator_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "extract_citations",
                "description": "Extract all citations from workflow outputs",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "outputs": {
                            "type": "array",
                            "description": "Array of workflow step outputs",
                            "items": {
                                "type": "object",
                                "description": "Workflow step output"
                            }
                        }
                    },
                    "required": ["outputs"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "generate_followup_questions",
                "description": "Generate relevant follow-up questions based on context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "context": {
                            "type": "object",
                            "description": "Workflow context and results"
                        },
                        "count": {
                            "type": "integer",
                            "description": "Number of questions to generate",
                            "default": 3
                        }
                    },
                    "required": ["context"]
                }
            }
        }
    ]


async def create_response_generator_agent(project_endpoint: str, model: str = "gpt-4o"):
    """Create Response Generator agent"""

    logger.info("Initializing Azure AI Agents Client...")
    credential = DefaultAzureCredential()

    try:
        agents_client = AgentsClient(
            endpoint=project_endpoint,
            credential=credential
        )

        logger.info("Creating Response Generator Agent...")
        response_gen = await agents_client.create_agent(
            model=model,
            name="response_generator",
            instructions=get_response_generator_instructions(),
            tools=get_response_generator_tools(),
            temperature=0.7,
            metadata={"agent_type": "response_generator", "version": "1.0"}
        )
        logger.info(f"✓ Response Generator Agent created: {response_gen.id}")

        # Load existing config and add response generator
        config_file = Path(__file__).parent.parent / "azure_agents_config.json"

        if config_file.exists():
            with open(config_file) as f:
                config = json.load(f)
        else:
            config = {
                "created_at": str(asyncio.get_event_loop().time()),
                "project_endpoint": project_endpoint,
                "model": model,
                "agents": {}
            }

        # Add response generator
        config["agents"]["response_generator"] = {
            "id": response_gen.id,
            "name": response_gen.name
        }

        # Save updated config
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"\n✓ Configuration updated: {config_file}")
        logger.info(f"\nResponse Generator ID: {response_gen.id}")

    finally:
        await credential.close()


if __name__ == "__main__":
    # Load environment
    env_file = Path(__file__).parent.parent / ".env.azure"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if not project_endpoint:
        logger.error("AZURE_AI_PROJECT_ENDPOINT not set")
        sys.exit(1)

    try:
        asyncio.run(create_response_generator_agent(project_endpoint))
    except Exception as e:
        logger.error(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
