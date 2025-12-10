"""
Test Azure AI Foundry Connection and Agents API Access

This script verifies:
1. Azure authentication is working
2. Azure AI Foundry project is accessible
3. Agents API is available and functional

Usage:
    python scripts/test_azure_connection.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Load environment variables from .env.azure
env_file = Path(__file__).parent.parent / ".env.azure"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key] = value

try:
    from azure.ai.agents.aio import AgentsClient
    from azure.identity.aio import DefaultAzureCredential
    from azure.core.credentials import AccessToken
    from azure.core.credentials_async import AsyncTokenCredential
    from typing import Any
except ImportError as e:
    print(f"ERROR: Missing dependencies: {e}")
    print("\nInstall required packages:")
    print("  pip install azure-ai-agents azure-identity")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class APIKeyTokenCredential(AsyncTokenCredential):
    """Token credential wrapper for API keys"""

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken(token=self._api_key, expires_on=9999999999)

    async def close(self) -> None:
        pass


async def test_connection():
    """Test Azure AI Foundry connection and Agents API"""

    # Get configuration
    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")

    if not project_endpoint:
        logger.error("AZURE_AI_PROJECT_ENDPOINT not set in .env.azure")
        return False

    logger.info("=" * 70)
    logger.info("Azure AI Foundry Connection Test")
    logger.info("=" * 70)
    logger.info(f"\nProject Endpoint: {project_endpoint}")

    # Try API key authentication first, then DefaultAzureCredential
    credential = None
    auth_method = None

    try:
        if api_key:
            logger.info("Authentication: Using API Key (wrapped as TokenCredential)")
            credential = APIKeyTokenCredential(api_key)
            auth_method = "api_key"
        else:
            logger.info("Authentication: Using DefaultAzureCredential (Managed Identity/Azure CLI)")
            credential = DefaultAzureCredential()
            auth_method = "default"

        # Initialize Agents client directly
        logger.info("\nInitializing AgentsClient...")
        agents_client = AgentsClient(
            endpoint=project_endpoint,
            credential=credential
        )

        logger.info("✓ AgentsClient initialized successfully")

        # Test Agents API access
        logger.info("\nTesting Agents API access...")

        # Try to list existing agents
        logger.info("Attempting to list agents...")

        try:
            # Note: This might fail if no agents exist yet, which is fine
            agents_list = []
            async for agent in agents_client.list_agents(limit=5):
                agents_list.append(agent)

            logger.info(f"✓ Agents API accessible")

            if agents_list:
                logger.info(f"\nFound {len(agents_list)} existing agent(s):")
                for agent in agents_list:
                    logger.info(f"  - {agent.name} (ID: {agent.id})")
            else:
                logger.info("\nNo existing agents found (this is normal for new projects)")

        except Exception as e:
            # Some implementations might not support list_agents
            logger.warning(f"Could not list agents: {e}")
            logger.info("This might be normal - will verify by creating a test agent...")

            # Try creating a minimal test agent
            try:
                logger.info("\nCreating test agent...")
                test_agent = await agents_client.create_agent(
                    model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
                    name="connection_test_agent",
                    instructions="This is a test agent to verify API access.",
                    temperature=0.5
                )

                logger.info(f"✓ Test agent created successfully: {test_agent.id}")

                # Clean up test agent
                logger.info("Cleaning up test agent...")
                await agents_client.delete_agent(test_agent.id)
                logger.info("✓ Test agent deleted")

            except Exception as create_error:
                logger.error(f"✗ Could not create test agent: {create_error}")
                logger.error("\nPossible issues:")
                logger.error("  1. Agents API not enabled for this project")
                logger.error("  2. Model deployment name incorrect")
                logger.error("  3. Insufficient permissions")
                return False

        logger.info("\n" + "=" * 70)
        logger.info("✓ ALL TESTS PASSED")
        logger.info("=" * 70)
        logger.info("\nYour Azure AI Foundry project is ready!")
        logger.info("Next step: Run 'python scripts/create_azure_agents.py'")
        logger.info("=" * 70)

        return True

    except Exception as e:
        logger.error(f"\n✗ Connection test failed: {e}")
        logger.error("\nTroubleshooting:")
        logger.error("  1. Verify AZURE_AI_PROJECT_ENDPOINT is correct")
        logger.error("  2. Run 'az login' if using Azure CLI authentication")
        logger.error("  3. Check API key is valid if using key authentication")
        logger.error("  4. Verify you have permissions on the Azure AI project")

        import traceback
        traceback.print_exc()
        return False

    finally:
        if credential and auth_method == "default":
            await credential.close()


if __name__ == "__main__":
    try:
        success = asyncio.run(test_connection())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
