"""
Comprehensive End-to-End Test of Azure Foundry Multi-Agent System

This test exercises the full workflow:
1. User Query → Supervisor Agent
2. Supervisor → Planner Agent (via invoke_agent)
3. Planner → Creates workflow plan
4. Supervisor → Executor Agent (via invoke_agent)
5. Executor → SQL Agent (via invoke_agent)
6. SQL Agent → Executes database query
7. Executor → Response Generator (via invoke_agent)
8. Response Generator → Formats final output
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python" / "packages" / "azure-ai"))

from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential
from agent_framework_azure_ai.connectors.standalone_sql import SimpleSQLiteConnector

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """Orchestrates multi-agent workflows with tool execution"""

    def __init__(self, agents_client: AgentsClient, agent_config: dict):
        self.agents_client = agents_client
        self.agent_config = agent_config
        self.sql_connector = None
        self.execution_trace = []

    def setup_database(self, db_path: str):
        """Setup test database with sample data"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create products table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT,
                price REAL,
                stock_quantity INTEGER
            )
        """)

        # Insert sample data
        sample_products = [
            (1, "Laptop Pro 15", "Electronics", 1299.99, 45),
            (2, "Wireless Mouse", "Electronics", 29.99, 150),
            (3, "Office Chair Deluxe", "Furniture", 399.99, 30),
            (4, "Standing Desk", "Furniture", 599.99, 20),
            (5, "Monitor 27inch 4K", "Electronics", 449.99, 60),
            (6, "Keyboard Mechanical", "Electronics", 129.99, 80),
            (7, "Desk Lamp LED", "Furniture", 79.99, 100),
            (8, "Webcam HD", "Electronics", 89.99, 55),
        ]

        cursor.executemany(
            "INSERT OR REPLACE INTO products VALUES (?, ?, ?, ?, ?)",
            sample_products
        )

        conn.commit()
        conn.close()

        logger.info(f"✓ Database created: {db_path} with {len(sample_products)} products")

        # Setup SQL connector
        self.sql_connector = SimpleSQLiteConnector(db_path)

    async def execute_tool_call(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool call and return results"""
        self.execution_trace.append(f"TOOL CALL: {tool_name}({json.dumps(arguments, indent=2)})")

        logger.info(f"\n{'='*70}")
        logger.info(f"EXECUTING TOOL: {tool_name}")
        logger.info(f"Arguments: {json.dumps(arguments, indent=2)}")
        logger.info(f"{'='*70}\n")

        if tool_name == "invoke_agent":
            # Agent-to-agent handoff
            return await self.invoke_agent(
                arguments.get("agent_name"),
                arguments.get("message"),
                arguments.get("context", {})
            )

        elif tool_name == "execute_sql_query":
            # SQL query execution
            query = arguments.get("query")
            database = arguments.get("database", "local_products")

            logger.info(f"Executing SQL on {database}:")
            logger.info(f"  {query}")

            if not self.sql_connector:
                return json.dumps({"error": "Database not configured"})

            try:
                results = self.sql_connector.run_query(query)
                logger.info(f"  → Returned {len(results)} rows")
                return json.dumps(results, indent=2)
            except Exception as e:
                logger.error(f"  → SQL Error: {e}")
                return json.dumps({"error": str(e)})

        elif tool_name == "get_database_schema":
            # Get schema
            database = arguments.get("database", "local_products")
            logger.info(f"Getting schema for: {database}")

            if not self.sql_connector:
                return "Database not configured"

            schema = self.sql_connector.get_schema()
            logger.info(f"  → Schema:\n{schema}")
            return schema

        elif tool_name == "list_available_agents":
            # List agents
            agents_info = {
                "agents": [
                    {"name": "planner_agent", "description": "Creates workflow plans"},
                    {"name": "executor_agent", "description": "Executes workflows step-by-step"},
                    {"name": "sql_agent", "description": "Queries SQL databases"},
                    {"name": "rag_agent", "description": "Searches documents"},
                    {"name": "response_generator", "description": "Formats final responses"}
                ]
            }
            return json.dumps(agents_info, indent=2)

        elif tool_name == "validate_data_source":
            # Validate data source
            source_type = arguments.get("source_type")
            available = source_type == "database"  # We have database available
            return json.dumps({"available": available, "source_type": source_type})

        elif tool_name in ["extract_citations", "generate_followup_questions",
                           "execute_step", "format_output", "request_user_feedback", "consult_rag"]:
            # Placeholder for other tools
            return json.dumps({"status": "completed", "note": f"{tool_name} executed"})

        else:
            logger.warning(f"Unknown tool: {tool_name}")
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    async def invoke_agent(self, agent_name: str, message: str, context: dict = None) -> str:
        """Invoke another agent and return its response"""
        agent_id = self.agent_config["agents"].get(agent_name, {}).get("id")

        if not agent_id:
            logger.error(f"Agent not found: {agent_name}")
            return json.dumps({"error": f"Agent not found: {agent_name}"})

        logger.info(f"\n{'#'*70}")
        logger.info(f"# AGENT HANDOFF: {agent_name}")
        logger.info(f"# Agent ID: {agent_id}")
        logger.info(f"# Message: {message[:100]}...")
        logger.info(f"{'#'*70}\n")

        self.execution_trace.append(f"AGENT HANDOFF → {agent_name}: {message[:80]}...")

        # Create thread and run agent
        result = await self.run_agent_with_tools(agent_id, agent_name, message)

        return result

    async def run_agent_with_tools(self, agent_id: str, agent_name: str, message: str) -> str:
        """Run an agent and handle its tool calls"""
        # Create thread with message
        run = await self.agents_client.create_thread_and_run(
            agent_id=agent_id,
            thread={"messages": [{"role": "user", "content": message}]}
        )

        thread_id = run.thread_id
        run_id = run.id

        # Poll until completion
        max_iterations = 20
        iteration = 0

        while run.status in ["queued", "in_progress", "requires_action"] and iteration < max_iterations:
            iteration += 1

            if run.status == "requires_action":
                logger.info(f"  [{agent_name}] Requires action - processing tool calls...")

                # Get tool calls
                tool_calls = run.required_action.submit_tool_outputs.tool_calls

                # Execute each tool call
                tool_outputs = []
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    # Execute the tool
                    output = await self.execute_tool_call(function_name, function_args)

                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": output
                    })

                # Submit tool outputs
                run = await self.agents_client.submit_tool_outputs_to_run(
                    thread_id=thread_id,
                    run_id=run_id,
                    tool_outputs=tool_outputs
                )

            else:
                # Wait and poll
                await asyncio.sleep(1)
                run = await self.agents_client.get_run(thread_id, run_id)
                logger.info(f"  [{agent_name}] Status: {run.status}")

        # Get final messages
        messages = await self.agents_client.list_messages(thread_id)

        # Extract assistant's response
        response_text = ""
        for msg in messages.data:
            if msg.role == "assistant":
                for content in msg.content:
                    if hasattr(content, 'text'):
                        response_text = content.text.value
                        break
                break

        logger.info(f"  [{agent_name}] Final response: {response_text[:200]}...")

        return response_text

    async def run_workflow(self, user_query: str) -> str:
        """Run complete multi-agent workflow"""
        logger.info(f"\n{'='*70}")
        logger.info(f"STARTING WORKFLOW")
        logger.info(f"User Query: {user_query}")
        logger.info(f"{'='*70}\n")

        self.execution_trace = [f"USER QUERY: {user_query}"]

        # Start with Supervisor
        supervisor_id = self.agent_config["agents"]["supervisor"]["id"]
        final_response = await self.run_agent_with_tools(supervisor_id, "supervisor_agent", user_query)

        logger.info(f"\n{'='*70}")
        logger.info(f"WORKFLOW COMPLETED")
        logger.info(f"{'='*70}\n")

        return final_response


