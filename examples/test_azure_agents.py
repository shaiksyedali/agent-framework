"""
Simple test to verify Azure Foundry agents are working
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python" / "packages" / "azure-ai"))

from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


async def test_agents():
    """Test agents are accessible"""

    # Load environment
    env_file = Path(__file__).parent.parent / ".env.azure"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

    # Load config
    config_file = Path(__file__).parent.parent / "azure_agents_config.json"
    with open(config_file) as f:
        config = json.load(f)

    # Initialize client
    logger.info("Initializing Azure AI Agents Client...")
    credential = DefaultAzureCredential()
    project_endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]

    try:
        agents_client = AgentsClient(
            endpoint=project_endpoint,
            credential=credential
        )

        logger.info("\n" + "=" * 70)
        logger.info("Testing Agent: Supervisor")
        logger.info("=" * 70)

        # Run the supervisor agent with automatic processing
        supervisor_id = config["agents"]["supervisor"]["id"]
        logger.info(f"Running supervisor agent: {supervisor_id}")

        # Create thread and run agent with automatic result processing
        result = await agents_client.create_thread_and_process_run(
            agent_id=supervisor_id,
            thread={
                "messages": [
                    {
                        "role": "user",
                        "content": "Hello! Can you explain what you do as a Supervisor Agent in 2-3 sentences?"
                    }
                ]
            }
        )

        logger.info("\n" + "=" * 70)
        logger.info("Response:")
        logger.info("=" * 70)

        # Process the result
        if hasattr(result, 'messages'):
            for msg in result.messages:
                if msg.role == "assistant":
                    for content in msg.content:
                        if hasattr(content, 'text'):
                            logger.info(content.text.value)
        elif hasattr(result, 'data'):
            # Alternative result format
            for msg in result.data:
                if msg.role == "assistant":
                    for content in msg.content:
                        if hasattr(content, 'text'):
                            logger.info(content.text.value)
        else:
            logger.info(f"Result type: {type(result)}")
            logger.info(f"Result: {result}")

        logger.info("\n" + "=" * 70)
        logger.info("✓ TEST PASSED - Supervisor agent is working!")
        logger.info("=" * 70)

        return True

    finally:
        await credential.close()


if __name__ == "__main__":
    try:
        success = asyncio.run(test_agents())
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
