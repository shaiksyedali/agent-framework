"""
Verify Azure Planner Agent Deployment and Test It.

This script:
1. Verifies the Planner Agent exists in Azure Foundry
2. Retrieves its current configuration
3. Tests it with a sample planning request
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
except ImportError:
    print("ERROR: Required packages not installed. Run:")
    print("  pip install azure-ai-agents azure-identity")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def verify_and_test_planner(project_endpoint: str):
    """Verify Planner Agent deployment and test it"""

    logger.info("="*70)
    logger.info("VERIFYING AZURE PLANNER AGENT DEPLOYMENT")
    logger.info("="*70)

    credential = DefaultAzureCredential()

    try:
        agents_client = AgentsClient(
            endpoint=project_endpoint,
            credential=credential
        )

        # Load agent configuration
        config_file = Path(__file__).parent.parent / "azure_agents_config.json"
        with open(config_file) as f:
            config = json.load(f)

        planner_id = config["agents"]["planner"]["id"]

        logger.info(f"\n1. Verifying Planner Agent exists...")
        logger.info(f"   Agent ID: {planner_id}")

        # Get agent details
        agent = await agents_client.get_agent(planner_id)

        logger.info(f"   ✓ Agent found!")
        logger.info(f"   Name: {agent.name}")
        logger.info(f"   Model: {agent.model}")
        logger.info(f"   Temperature: {agent.temperature}")
        logger.info(f"   Response Format: {agent.response_format}")
        logger.info(f"   Instructions length: {len(agent.instructions)} chars")

        # Verify it has JSON response format
        if agent.response_format and agent.response_format.get("type") == "json_object":
            logger.info("   ✓ Configured for JSON output")
        else:
            logger.warning("   ⚠ Not configured for JSON output!")

        logger.info(f"\n2. Testing Planner Agent with sample request...")

        # Create a test planning request
        test_request = """Create a workflow plan for the following request:

User Intent: Analyze top 5 products by sales from the database

Available Data Sources:
[
  {
    "name": "Sales Database",
    "type": "database",
    "path": "/data/sales.db"
  }
]

Available Agents: supervisor, planner, executor, sql_agent, rag_agent, response_generator

Please analyze the request and data sources, then return a complete workflow plan in JSON format.

The plan should include:
1. Workflow name and description
2. Required agents based on the task
3. Execution steps with dependencies
4. Approval gates if needed

Return ONLY valid JSON with the workflow plan structure."""

        logger.info("   Sending test request to Azure Planner Agent...")

        # Call the agent
        result = await agents_client.create_thread_and_process_run(
            agent_id=planner_id,
            thread={
                "messages": [
                    {
                        "role": "user",
                        "content": test_request
                    }
                ]
            }
        )

        logger.info(f"   Run Status: {result.status}")
        logger.info(f"   Thread ID: {result.thread_id}")

        if result.status == "completed":
            logger.info("   ✓ Planner Agent responded successfully")

            # Get the response from the thread
            from azure.ai.agents.models import MessageRole
            messages = await agents_client.get_messages(thread_id=result.thread_id)

            # Find assistant's response
            content = ""
            for message in messages.data:
                if message.role == MessageRole.ASSISTANT:
                    if message.content and len(message.content) > 0:
                        content = str(message.content[0].text.value)
                        break

            if not content:
                logger.error("   ✗ No response content found")
                return False

            logger.info(f"\n3. Planner Agent Response:")
            logger.info("   " + "-"*66)
            logger.info(f"   {content[:500]}...")
            logger.info("   " + "-"*66)

            # Try to parse as JSON
            try:
                import re
                # Try direct parsing
                try:
                    plan_json = json.loads(content)
                except json.JSONDecodeError:
                    # Try extracting JSON from markdown
                    json_match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
                    if json_match:
                        plan_json = json.loads(json_match.group(1))
                    else:
                        json_match = re.search(r'\{.*\}', content, re.DOTALL)
                        if json_match:
                            plan_json = json.loads(json_match.group(0))
                        else:
                            raise ValueError("No JSON found")

                logger.info(f"\n4. Parsed Plan:")
                logger.info(f"   ✓ Valid JSON response")
                logger.info(f"   Workflow Name: {plan_json.get('name', 'N/A')}")
                logger.info(f"   Description: {plan_json.get('description', 'N/A')}")
                logger.info(f"   Steps: {len(plan_json.get('steps', []))}")

                if plan_json.get('steps'):
                    logger.info(f"\n   Steps breakdown:")
                    for i, step in enumerate(plan_json['steps'], 1):
                        logger.info(f"     {i}. {step.get('step_name', 'Unnamed')} ({step.get('agent', 'N/A')})")

                logger.info("\n" + "="*70)
                logger.info("✓✓✓ PLANNER AGENT VERIFIED AND WORKING ✓✓✓")
                logger.info("="*70)

            except Exception as e:
                logger.error(f"\n   ✗ Failed to parse response as JSON: {e}")
                logger.error("   Planner may not be returning valid JSON")
                return False

            return True

        elif result.status == "failed":
            logger.error(f"   ✗ Planner Agent failed")
            if hasattr(result, 'last_error') and result.last_error:
                logger.error(f"   Error: {result.last_error}")
            return False

        else:
            logger.warning(f"   ⚠ Unexpected status: {result.status}")
            return False

    except Exception as e:
        logger.error(f"\n✗✗✗ VERIFICATION FAILED ✗✗✗")
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await credential.close()
        await agents_client.close()


def main():
    # Load environment
    env_file = Path(__file__).parent.parent / ".env.azure"
    if env_file.exists():
        logger.info(f"Loading environment from: {env_file}\n")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value
    else:
        logger.warning(".env.azure not found, using existing environment variables\n")

    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    if not project_endpoint:
        logger.error("ERROR: AZURE_AI_PROJECT_ENDPOINT not set")
        sys.exit(1)

    logger.info(f"Project endpoint: {project_endpoint}\n")

    try:
        success = asyncio.run(verify_and_test_planner(project_endpoint))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
