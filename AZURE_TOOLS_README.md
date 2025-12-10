# Azure Tools Integration

Complete implementation of hybrid local/cloud tools for Azure Foundry multi-agent system.

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Components](#components)
- [Setup & Installation](#setup--installation)
- [Deployment](#deployment)
- [Usage](#usage)
- [Tool Types](#tool-types)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## 🎯 Overview

This implementation provides a **hybrid architecture** that seamlessly integrates:

- **Local Tools** - Direct Python execution for `.db` and `.duckdb` files
- **Cloud Tools** - Azure Functions for Azure SQL, Azure AI Search, and MCP servers

The system **automatically selects** the appropriate tool (local vs cloud) based on the data source type, providing optimal performance and cost efficiency.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Azure Foundry Agents                         │
│  (supervisor, planner, executor, sql_agent, rag_agent, etc.)   │
└─────────────────┬───────────────────────────────────────────────┘
                  │
                  ├─────────────────────────────────────────────┐
                  │                                             │
         ┌────────▼────────┐                       ┌───────────▼──────────┐
         │  ToolExecutor   │                       │   ToolExecutor       │
         │  (Local Tools)  │                       │   (Cloud Tools)      │
         └────────┬────────┘                       └───────────┬──────────┘
                  │                                            │
    ┌─────────────┴─────────────┐                 ┌───────────┴──────────┐
    │                           │                 │                      │
┌───▼──────┐          ┌────────▼────────┐   ┌────▼────────┐   ┌────────▼───────┐
│ SQLite/  │          │    DuckDB       │   │   Azure     │   │  Azure AI      │
│ Local DB │          │    Local DB     │   │ Functions   │   │    Search      │
└──────────┘          └─────────────────┘   └─────────────┘   └────────────────┘
                                                    │                  │
                                              ┌─────▼──────┐    ┌──────▼─────┐
                                              │ Azure SQL  │    │ Vector DB  │
                                              │  Database  │    │   + Docs   │
                                              └────────────┘    └────────────┘
```

### Key Components:

1. **ToolSelector** - Analyzes data sources and selects appropriate tools
2. **LocalSQLTools** - Async Python tools for local databases
3. **Azure Functions** - Cloud-hosted tools for Azure SQL and RAG
4. **AzureToolsIntegration** - Orchestrates tool registration and execution
5. **AzureFoundryAgentAdapter** - Bridges Azure agents with local protocol

## 📦 Components

### 1. Local SQL Tools

**Location:** `python/packages/core/agent_framework/tools/local_sql_tools.py`

**Features:**
- Async execution for SQLite and DuckDB
- Methods: `query_database`, `get_database_schema`, `list_tables`, `describe_table`
- Automatic database type detection
- JSON response format

**Example:**
```python
from agent_framework.tools import LocalSQLTools

tools = LocalSQLTools("/path/to/database.db")
result = await tools.query_database("SELECT * FROM users LIMIT 10")
```

### 2. Tool Selector

**Location:** `python/packages/core/agent_framework/tools/tool_selector.py`

**Features:**
- Intelligent routing based on data source type
- Returns separate lists for local and cloud tools
- Metadata tracking for debugging

**Decision Logic:**
- `.db`, `.duckdb` files → Local SQL Tools
- Azure SQL connection string → Cloud SQL Tool (Azure Function)
- `.pdf`, `.docx`, `.md` files → Cloud RAG Tool (Azure AI Search)
- MCP server URL → Cloud MCP Tool (Azure Function)

**Example:**
```python
from agent_framework.tools import ToolSelector

selector = ToolSelector(azure_functions_url="https://myapp.azurewebsites.net")
tools = selector.select_tools(data_sources)

print(f"Local tools: {len(tools['local_tools'])}")
print(f"Cloud tools: {len(tools['cloud_tools'])}")
```

### 3. Azure Functions

**Location:** `azure-functions/`

**Functions:**
- `execute_azure_sql` - Execute SQL queries on Azure SQL Database
- `get_azure_sql_schema` - Get database schema information
- `consult_rag` - Search documents using Azure AI Search

**Authentication:**
- Managed Identity (recommended for production)
- API Key (for development)

### 4. Azure Tools Integration

**Location:** `python/packages/core/agent_framework/azure/azure_tools_integration.py`

**Features:**
- Creates `ToolExecutor` with all tools registered
- Handles both local and cloud tool execution
- HTTP client for Azure Functions
- Factory functions for agent creation

**Key Classes:**
- `AzureToolsIntegration` - Main integration class
- `create_agent_with_tools()` - Factory to create single agent
- `create_multi_agent_system()` - Factory to create multiple agents

## 🚀 Setup & Installation

### Prerequisites

1. **Python 3.11+**
2. **Azure CLI** - `az --version`
3. **Azure Functions Core Tools** (optional, for local testing)
   ```bash
   npm install -g azure-functions-core-tools@4
   ```

### Installation

1. **Install Python dependencies:**
   ```bash
   cd python/packages/core
   pip install -e .
   
   cd ../../azure-ai
   pip install -e .
   ```

2. **Install Azure Functions dependencies:**
   ```bash
   cd azure-functions
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.azure.example .env.azure
   # Edit .env.azure with your Azure credentials
   ```

### Environment Variables

Required in `.env.azure`:

```bash
# Azure AI Foundry Project
AZURE_AI_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com/api/projects/yourproject
AZURE_SUBSCRIPTION_ID=your-subscription-id
AZURE_RESOURCE_GROUP=your-resource-group
AZURE_PROJECT_NAME=your-project-name

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-openai.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2025-01-01-preview
AZURE_EMBED_DEPLOYMENT=text-embedding-3-small
AZURE_EMBED_DIM=1536

# Azure AI Search (RAG)
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_INDEX=your-index
SEMANTIC_CONFIG_NAME=default

# Azure SQL (optional)
AZURE_SQL_CONNECTION_STRING=your-connection-string
```

## 📤 Deployment

### Deploy Azure Functions

```bash
# Make deployment script executable
chmod +x scripts/deploy_azure_functions.sh

# Run deployment
./scripts/deploy_azure_functions.sh
```

This script will:
1. ✅ Create/verify resource group
2. ✅ Create storage account
3. ✅ Create function app
4. ✅ Configure app settings
5. ✅ Enable managed identity
6. ✅ Deploy functions
7. ✅ Retrieve function keys

**Output:**
```
Function App: yourproject-functions
URL: https://yourproject-functions.azurewebsites.net
Host Key: ***************
```

### Update .env.azure

Add the deployment outputs:

```bash
AZURE_FUNCTIONS_URL=https://yourproject-functions.azurewebsites.net
AZURE_FUNCTIONS_KEY=your-function-key
```

### Test Deployment

```bash
python scripts/test_azure_functions.py
```

Expected output:
```
✓ consult_rag test PASSED
✓ get_azure_sql_schema test PASSED
✓ execute_azure_sql test PASSED

Results: 3/3 tests passed
✓ All tests passed!
```

## 💻 Usage

### Basic Usage - Single Agent

```python
import asyncio
import os
from dataclasses import dataclass

from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential

from agent_framework.azure import create_agent_with_tools


@dataclass
class DataSourceConfig:
    id: str
    name: str
    type: str
    path: str = None
    connection_string: str = None


async def main():
    # Initialize Azure client
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        credential=credential,
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    )
    
    # Define data sources
    data_sources = [
        DataSourceConfig(
            id="ds-1",
            name="Sales Database",
            type="file",
            path="/data/sales.db"
        )
    ]
    
    # Create SQL agent with tools
    sql_agent = create_agent_with_tools(
        agents_client=project_client.agents,
        agent_id="asst_WyXNFtXxcLqqUQKrlwkr3g3U",  # From azure_agents_config.json
        agent_name="sql_agent",
        data_sources=data_sources,
        azure_functions_url=os.environ["AZURE_FUNCTIONS_URL"]
    )
    
    # Use the agent
    result = await sql_agent.run(
        "What are the top 10 customers by revenue?"
    )
    
    print(result.messages[0].text)
    
    await project_client.close()
    await credential.close()


if __name__ == "__main__":
    asyncio.run(main())
```

### Advanced Usage - Multi-Agent System

```python
from agent_framework.azure import create_multi_agent_system

# Load agent configs
with open("azure_agents_config.json", "r") as f:
    agent_config = json.load(f)

# Create all agents
agents = create_multi_agent_system(
    agents_client=project_client.agents,
    agent_configs={
        "supervisor": {"id": agent_config["agents"]["supervisor"]["id"]},
        "sql_agent": {"id": agent_config["agents"]["sql_agent"]["id"]},
        "rag_agent": {"id": agent_config["agents"]["rag_agent"]["id"]},
    },
    data_sources=data_sources,
    azure_functions_url=os.environ["AZURE_FUNCTIONS_URL"]
)

# Use agents
sql_result = await agents["sql_agent"].run("Query the database")
rag_result = await agents["rag_agent"].run("Search the documents")
```

## 🛠️ Tool Types

### Local SQL Tools

**When Used:** `.db` or `.duckdb` files

**Available Methods:**
1. `query_database(query: str)` - Execute SQL query
2. `get_database_schema()` - Get complete schema
3. `list_tables()` - List all tables
4. `describe_table(table_name: str)` - Get table details

**Example Call:**
```json
{
  "tool_call_id": "call_abc123",
  "function": {
    "name": "query_database",
    "arguments": "{\"query\": \"SELECT * FROM users LIMIT 10\"}"
  }
}
```

### Cloud SQL Tools (Azure Functions)

**When Used:** Azure SQL Database connection string

**Available Methods:**
1. `execute_azure_sql(query: str, database: str)` - Execute query
2. `get_azure_sql_schema(database: str)` - Get schema

**Example Call:**
```json
{
  "tool_call_id": "call_xyz789",
  "function": {
    "name": "execute_azure_sql",
    "arguments": "{\"query\": \"SELECT TOP 10 * FROM customers\", \"database\": \"production\"}"
  }
}
```

### Cloud RAG Tools (Azure AI Search)

**When Used:** `.pdf`, `.docx`, `.md`, `.txt` files

**Available Methods:**
1. `consult_rag(query: str, top_k: int, search_type: str)` - Search documents

**Search Types:**
- `hybrid` - Recommended (vector + semantic + keyword)
- `semantic` - Semantic search only
- `vector` - Vector search only

**Example Call:**
```json
{
  "tool_call_id": "call_def456",
  "function": {
    "name": "consult_rag",
    "arguments": "{\"query\": \"What is the voltage range?\", \"top_k\": 5, \"search_type\": \"hybrid\"}"
  }
}
```

## 📝 Examples

### Example 1: Test Local SQL Tools

```bash
python python/packages/core/examples/test_local_sql_tools.py
```

This will:
1. Create a sample SQLite database
2. Test all LocalSQLTools methods
3. Display results

### Example 2: Complete Multi-Agent Workflow

```bash
python python/packages/core/examples/azure_sql_rag_example.py
```

This demonstrates:
1. Local SQL query
2. RAG document search
3. Hybrid workflow (SQL + RAG)

## 🔧 Troubleshooting

### Issue: "Function not found" errors

**Solution:** Ensure tools are registered with ToolExecutor:

```python
# Check registered tools
print(tool_executor.list_tools())

# Expected output:
# ['query_database', 'get_database_schema', 'consult_rag', ...]
```

### Issue: Azure Functions timeout

**Solution:** Increase timeout in Azure Functions configuration:

```bash
az functionapp config appsettings set \
    --name yourapp-functions \
    --resource-group yourgroup \
    --settings "FUNCTIONS_WORKER_PROCESS_COUNT=4"
```

### Issue: "Module not found" errors

**Solution:** Ensure proper Python path:

```python
import sys
sys.path.insert(0, "/path/to/python/packages/core")
```

### Issue: Azure AI Search returns no results

**Solution:** Verify documents are ingested:

1. Check Azure AI Search portal
2. Verify index exists and has documents
3. Test search manually in portal

### Issue: Managed Identity authentication fails

**Solution:** Use API key for development:

```python
integration = AzureToolsIntegration(
    agents_client=project_client.agents,
    azure_functions_url=azure_functions_url,
    api_key=os.environ.get("AZURE_FUNCTIONS_KEY")  # Add API key
)
```

## 📚 Additional Resources

- [Azure AI Foundry Documentation](https://learn.microsoft.com/en-us/azure/ai-studio/)
- [Azure Functions Documentation](https://learn.microsoft.com/en-us/azure/azure-functions/)
- [Azure AI Search Documentation](https://learn.microsoft.com/en-us/azure/search/)
- [Azure SQL Database Documentation](https://learn.microsoft.com/en-us/azure/azure-sql/)

## 🎉 Summary

You now have a complete hybrid architecture that:

✅ Automatically selects local vs cloud tools  
✅ Executes local SQL queries efficiently  
✅ Scales to Azure SQL for production workloads  
✅ Performs semantic search on documents  
✅ Integrates seamlessly with Azure Foundry agents  
✅ Provides comprehensive error handling  
✅ Supports managed identity for secure authentication  

**Next Steps:**
1. Deploy Azure Functions
2. Test all tool types
3. Build your multi-agent workflows
4. Monitor and optimize performance

Happy building! 🚀
