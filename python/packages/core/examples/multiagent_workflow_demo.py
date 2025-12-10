"""
Comprehensive Multi-Agent Workflow Demo

This demo showcases the complete multiagent workflow system, including:
- Setting up all 6 agents (Supervisor, Planner, Executor, Structured Data, RAG, Response Generator)
- Configuring database and vector store data sources
- Running end-to-end workflows with approval gates
- Handling user feedback
- Error handling and recovery
- Event streaming and observability

Requirements:
    - Azure OpenAI API key (or OpenAI API key)
    - SQLite database (auto-created if not exists)
    - Optional: Documents for vector store

Usage:
    python multiagent_workflow_demo.py
"""

import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict

from azure.identity import DefaultAzureCredential

# Import agent framework components
from agent_framework import ChatAgent
from agent_framework._types import ChatClientProtocol
from agent_framework.agents import (
    RAGRetrievalAgent,
    SQLAgent,
    StructuredDataAgent,
    SupervisorAgent,
    WorkflowExecutorAgent,
    WorkflowPlannerAgent,
    WorkflowResponseGenerator,
)
from agent_framework.azure import AzureOpenAIChatClient
from agent_framework.data.connectors import SQLiteConnector
from agent_framework.data.vector_store import (
    DocumentIngestionService,
    InMemoryVectorStore,
)
from agent_framework.orchestrator import (
    ApprovalDecision,
    ApprovalRequest,
    Orchestrator,
    OrchestrationContext,
)
from agent_framework.schemas import (
    SupervisorEvent,
    WorkflowInput,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ==============================================================================
# Setup Functions
# ==============================================================================


def setup_database() -> tuple[Path, SQLiteConnector]:
    """Setup SQLite database with sample data.

    Returns:
        Tuple of (database path, connector)
    """
    logger.info("Setting up SQLite database...")

    db_path = Path("demo_data.db")

    # Create database and sample tables
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create sales table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY,
            product TEXT NOT NULL,
            region TEXT NOT NULL,
            amount DECIMAL(10, 2) NOT NULL,
            sale_date DATE NOT NULL
        )
    """)

    # Create customers table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            region TEXT NOT NULL,
            signup_date DATE NOT NULL
        )
    """)

    # Insert sample data
    cursor.execute("DELETE FROM sales")  # Clear existing data
    cursor.execute("DELETE FROM customers")

    sales_data = [
        (1, "Laptop", "West", 1200.00, "2024-01-15"),
        (2, "Monitor", "West", 300.00, "2024-01-16"),
        (3, "Keyboard", "East", 80.00, "2024-01-17"),
        (4, "Mouse", "East", 25.00, "2024-01-17"),
        (5, "Laptop", "North", 1200.00, "2024-01-18"),
        (6, "Laptop", "East", 1200.00, "2024-01-19"),
        (7, "Monitor", "North", 300.00, "2024-01-20"),
        (8, "Keyboard", "West", 80.00, "2024-01-21"),
        (9, "Mouse", "North", 25.00, "2024-01-22"),
        (10, "Laptop", "West", 1200.00, "2024-01-23"),
    ]

    cursor.executemany(
        "INSERT INTO sales VALUES (?, ?, ?, ?, ?)",
        sales_data,
    )

    customers_data = [
        (1, "Alice Johnson", "West", "2023-06-01"),
        (2, "Bob Smith", "East", "2023-07-15"),
        (3, "Carol White", "North", "2023-08-20"),
        (4, "David Brown", "West", "2023-09-10"),
        (5, "Eve Davis", "East", "2023-10-05"),
    ]

    cursor.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?)",
        customers_data,
    )

    conn.commit()
    conn.close()

    logger.info(f"Database created at: {db_path}")
    logger.info(f"  - Sales records: {len(sales_data)}")
    logger.info(f"  - Customer records: {len(customers_data)}")

    # Create connector
    connector = SQLiteConnector(db_path=str(db_path))

    return db_path, connector