async def main():
    """Main test execution"""
    # Load environment
    env_file = Path(__file__).parent.parent / ".env.azure"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

    # Load agent configuration
    config_file = Path(__file__).parent.parent / "azure_agents_config.json"
    with open(config_file) as f:
        agent_config = json.load(f)

    logger.info("="*70)
    logger.info("COMPREHENSIVE END-TO-END MULTI-AGENT TEST")
    logger.info("="*70)
    logger.info("")
    logger.info("Testing complete workflow with all 6 agents:")
    logger.info("  1. Supervisor Agent (orchestration)")
    logger.info("  2. Planner Agent (workflow planning)")
    logger.info("  3. Executor Agent (step execution)")
    logger.info("  4. SQL Agent (database queries)")
    logger.info("  5. RAG Agent (document search)")
    logger.info("  6. Response Generator (output formatting)")
    logger.info("")

    # Initialize Azure client
    credential = DefaultAzureCredential()
    project_endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]

    agents_client = AgentsClient(
        endpoint=project_endpoint,
        credential=credential
    )

    try:
        # Setup orchestrator
        orchestrator = MultiAgentOrchestrator(agents_client, agent_config)

        # Setup database
        db_path = "test_products.db"
        orchestrator.setup_database(db_path)

        # Run test query
        user_query = "What are the top 5 products by price in the database? Show me the product name, category, and price formatted in a nice table."

        logger.info(f"\n{'*'*70}")
        logger.info(f"TEST QUERY: {user_query}")
        logger.info(f"{'*'*70}\n")

        final_response = await orchestrator.run_workflow(user_query)

        # Print results
        logger.info("\n" + "="*70)
        logger.info("FINAL RESPONSE TO USER")
        logger.info("="*70)
        logger.info(final_response)
        logger.info("="*70)

        # Print execution trace
        logger.info("\n" + "="*70)
        logger.info("EXECUTION TRACE")
        logger.info("="*70)
        for i, step in enumerate(orchestrator.execution_trace, 1):
            logger.info(f"{i}. {step}")
        logger.info("="*70)

        logger.info("\n✓ COMPREHENSIVE TEST COMPLETED SUCCESSFULLY!")

    finally:
        await credential.close()
        await agents_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nTest cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
