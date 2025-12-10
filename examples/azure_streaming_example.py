"""
Azure Foundry Streaming Workflow Example

Demonstrates real-time streaming responses from Azure Foundry agents.

Usage:
    python examples/azure_streaming_example.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python" / "packages" / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent / "python" / "packages" / "azure-ai"))

from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential
from agent_framework_azure_ai import AzureFoundryAgentAdapter


async def main():
    """Stream agent responses"""

    # Load configuration
    config_file = Path(__file__).parent.parent / "azure_agents_config.json"
    with open(config_file) as f:
        config = json.load(f)

    # Initialize
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        credential=credential,
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    )

    # Create supervisor adapter
    supervisor = AzureFoundryAgentAdapter(
        agents_client=project_client.agents,
        agent_id=config["agents"]["supervisor"]["id"],
        agent_name="supervisor_agent"
    )

    # Stream response
    print("\nStreaming workflow execution:\n")
    print("-" * 60)

    async for update in supervisor.run_stream("Explain the benefits of multi-agent systems in 3 bullet points"):
        if update.contents:
            print(update.contents, end="", flush=True)

    print("\n" + "-" * 60)

    await credential.close()


if __name__ == "__main__":
    asyncio.run(main())