def setup_vector_store() -> tuple[InMemoryVectorStore, DocumentIngestionService]:
    """Setup vector store with sample documents.

    Returns:
        Tuple of (vector store, ingestion service)
    """
    logger.info("Setting up vector store...")

    vector_store = InMemoryVectorStore()
    ingestion_service = DocumentIngestionService(vector_store)

    # Add sample documents about database schema
    documents = [
        {
            "text": (
                "The sales table contains transaction records with columns: "
                "id (primary key), product (product name), region (geographic region), "
                "amount (sale amount in dollars), and sale_date (date of sale)."
            ),
            "metadata": {"source": "schema_docs", "table": "sales"},
        },
        {
            "text": (
                "The customers table stores customer information including: "
                "id (primary key), name (customer full name), region (customer's region), "
                "and signup_date (date when customer signed up)."
            ),
            "metadata": {"source": "schema_docs", "table": "customers"},
        },
        {
            "text": (
                "Our product catalog includes: Laptops (high-end computing devices, ~$1200), "
                "Monitors (display screens, ~$300), Keyboards (input devices, ~$80), "
                "and Mice (pointing devices, ~$25)."
            ),
            "metadata": {"source": "product_catalog", "type": "products"},
        },
        {
            "text": (
                "We operate in three main regions: West (California, Nevada), "
                "East (New York, Massachusetts), and North (Washington, Oregon). "
                "Each region has different market characteristics."
            ),
            "metadata": {"source": "business_info", "type": "regions"},
        },
        {
            "text": (
                "Sales analysis best practices: Always group by region when analyzing "
                "geographic trends. Use date filters for time-based analysis. "
                "Join with customers table for customer-centric insights."
            ),
            "metadata": {"source": "analytics_guide", "type": "best_practices"},
        },
    ]

    for doc in documents:
        ingestion_service.ingest(doc["text"], metadata=doc["metadata"])

    logger.info(f"Vector store populated with {len(documents)} documents")

    return vector_store, ingestion_service


def setup_chat_client() -> ChatClientProtocol:
    """Setup Azure OpenAI chat client.

    Returns:
        Chat client instance
    """
    logger.info("Setting up chat client...")

    # Try Azure OpenAI first
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if azure_endpoint:
        logger.info("Using Azure OpenAI")
        try:
            client = AzureOpenAIChatClient(
                credential=DefaultAzureCredential(),
                # model_id and endpoint will be picked from environment
            )
            return client
        except Exception as e:
            logger.warning(f"Azure OpenAI setup failed: {e}, trying OpenAI...")

    # Fallback to OpenAI
    from agent_framework.openai import OpenAIChatClient

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "No API key found. Set AZURE_OPENAI_ENDPOINT or OPENAI_API_KEY"
        )

    logger.info("Using OpenAI")
    client = OpenAIChatClient(api_key=api_key)
    return client


