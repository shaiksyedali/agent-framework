# Multi-Agent Workflow System

A comprehensive multiagent framework for building dynamic, orchestrated workflows with SQL, RAG, and custom agents.

## Overview

This system provides 6 specialized agents that work together to handle complex workflows:

1. **Supervisor Agent** - Master orchestrator that coordinates all agents
2. **Planner Agent** - Creates workflow plans (human-readable + executable)
3. **Executor Agent** - Executes workflows step-by-step with feedback
4. **Structured Data Agent** - SQL query generation and execution with RAG
5. **RAG Retrieval Agent** - Semantic document search
6. **Response Generator** - Formats final responses with citations

## Architecture

```
User Request
    ↓
┌─────────────────────┐
│  Supervisor Agent   │  ← Analyzes request, coordinates workflow
└─────────────────────┘
    ↓
┌─────────────────────┐
│   Planner Agent     │  ← Creates execution plan
└─────────────────────┘
    ↓ (user approval)
    ↓
┌─────────────────────┐
│  Executor Agent     │  ← Runs workflow step-by-step
└─────────────────────┘
    │
    ├──→ Structured Data Agent  ← SQL queries (may consult RAG)
    │
    ├──→ RAG Agent              ← Document search
    │
    └──→ (stores results in context)
    ↓
┌─────────────────────┐
│ Response Generator  │  ← Formats final answer
└─────────────────────┘
    ↓
  User
```

## Quick Start

### Installation

```bash
# The agents are already part of the agent_framework package
# Just import and use them
```

### Simple Example

```python
from agent_framework.agents import (
    SupervisorAgent,
    WorkflowPlannerAgent,
    WorkflowExecutorAgent,
    StructuredDataAgent,
    RAGRetrievalAgent,
    WorkflowResponseGenerator,
)

# See simple_workflow_example.py for complete setup
```

### Run Demo

```bash
# Simple workflow (5 minutes)
python simple_workflow_example.py

# Comprehensive demo (15 minutes)
python multiagent_workflow_demo.py
```

## Agent Details

### 1. Supervisor Agent

**Purpose**: Master orchestrator coordinating all workflow activities

**Capabilities**:
- Analyzes incoming requests to determine task type
- Identifies required agents (SQL, RAG, both)
- Delegates to Planner → Executor → Response Generator
- Handles errors and recovery
- Event streaming for observability

**Usage**:
```python
supervisor = SupervisorAgent(
    chat_client=chat_client,
    planner_agent=planner,
    executor_agent=executor,
    structured_data_agent=sql_agent,
    rag_agent=rag_agent,
    response_generator=response_gen,
)

async for event in supervisor.process_request("What were our top products?"):
    print(f"{event.type}: {event.message}")
```

### 2. Planner Agent

**Purpose**: Creates structured workflow plans

**Capabilities**:
- Analyzes user requirements
- Determines optimal agent selection and order
- Identifies approval gates
- Creates both human-readable plans (markdown) AND executable StepGraphs
- Validates data source availability

**Usage**:
```python
planner = WorkflowPlannerAgent(
    chat_client=chat_client,
    available_agents={
        "structured_data": "Query databases with SQL",
        "rag": "Search documents via semantic search",
    },
)

plan = await planner.plan_workflow(workflow_input)
graph = planner.build_step_graph(plan, context)
```

### 3. Executor Agent

**Purpose**: Step-by-step workflow execution

**Capabilities**:
- Executes StepGraphs from Planner
- Formats outputs (tables, text, JSON)
- Supports user feedback (proceed/rerun/abort)
- Event streaming for progress tracking
- Error handling with recovery options

**Usage**:
```python
executor = WorkflowExecutorAgent(
    orchestrator=orchestrator,
    feedback_callback=my_feedback_handler,  # Optional
)

async for event in executor.execute_workflow(plan, context, graph_builder):
    if event.type == "step_completed":
        print(f"Step done: {event.output}")
```

### 4. Structured Data Agent

**Purpose**: SQL query generation and execution

**Capabilities**:
- Generates SQL from natural language
- Consults RAG agent for schema documentation
- Retry logic (up to 3 attempts)
- Detects aggregations and fetches raw records
- Supports SQLite, DuckDB, PostgreSQL
- Write protection and row limits

