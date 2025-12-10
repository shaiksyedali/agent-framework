"""
Simple Multi-Agent Workflow Example

A minimal example showing how to use the multiagent workflow system
for a simple SQL query task.

This example demonstrates:
- Basic agent setup
- Simple SQL query workflow
- Event streaming
- Minimal configuration

Usage:
    python simple_workflow_example.py
"""

import asyncio
import logging
import os
import sqlite3
from pathlib import Path

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
from agent_framework.orchestrator import ApprovalDecision, Orchestrator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_sample_database() -> Path:
    """Create a simple SQLite database with sample data."""
    db_path = Path("simple_demo.db")

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create products table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price DECIMAL(10, 2) NOT NULL,
            stock INTEGER NOT NULL
        )
    """)

    # Insert sample data
    cursor.execute("DELETE FROM products")
    products = [
        (1, "Laptop", "Electronics", 999.99, 15),
        (2, "Mouse", "Electronics", 29.99, 50),
        (3, "Desk Chair", "Furniture", 199.99, 10),
        (4, "Monitor", "Electronics", 299.99, 20),
        (5, "Desk Lamp", "Furniture", 49.99, 30),
    ]

    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", products)
    conn.commit()
    conn.close()

    logger.info(f"Created database with {len(products)} products")
    return db_path


async def main():
    """Run a simple workflow example."""
    print("\n" + "=" * 60)
    print("Simple Multi-Agent Workflow Example")
    print("=" * 60 + "\n")

    # 1. Create sample database
    print("📁 Creating sample database...")
    db_path = create_sample_database()
    sql_connector = SQLiteConnector(db_path=str(db_path))

    # 2. Setup vector store (optional, for schema docs)
    print("📚 Setting up vector store...")
    vector_store = InMemoryVectorStore()
    ingestion_service = DocumentIngestionService(vector_store)

    # Add schema documentation
    ingestion_service.ingest(
        "The products table contains: id (primary key), name (product name), "
        "category (product category), price (in dollars), and stock (quantity available).",
        metadata={"source": "schema_docs"},
    )

    # 3. Setup chat client
    print("🤖 Setting up chat client...")

    # Try Azure OpenAI
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if azure_endpoint:
        from azure.identity import DefaultAzureCredential

        chat_client = AzureOpenAIChatClient(credential=DefaultAzureCredential())
        print("   Using Azure OpenAI")
    else:
        # Fallback to OpenAI
        from agent_framework.openai import OpenAIChatClient

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Set AZURE_OPENAI_ENDPOINT or OPENAI_API_KEY")

        chat_client = OpenAIChatClient(api_key=api_key)
        print("   Using OpenAI")

    # 4. Create agents
    print("⚙️  Creating agents...")

    # SQL Agent
    sql_agent = SQLAgent(
        llm=lambda prompt: chat_client.run(prompt).message.text,
    )

    # RAG Agent
    rag_agent = RAGRetrievalAgent(
        ingestion_service=ingestion_service,
        top_k=5,
    )

    # Structured Data Agent
    structured_data_agent = StructuredDataAgent(
        sql_agent=sql_agent,
        connector=sql_connector,
        rag_agent=rag_agent,
        allow_writes=False,
    )

    # Planner Agent
    planner_agent = WorkflowPlannerAgent(
        chat_client=chat_client,
        available_agents={
            "structured_data": "Query databases with SQL",
            "rag": "Search documents",
        },
    )

    # Auto-approve callback (for demo)
    def auto_approve(request):
        print(f"   ✓ Auto-approving: {request.step_name}")
        return ApprovalDecision(approved=True, reason="Demo auto-approve")

    # Executor Agent
    executor_agent = WorkflowExecutorAgent(
        orchestrator=Orchestrator(approval_callback=auto_approve),
    )

    # Response Generator
    response_generator = WorkflowResponseGenerator(chat_client=chat_client)

    # Supervisor (master orchestrator)
    supervisor = SupervisorAgent(
        chat_client=chat_client,
        planner_agent=planner_agent,
        executor_agent=executor_agent,
        structured_data_agent=structured_data_agent,
        rag_agent=rag_agent,
        response_generator=response_generator,
    )

    print("   ✓ All agents ready!\n")

    # 5. Run workflow
    query = "What are the top 3 most expensive products?"

    print(f"❓ User Query: {query}\n")
    print("🔄 Processing workflow...\n")

    final_response = None
    async for event in supervisor.process_request(query):
        # Print event
        icon = {
            "started": "🚀",
            "analysis": "🔍",
            "planning": "📋",
            "plan_created": "✅",
            "executing": "⚙️",
            "execution_event": "📊",
            "generating_response": "✍️",
            "completed": "🎉",
            "error": "❌",
        }.get(event.type, "ℹ️")

        print(f"{icon} {event.message}")

        # Capture final response
        if event.type == "completed" and event.data:
            final_response = event.data.get("response")

    # 6. Display final response
    if final_response:
        print("\n" + "=" * 60)
        print("📄 Final Response:")
        print("=" * 60)
        print(final_response)
        print("=" * 60)

    print("\n✅ Workflow completed successfully!")
    print(f"💾 Database saved at: {db_path}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