def setup_agents(
    chat_client: ChatClientProtocol,
    sql_connector: SQLiteConnector,
    ingestion_service: DocumentIngestionService,
) -> Dict[str, Any]:
    """Setup all agents for the workflow system.

    Args:
        chat_client: Chat client for LLM communication
        sql_connector: Database connector
        ingestion_service: Document ingestion service

    Returns:
        Dictionary of all configured agents
    """
    logger.info("Setting up agents...")

    # 1. Create SQLAgent for SQL generation
    sql_agent = SQLAgent(
        llm=lambda prompt: chat_client.run(prompt).message.text,
        few_shot_limit=3,
    )

    # 2. Create RAG Retrieval Agent
    rag_agent = RAGRetrievalAgent(
        ingestion_service=ingestion_service,
        top_k=20,
        name="rag_retrieval_agent",
    )

    # 3. Create Structured Data Agent
    structured_data_agent = StructuredDataAgent(
        sql_agent=sql_agent,
        connector=sql_connector,
        rag_agent=rag_agent,  # Enable RAG consultation for schema
        max_retry_attempts=3,
        allow_writes=False,
        name="structured_data_agent",
    )

    # 4. Create Workflow Planner Agent
    planner_agent = WorkflowPlannerAgent(
        chat_client=chat_client,
        available_agents={
            "structured_data": "Query structured databases (SQL)",
            "rag": "Search unstructured documents via semantic search",
        },
        name="workflow_planner",
    )

    # 5. Create Approval Callback
    def approval_callback(request: ApprovalRequest) -> ApprovalDecision:
        """Simple auto-approve callback for demo."""
        logger.info(f"Approval requested for: {request.step_name}")
        logger.info(f"  Type: {request.approval_type}")
        logger.info(f"  Summary: {request.summary}")

        # Auto-approve for demo (in production, this would prompt user)
        logger.info("  -> AUTO-APPROVED (demo mode)")
        return ApprovalDecision(
            approved=True,
            reason="Auto-approved for demo",
        )

    # 6. Create Orchestrator
    orchestrator = Orchestrator(
        approval_callback=approval_callback,
    )

    # 7. Create Workflow Executor Agent
    executor_agent = WorkflowExecutorAgent(
        orchestrator=orchestrator,
        feedback_callback=None,  # No user feedback for demo
        name="workflow_executor",
    )

    # 8. Create Response Generator Agent
    response_generator = WorkflowResponseGenerator(
        chat_client=chat_client,
        name="response_generator",
    )

    # 9. Create Supervisor Agent (master orchestrator)
    supervisor = SupervisorAgent(
        chat_client=chat_client,
        planner_agent=planner_agent,
        executor_agent=executor_agent,
        structured_data_agent=structured_data_agent,
        rag_agent=rag_agent,
        response_generator=response_generator,
        name="supervisor",
    )

    logger.info("All agents configured successfully")

    return {
        "supervisor": supervisor,
        "planner": planner_agent,
        "executor": executor_agent,
        "structured_data": structured_data_agent,
        "rag": rag_agent,
        "response_generator": response_generator,
        "orchestrator": orchestrator,
    }


# ==============================================================================
# Demo Workflows
# ==============================================================================


async def run_simple_sql_query(agents: Dict[str, Any]) -> None:
    """Demo 1: Simple SQL query workflow.

    Tests:
    - Supervisor request analysis
    - Planner creating simple workflow
    - Structured Data Agent executing SQL
    - Response generation
    """
    logger.info("\n" + "=" * 80)
    logger.info("DEMO 1: Simple SQL Query Workflow")
    logger.info("=" * 80)

    supervisor: SupervisorAgent = agents["supervisor"]

    query = "What were the top 3 products by total sales amount?"

    logger.info(f"\nUser Query: {query}\n")

    async for event in supervisor.process_request(query):
        _log_supervisor_event(event)

    logger.info("\n✓ Demo 1 completed successfully\n")


async def run_hybrid_workflow(agents: Dict[str, Any]) -> None:
    """Demo 2: Hybrid SQL + RAG workflow.

    Tests:
    - Multi-agent coordination
    - SQL + document search
    - Information synthesis
    """
    logger.info("\n" + "=" * 80)
    logger.info("DEMO 2: Hybrid SQL + RAG Workflow")
    logger.info("=" * 80)

    supervisor: SupervisorAgent = agents["supervisor"]

    query = (
        "Show me sales by region and include information about "
        "what products we sell and which regions we operate in."
    )

    logger.info(f"\nUser Query: {query}\n")

    async for event in supervisor.process_request(query):
        _log_supervisor_event(event)

    logger.info("\n✓ Demo 2 completed successfully\n")


async def run_complex_analysis_workflow(agents: Dict[str, Any]) -> None:
    """Demo 3: Complex multi-step analysis.

    Tests:
    - Complex workflow planning
    - Multiple SQL queries
    - Data aggregation
    - Detailed response generation
    """
    logger.info("\n" + "=" * 80)
    logger.info("DEMO 3: Complex Analysis Workflow")
    logger.info("=" * 80)

    supervisor: SupervisorAgent = agents["supervisor"]

    query = (
        "Analyze our sales performance: "
        "1) Which region has the highest sales? "
        "2) What is the most popular product? "
        "3) How many customers do we have per region?"
    )

    logger.info(f"\nUser Query: {query}\n")

    async for event in supervisor.process_request(query):
        _log_supervisor_event(event)

    logger.info("\n✓ Demo 3 completed successfully\n")