**Usage**:
```python
structured_data_agent = StructuredDataAgent(
    sql_agent=sql_agent,
    connector=sql_connector,
    rag_agent=rag_agent,  # Optional, for schema docs
    max_retry_attempts=3,
    allow_writes=False,
)

response = await structured_data_agent.run("Get top 10 customers")
result = response.value  # StructuredDataResult
print(result.sql)  # Generated SQL
print(result.results)  # Query results
```

### 5. RAG Retrieval Agent

**Purpose**: Semantic document search

**Capabilities**:
- Semantic search over vector store
- Configurable result count (default: 20)
- Returns results with citations and metadata
- Built on DocumentIngestionService

**Usage**:
```python
rag_agent = RAGRetrievalAgent(
    ingestion_service=ingestion_service,
    top_k=20,
)

response = await rag_agent.run("Find product documentation")
evidence = response.value  # List[RetrievedEvidence]
```

### 6. Response Generator Agent

**Purpose**: Final response formatting

**Capabilities**:
- Synthesizes information from multiple steps
- Generates executive summaries
- Includes citations for all sources
- Suggests follow-up questions
- Professional markdown formatting

**Usage**:
```python
response_gen = WorkflowResponseGenerator(chat_client=chat_client)

response = await response_gen.generate_response(
    workflow_outputs=[...],
    original_query="What were sales last quarter?",
)
```

## Data Flow

### Context Propagation

Agents communicate through `OrchestrationContext`:

```python
context = OrchestrationContext(
    workflow_id="wf-123",
    connectors={"database": sql_connector, "vector_store": vector_store},
    transient_artifacts={},  # Results stored here
)

# Agents registered in context
context.transient_artifacts["agent_structured_data"] = sql_agent
context.transient_artifacts["agent_rag"] = rag_agent

# Step results stored by step_id
context.transient_artifacts["step_1"] = result_1
context.transient_artifacts["step_2"] = result_2
```

### Message Flow

```
Step 1 (SQL Query)
    → Executes, stores result in context.transient_artifacts["step_1"]
    ↓
Step 2 (RAG Search)
    → Can access step_1 result via context
    → Stores result in context.transient_artifacts["step_2"]
    ↓
Step 3 (Synthesize)
    → Accesses both step_1 and step_2 results
    → Produces final output
```

## Approval System

### Approval Types

- `ApprovalType.SQL` - SQL queries (especially writes)
- `ApprovalType.MCP` - External API calls
- `ApprovalType.CUSTOM` - Custom approval gates

### Approval Callback

```python
def my_approval_callback(request: ApprovalRequest) -> ApprovalDecision:
    print(f"Approve {request.step_name}?")
    print(f"Type: {request.approval_type}")
    print(f"Summary: {request.summary}")

    # Get user input
    user_input = input("Approve? (y/n): ")

    return ApprovalDecision(
        approved=(user_input.lower() == 'y'),
        reason="User decision",
    )

orchestrator = Orchestrator(approval_callback=my_approval_callback)
```

## Configuration

### Environment Variables

```bash
# Azure OpenAI (recommended)
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
export AZURE_OPENAI_DEPLOYMENT=gpt-4
export AZURE_OPENAI_API_KEY=your-key

# Or OpenAI
export OPENAI_API_KEY=your-openai-key

# Optional: Embeddings
export AZURE_EMBED_DEPLOYMENT=text-embedding-3-small
```

### Database Setup

```python
from agent_framework.data.connectors import SQLiteConnector

# SQLite
connector = SQLiteConnector(db_path="data.db")

# DuckDB
from agent_framework.data.connectors import DuckDBConnector
connector = DuckDBConnector(db_path="data.duckdb")

# PostgreSQL
from agent_framework.data.connectors import PostgresConnector
connector = PostgresConnector(
    connection_string="postgresql://user:pass@localhost/db"
)
```

### Vector Store Setup

```python
from agent_framework.data.vector_store import (
    InMemoryVectorStore,
    DocumentIngestionService,
)

# Create vector store
vector_store = InMemoryVectorStore()
ingestion_service = DocumentIngestionService(vector_store)

# Ingest documents
ingestion_service.ingest(
    text="Your document text here",
    metadata={"source": "docs", "page": 1},
)
```

## Advanced Usage

### Custom Workflow Input