async def run_custom_workflow(agents: Dict[str, Any]) -> None:
    """Demo 4: Custom workflow with predefined input.

    Tests:
    - Manual workflow definition
    - Custom step configuration
    - Direct workflow execution
    """
    logger.info("\n" + "=" * 80)
    logger.info("DEMO 4: Custom Workflow with Predefined Input")
    logger.info("=" * 80)

    supervisor: SupervisorAgent = agents["supervisor"]

    # Create custom workflow input
    workflow_input = WorkflowInput(
        name="Sales Analysis Workflow",
        description="Analyze sales data with custom steps",
        user_prompt="Analyze sales by product and region",
        workflow_steps=[
            "Query sales data from database",
            "Search for product information in documents",
            "Generate comprehensive report",
        ],
        data_sources={},
    )

    logger.info(f"\nWorkflow Name: {workflow_input.name}")
    logger.info(f"Description: {workflow_input.description}")
    logger.info("Steps:")
    for i, step in enumerate(workflow_input.workflow_steps, 1):
        logger.info(f"  {i}. {step}")
    logger.info()

    async for event in supervisor.process_request(
        user_request=workflow_input.user_prompt,
        workflow_input=workflow_input,
    ):
        _log_supervisor_event(event)

    logger.info("\n✓ Demo 4 completed successfully\n")


# ==============================================================================
# Helper Functions
# ==============================================================================


def _log_supervisor_event(event: SupervisorEvent) -> None:
    """Log supervisor event with appropriate formatting.

    Args:
        event: Supervisor event to log
    """
    event_icons = {
        "started": "🚀",
        "analysis": "🔍",
        "planning": "📋",
        "plan_created": "✅",
        "executing": "⚙️",
        "execution_event": "📊",
        "generating_response": "✍️",
        "completed": "🎉",
        "error": "❌",
        "aborted": "🛑",
    }

    icon = event_icons.get(event.type, "ℹ️")

    logger.info(f"{icon} [{event.type.upper()}] {event.message}")

    # Log additional data for certain events
    if event.data:
        if event.type == "analysis":
            logger.info(f"   Analysis: {event.data}")
        elif event.type == "plan_created":
            logger.info(f"   Workflow ID: {event.data.get('workflow_id')}")
            logger.info(f"   Steps: {event.data.get('num_steps')}")
        elif event.type == "execution_event":
            step_name = event.data.get("step_name", "Unknown")
            event_type = event.data.get("event_type", "unknown")
            if event_type == "step_completed":
                logger.info(f"   ✓ Step completed: {step_name}")
            elif event_type == "step_failed":
                error = event.data.get("error", "Unknown error")
                logger.error(f"   ✗ Step failed: {step_name} - {error}")
        elif event.type == "completed":
            num_steps = event.data.get("num_steps_completed", 0)
            logger.info(f"   Steps completed: {num_steps}")


# ==============================================================================
# Main Entry Point
# ==============================================================================


async def main():
    """Main entry point for the demo."""
    logger.info("=" * 80)
    logger.info("Multi-Agent Workflow System - Comprehensive Demo")
    logger.info("=" * 80)

    try:
        # Setup
        logger.info("\n--- SETUP PHASE ---\n")

        db_path, sql_connector = setup_database()
        vector_store, ingestion_service = setup_vector_store()
        chat_client = setup_chat_client()

        agents = setup_agents(chat_client, sql_connector, ingestion_service)

        # Run demos
        logger.info("\n--- DEMO PHASE ---\n")

        await run_simple_sql_query(agents)
        await run_hybrid_workflow(agents)
        await run_complex_analysis_workflow(agents)
        await run_custom_workflow(agents)

        # Cleanup
        logger.info("\n--- CLEANUP ---\n")
        if db_path.exists():
            logger.info(f"Database created at: {db_path}")
            logger.info("(You can delete it manually or keep it for testing)")

        logger.info("\n" + "=" * 80)
        logger.info("All demos completed successfully! 🎉")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"\n❌ Demo failed with error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