```python
from agent_framework.schemas import WorkflowInput

workflow_input = WorkflowInput(
    name="Custom Analysis",
    description="Analyze sales with specific steps",
    user_prompt="Show me Q4 sales by region",
    workflow_steps=[
        "Query sales database",
        "Search for regional info",
        "Generate report",
    ],
    data_sources={"database": connector},
)

async for event in supervisor.process_request(
    user_request="",
    workflow_input=workflow_input,
):
    print(event.message)
```

### Dynamic Workflow Construction

```python
from agent_framework.orchestrator import (
    create_sequential_graph,
    create_parallel_graph,
)

# Sequential workflow
steps = [
    {"step_id": "step1", "name": "Query", "action": query_fn},
    {"step_id": "step2", "name": "Format", "action": format_fn},
]
graph = create_sequential_graph(steps, context)

# Parallel workflow
parallel_steps = [
    {"step_id": "query1", "name": "Query A", "action": fn1},
    {"step_id": "query2", "name": "Query B", "action": fn2},
]
merge_step = {"step_id": "merge", "name": "Combine", "action": merge_fn}
graph = create_parallel_graph(parallel_steps, context, merge_step)
```

### Error Handling

```python
try:
    async for event in supervisor.process_request(query):
        if event.type == "error":
            print(f"Error: {event.message}")
            # Handle error
        elif event.type == "completed":
            print(f"Success: {event.data}")
except Exception as e:
    print(f"Workflow failed: {e}")
```

## Testing

### Unit Testing Agents

```python
import pytest
from unittest.mock import Mock

@pytest.mark.asyncio
async def test_structured_data_agent():
    # Mock dependencies
    mock_sql_agent = Mock()
    mock_connector = Mock()
    mock_connector.get_schema.return_value = "table: col1, col2"

    agent = StructuredDataAgent(
        sql_agent=mock_sql_agent,
        connector=mock_connector,
    )

    response = await agent.run("Get all records")
    assert response is not None
```

### Integration Testing

```python
@pytest.mark.asyncio
async def test_end_to_end_workflow():
    # Setup all agents
    supervisor = setup_supervisor()

    # Run workflow
    events = []
    async for event in supervisor.process_request("Test query"):
        events.append(event)

    # Assertions
    assert events[0].type == "started"
    assert events[-1].type == "completed"
    assert any(e.type == "plan_created" for e in events)
```

## Troubleshooting

### Common Issues

**1. Import Errors**

```python
# Make sure you're importing from the correct location
from agent_framework.agents import SupervisorAgent  # Correct
from agent_framework.supervisor_agent import SupervisorAgent  # Wrong
```

**2. API Key Not Found**

```bash
# Check environment variables
echo $AZURE_OPENAI_ENDPOINT
echo $OPENAI_API_KEY

# Set them if missing
export OPENAI_API_KEY=your-key
```

**3. Database Connection Issues**

```python
# Verify database path
db_path = Path("data.db")
assert db_path.exists(), f"Database not found: {db_path}"

# Check connector
connector = SQLiteConnector(db_path=str(db_path))
schema = connector.get_schema()
print(schema)  # Should show tables
```

**4. Empty Responses**

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check if agents are registered in context
print(context.transient_artifacts.keys())
```

## Performance Optimization

### Caching

```python
# Cache SQL query results
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_query(sql: str):
    return connector.run_query(sql)
```

### Parallel Execution

```python
# Run independent agents in parallel
import asyncio

results = await asyncio.gather(
    sql_agent.run(query1),
    rag_agent.run(query2),
)
```

### Row Limiting

```python
# Limit results for large datasets
agent = StructuredDataAgent(
    sql_agent=sql_agent,
    connector=connector,
    row_limit=100,  # Max 100 rows
)
```

## Next Steps

1. **Implement RAG-Based SQL Few-Shot Retrieval**
   - Vector store for SQL examples
   - Hybrid search for similar queries
   - Success tracking

2. **Add Workflow Templates**
   - Pre-built workflows for common patterns
   - Template library
   - Customization support

3. **Enhance Visualization**
   - Chart generation for data
   - Interactive dashboards
   - Export capabilities

4. **UI Integration**
   - Connect to existing HIL UI
   - Workflow builder interface
   - Real-time monitoring

## Resources

- [Agent Framework Documentation](../README.md)
- [SQL Agent Guide](../agents/sql.py)
- [Orchestrator Guide](../orchestrator/README.md)
- [Examples Directory](.)

## Support

For issues, questions, or contributions, please refer to the main project repository.
