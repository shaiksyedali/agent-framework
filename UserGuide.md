# Azure Foundry Multi-Agent Framework - User Guide

## Table of Contents
1. [Overview](#overview)
2. [Deployment Patterns: Local vs Cloud Tools](#deployment-patterns-local-vs-cloud-tools)
   - [Decision Framework](#decision-framework)
   - [Pattern A: Local Tools](#pattern-a-local-tools)
   - [Pattern B: Cloud Tools](#pattern-b-cloud-tools---recommended)
   - [Pattern C: Hybrid](#pattern-c-hybrid)
   - [Comparison & Recommendations](#comparison-and-recommendations)
3. [Intelligent Workflow Orchestration with Human-in-the-Loop](#intelligent-workflow-orchestration-with-human-in-the-loop)
   - [System Architecture](#system-architecture)
   - [Data Source Intelligence](#data-source-intelligence)
   - [Workflow Execution Flow](#workflow-execution-flow)
   - [Example: PI10 Assistant](#example-pi10-assistant-workflow)
4. [Prerequisites](#prerequisites)
5. [Required Information from User](#required-information-from-user)
6. [SDK and Tools](#sdk-and-tools)
7. [Agent Anatomy](#agent-anatomy)
8. [Creating Agents: Step-by-Step](#creating-agents-step-by-step)
9. [Agent Examples](#agent-examples)
10. [Code Structure](#code-structure)
11. [Running and Testing](#running-and-testing)
12. [Troubleshooting](#troubleshooting)

---

## Overview

This framework enables you to create, deploy, and orchestrate multiple AI agents in **Azure AI Foundry** (formerly Azure AI Studio). Agents are created programmatically using the Azure AI Agents SDK and deployed to your Azure AI project endpoint.

**Key Capabilities:**
- Create agents with custom instructions and tools
- Define function tools for database access, document search, API calls
- Enable agent-to-agent communication (handoffs)
- Execute tools locally while agents run in Azure cloud
- Multi-agent orchestration with supervisor pattern

**Architecture:**
```
User Query
    ↓
Supervisor Agent (Azure) ← Local Tools (Python Functions)
    ↓                      ↑
Specialized Agents         ↓
    ↓                      ↑
Tool Execution ────────────┘
    ↓
Final Response
```

### Architecture Deep Dive: Where Does Everything Run?

**Critical Understanding:** This is a **hybrid architecture** where:
- 🌩️ **Agents run in Azure Cloud** (AI reasoning, decision-making)
- 💻 **Tools run on YOUR local machine** (data access, processing)

#### Detailed Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    AZURE CLOUD                          │
│                                                         │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Supervisor Agent (GPT-4o)                       │  │
│  │ - Receives user query                           │  │
│  │ - Decides which tools/agents to call            │  │
│  │ - Coordinates workflow                          │  │
│  └────────────┬────────────────────────▲────────────┘  │
│               │                        │               │
│  ┌────────────▼────────────────────────┴────────────┐  │
│  │ Specialized Agents                              │  │
│  │ - SQL Agent (GPT-4o)                            │  │
│  │ - RAG Agent (GPT-4o)                            │  │
│  │ - Response Generator (GPT-4o)                   │  │
│  └────────────┬────────────────────────▲────────────┘  │
│               │                        │               │
└───────────────┼────────────────────────┼───────────────┘
                │ Tool Call Request      │ Tool Result
                │ (JSON)                 │ (JSON)
┌───────────────▼────────────────────────┴───────────────┐
│               YOUR LOCAL MACHINE                        │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Python Script (running on your laptop/server)   │  │
│  │                                                  │  │
│  │  ┌────────────────────────────────────────────┐ │  │
│  │  │ LOCAL TOOLS (Python Functions)             │ │  │
│  │  │                                            │ │  │
│  │  │ 1. execute_sql_query()                     │ │  │
│  │  │    → Connects to YOUR local/network DB     │ │  │
│  │  │                                            │ │  │
│  │  │ 2. get_database_schema()                   │ │  │
│  │  │    → Reads YOUR database structure         │ │  │
│  │  │                                            │ │  │
│  │  │ 3. consult_rag()                           │ │  │
│  │  │    → Searches YOUR documents/vector store  │ │  │
│  │  │                                            │ │  │
│  │  │ 4. invoke_agent()                          │ │  │
│  │  │    → Triggers another Azure agent          │ │  │
│  │  │                                            │ │  │
│  │  │ 5. list_available_agents()                 │ │  │
│  │  │    → Returns YOUR agent configuration      │ │  │
│  │  │                                            │ │  │
│  │  │ 6. validate_data_source()                  │ │  │
│  │  │    → Checks YOUR local resources           │ │  │
│  │  │                                            │ │  │
│  │  │ 7. extract_citations()                     │ │  │
│  │  │    → Processes data locally                │ │  │
│  │  └────────────────────────────────────────────┘ │  │
│  │          │                                       │  │
│  │          ▼                                       │  │
│  │  ┌────────────────────────────────────────────┐ │  │
│  │  │ YOUR LOCAL DATA SOURCES                    │ │  │
│  │  │ - SQLite database (test.db)                │ │  │
│  │  │ - PostgreSQL/MySQL on network              │ │  │
│  │  │ - Local files and documents                │ │  │
│  │  │ - Azure Search (via API)                   │ │  │
│  │  └────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### The 7 Local Tools

All tools run **locally on your machine**, giving you full control over data access:

#### 1. **execute_sql_query** 🗄️
- **Runs**: Locally on your machine
- **What it does**: Executes SQL queries on your database
- **Accesses**: Your local SQLite, or network databases (PostgreSQL, MySQL, Azure SQL)
- **Returns**: Query results as JSON

#### 2. **get_database_schema** 📊
- **Runs**: Locally
- **What it does**: Retrieves table structures, columns, types
- **Accesses**: Your database metadata
- **Returns**: Schema description string

#### 3. **consult_rag** 🔍
- **Runs**: Locally (but may call Azure Search API)
- **What it does**: Searches documents using semantic search
- **Accesses**: Azure AI Search or local vector store
- **Returns**: Relevant documents with scores

#### 4. **invoke_agent** 🤝
- **Runs**: Locally (orchestration logic)
- **What it does**: Triggers another Azure agent (agent-to-agent handoff)
- **Calls**: Azure API to start another agent
- **Returns**: Response from invoked agent

#### 5. **list_available_agents** 📋
- **Runs**: Locally
- **What it does**: Lists all agents in your configuration
- **Accesses**: Your local `azure_agents_config.json` file
- **Returns**: JSON list of agents with descriptions

#### 6. **validate_data_source** ✅
- **Runs**: Locally
- **What it does**: Checks if a data source is available
- **Accesses**: Local database connections, API endpoints
- **Returns**: Availability status

#### 7. **extract_citations** 📝
- **Runs**: Locally
- **What it does**: Extracts source citations from workflow outputs
- **Processes**: Local data structures
- **Returns**: Formatted citations

### Complete Execution Flow Example

Let's trace a real query through the entire system:

```
👤 USER: "Show me top 5 products by price"

┌─ STEP 1: Query Submission ──────────────────────────────┐
│ [LOCAL] Your Python script sends query to Azure         │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 2: Supervisor Receives Query ─────────────────────┐
│ [AZURE] Supervisor Agent (GPT-4o) receives query        │
│ → Analyzes: "This requires database access"             │
│ → Decision: "I need to call the SQL agent"              │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 3: Agent Handoff Tool Call ───────────────────────┐
│ [AZURE] Supervisor calls: invoke_agent()                │
│ → agent_name: "sql_agent"                               │
│ → message: "Get top 5 products by price"                │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 4: Local Tool Execution ──────────────────────────┐
│ [LOCAL] Your function invoke_agent() executes           │
│ → Looks up SQL agent ID in config                       │
│ → Calls Azure API to start SQL agent                    │
│ → Returns: "SQL agent started in thread_xyz"            │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 5: SQL Agent Starts ──────────────────────────────┐
│ [AZURE] SQL Agent (GPT-4o) starts in new thread         │
│ → Receives: "Get top 5 products by price"               │
│ → Thinks: "I need to know the schema first"             │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 6: Schema Tool Call ──────────────────────────────┐
│ [AZURE] SQL Agent calls: get_database_schema()          │
│ → database: "local_products"                            │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 7: Local Schema Retrieval ────────────────────────┐
│ [LOCAL] Your function get_database_schema() executes    │
│ → Opens connection to YOUR database                     │
│ → Queries: PRAGMA table_info(products)                  │
│ → Returns: "Table: products                             │
│             product_id INTEGER PRIMARY KEY              │
│             name TEXT NOT NULL                          │
│             category TEXT                               │
│             price REAL                                  │
│             stock_quantity INTEGER"                     │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 8: SQL Agent Constructs Query ────────────────────┐
│ [AZURE] SQL Agent receives schema                       │
│ → Analyzes columns: price exists ✓                      │
│ → Constructs query:                                     │
│   "SELECT name, category, price, stock_quantity         │
│    FROM products                                        │
│    ORDER BY price DESC                                  │
│    LIMIT 5"                                             │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 9: SQL Execution Tool Call ───────────────────────┐
│ [AZURE] SQL Agent calls: execute_sql_query()            │
│ → query: "SELECT name, category, price..."             │
│ → database: "local_products"                            │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 10: Local Query Execution ────────────────────────┐
│ [LOCAL] Your function execute_sql_query() executes      │
│ → Opens connection to YOUR database                     │
│ → Executes: SELECT name, category, price...            │
│ → Fetches results from YOUR data                       │
│ → Returns JSON:                                         │
│   [                                                     │
│     {"name": "Laptop Pro 15", "category": "Electronics",│
│      "price": 1299.99, "stock_quantity": 45},          │
│     {"name": "Standing Desk", "category": "Furniture",  │
│      "price": 599.99, "stock_quantity": 20},           │
│     {"name": "Monitor 27inch 4K", "category":           │
│      "Electronics", "price": 449.99, "stock": 60},     │
│     {"name": "Office Chair Deluxe", "category":         │
│      "Furniture", "price": 399.99, "stock": 30},       │
│     {"name": "Keyboard Mechanical", "category":         │
│      "Electronics", "price": 129.99, "stock": 80}      │
│   ]                                                     │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 11: SQL Agent Formats Results ────────────────────┐
│ [AZURE] SQL Agent receives query results                │
│ → Analyzes data                                         │
│ → Formats as readable table                             │
│ → Returns formatted response                            │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 12: Supervisor Receives Results ──────────────────┐
│ [AZURE] Supervisor Agent receives SQL agent response    │
│ → Reviews formatted results                             │
│ → Decides: "This is complete, return to user"           │
└──────────────────────────────────────────────────────────┘
                        ↓
┌─ STEP 13: Final Response ───────────────────────────────┐
│ [LOCAL] Your Python script receives final response:     │
│                                                         │
│ "Here are the top 5 products by price:                  │
│                                                         │
│  ┌──────────────────────┬─────────────┬──────────┬─────┐│
│  │ Product              │ Category    │ Price    │Stock││
│  ├──────────────────────┼─────────────┼──────────┼─────┤│
│  │ Laptop Pro 15        │ Electronics │ $1,299.99│  45 ││
│  │ Standing Desk        │ Furniture   │ $599.99  │  20 ││
│  │ Monitor 27inch 4K    │ Electronics │ $449.99  │  60 ││
│  │ Office Chair Deluxe  │ Furniture   │ $399.99  │  30 ││
│  │ Keyboard Mechanical  │ Electronics │ $129.99  │  80 ││
│  └──────────────────────┴─────────────┴──────────┴─────┘│
│                                                         │
│  The highest-priced item is the Laptop Pro at          │
│  $1,299.99, followed by furniture items."               │
└──────────────────────────────────────────────────────────┘
                        ↓
                  👤 USER SEES RESULT
```

### Why This Hybrid Architecture?

#### ✅ **Advantages**

1. **Data Security & Privacy**
   - Your data **never leaves your infrastructure**
   - Database stays on your network/laptop
   - Sensitive data isn't sent to Azure for processing
   - Only query results (which you control) go to agents

2. **Flexibility**
   - Access **ANY** data source from your machine
   - Local SQLite files
   - Network databases behind firewalls
   - On-premises file systems
   - Legacy systems without cloud connectivity
   - Private APIs

3. **Cost Efficiency**
   - Only AI reasoning happens in cloud (pay per token)
   - Data processing is free (runs locally)
   - No data transfer costs for large datasets

4. **Low Latency for Data Operations**
   - Direct access to local/network resources
   - No need to copy data to cloud
   - Fast database queries on local network

5. **Compliance & Governance**
   - Maintain data residency requirements
   - Keep sensitive data in compliance zones
   - Full audit trail on your infrastructure

#### ⚠️ **Important Considerations**

1. **Your Python Script Must Keep Running**
   - Tools execute when Azure agents request them
   - If your script stops, tools can't execute
   - Agents will receive "function not found" errors
   - **Solution**: Deploy script as a service/daemon for production

2. **Network Connectivity Required**
   - Your machine must reach Azure APIs (HTTPS)
   - Agents send tool call requests back to your script
   - Results flow back to Azure
   - **Requirement**: Stable internet connection

3. **Authentication Happens Locally**
   - Your script authenticates to Azure (via Azure CLI/Service Principal)
   - Your tools authenticate to databases/APIs (using your credentials)
   - **Security**: Credentials stay on your machine

4. **Scalability Considerations**
   - Single Python process handles all tool calls
   - For high load, consider:
     - Multiple worker processes
     - Load balancing
     - Caching frequently accessed data

### Component Location Summary

| Component | Location | Purpose |
|-----------|----------|---------|
| **Agents** (Supervisor, SQL, RAG, etc.) | ☁️ **Azure Cloud** | AI reasoning, decision making, language understanding |
| **AI Models** (GPT-4o) | ☁️ **Azure Cloud** | Natural language processing |
| **Tools** (7 Python functions) | 💻 **Your Local Machine** | Data access, processing, orchestration |
| **Databases** | 💻 **Your Infrastructure** | Data storage (SQLite, PostgreSQL, etc.) |
| **Documents/Files** | 💻 **Your Infrastructure** | Document storage, vector stores |
| **Orchestration Script** | 💻 **Your Local Machine** | Coordinates everything, handles tool calls |
| **Configuration** (`azure_agents_config.json`) | 💻 **Your Local Machine** | Agent IDs and settings |

### The Critical SDK Method

This is what enables tools to run locally while agents run in Azure:

```python
from azure.ai.agents.aio import AgentsClient
from azure.ai.agents.models import AsyncFunctionTool

# 1. Define your LOCAL tool functions
async def execute_sql_query(query: str, database: str = "default") -> str:
    """This runs on YOUR machine"""
    results = my_local_db.execute(query)
    return json.dumps(results)

# 2. Create function tool from local functions
function_tool = AsyncFunctionTool({
    execute_sql_query,
    get_database_schema,
    consult_rag,
    invoke_agent,
    list_available_agents,
    validate_data_source,
    extract_citations
})

# 3. Register with Azure client
# This tells Azure: "When agents call these functions,
# send the request back to MY running Python process"
agents_client.enable_auto_function_calls(function_tool, max_retry=10)

# 4. Run agent in Azure
result = await agents_client.create_thread_and_process_run(
    agent_id="asst_sql_agent_id",
    thread={"messages": [{"role": "user", "content": "Get top products"}]}
)

# FLOW:
# Azure agent runs → decides to call execute_sql_query →
# request comes back to YOUR Python process →
# your local function executes on YOUR database →
# result goes back to Azure agent →
# agent continues reasoning
```

**Key Insight:** The `enable_auto_function_calls()` method creates a bridge between Azure agents and your local tools, enabling this powerful hybrid architecture where AI reasoning happens in the cloud but data stays secure on your infrastructure.

---

## Deployment Patterns: Local vs Cloud Tools

### Critical Decision: Where Should Your Tools Run?

The architecture shown above uses **local tools**, but this is **not the only option**. The right deployment pattern depends entirely on **where your data lives**.

### Decision Framework

```
┌─ DECISION TREE: Tool Deployment Pattern ────────────────────────────┐
│                                                                      │
│  Where is your data?                                                │
│           │                                                          │
│           ├── Local files (.db, .csv, .pdf on your laptop)          │
│           │   → Use LOCAL TOOLS (Pattern A)                         │
│           │                                                          │
│           ├── On-premises database (behind firewall)                │
│           │   → Use LOCAL TOOLS (Pattern A)                         │
│           │                                                          │
│           ├── Internal APIs (corporate network, not public)         │
│           │   → Use LOCAL TOOLS (Pattern A)                         │
│           │                                                          │
│           ├── Azure SQL, Azure AI Search, Azure services            │
│           │   → Use CLOUD TOOLS (Pattern B) ⚡ RECOMMENDED          │
│           │                                                          │
│           ├── AWS RDS, AWS services (internet-accessible)           │
│           │   → Use CLOUD TOOLS (Pattern B)                         │
│           │                                                          │
│           ├── MCP Server (public URL)                               │
│           │   → Use CLOUD TOOLS (Pattern B)                         │
│           │                                                          │
│           └── Mix of local AND cloud data sources                   │
│               → Use HYBRID (Pattern C)                              │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Pattern A: Local Tools

**Use When:**
- ✅ Data is on your laptop/workstation (.db, .csv, .pdf files)
- ✅ Database is behind corporate firewall
- ✅ APIs are on internal network (not internet-accessible)
- ✅ Quick prototyping and development
- ✅ Need to debug tool implementations locally

**Architecture:**

```
┌─────────────────────────────────────────────────────────┐
│                    AZURE CLOUD                          │
│                                                         │
│  ┌───────────────────────────────────────────────────┐ │
│  │ Agents (GPT-4o)                                   │ │
│  └──────────────┬────────────────────▲────────────────┘ │
│                 │ Tool Call          │ Tool Result      │
└─────────────────┼────────────────────┼──────────────────┘
                  │                    │
┌─────────────────▼────────────────────┴──────────────────┐
│            YOUR LOCAL MACHINE                           │
│                                                         │
│  Python Script (orchestrator.py)                       │
│    ├── Local Tool Functions                            │
│    │   ├── execute_sql_query()                         │
│    │   ├── get_database_schema()                       │
│    │   └── consult_rag()                               │
│    │                                                    │
│    └── Local Data Sources                              │
│        ├── test.db (SQLite)                            │
│        ├── documents.csv                               │
│        └── reports/*.pdf                               │
└─────────────────────────────────────────────────────────┘
```

**Pseudo Code:**

```
class LocalTools:
    initialize with local data paths (db_path, csv_directory, pdf_directory)

    function execute_sql_query(query):
        connect to local SQLite database
        execute query on local machine
        return results as JSON

    function read_local_csv(filename):
        read CSV file from local filesystem
        return data as JSON

    function search_local_pdfs(query):
        search local PDF files using vector store
        return relevant documents

main workflow:
    1. Initialize AgentsClient with Azure credentials
    2. Create LocalTools instance
    3. Register local tool functions with AsyncFunctionTool
    4. Enable auto function calls: client.enable_auto_function_calls(tools)
    5. Run agent: tools execute on YOUR machine when called
```

**Advantages:**
- ✅ Access ANY data on your machine/network
- ✅ Data never leaves your infrastructure
- ✅ Easy debugging (logs on your machine)
- ✅ No Azure Function deployment needed
- ✅ Works behind firewalls

**Limitations:**
- ⚠️ Your Python script must keep running
- ⚠️ Single point of failure (your machine)
- ⚠️ Higher latency for cloud data sources
- ⚠️ Manual scaling required

---

### Pattern B: Cloud Tools - Recommended

**Use When:**
- ✅ Data is in Azure (Azure SQL, Azure AI Search, Cosmos DB)
- ✅ Data is in AWS but internet-accessible (RDS, S3)
- ✅ MCP servers are publicly accessible
- ✅ Production deployment required
- ✅ Need auto-scaling and high availability
- ✅ Lower latency is critical

**Architecture:**

```
┌──────────────────────────────────────────────────────────────────────┐
│                         AZURE CLOUD                                  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ Agents (GPT-4o)                                                │ │
│  └────────────┬───────────────────────▲───────────────────────────┘ │
│               │ Tool Call             │ Tool Result                 │
│               │ (via Azure Queues)    │                             │
│  ┌────────────▼───────────────────────┴───────────────────────────┐ │
│  │ AZURE FUNCTIONS (Serverless Tools)                            │ │
│  │                                                                │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐  │ │
│  │  │ consult_rag  │  │ execute_sql  │  │ call_mcp_server    │  │ │
│  │  │ Function     │  │ Function     │  │ Function           │  │ │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬─────────────┘  │ │
│  │         │                 │                  │                │ │
│  └─────────┼─────────────────┼──────────────────┼────────────────┘ │
│            │                 │                  │                  │
│  ┌─────────▼─────┐  ┌────────▼──────┐  ┌────────▼──────────────┐  │
│  │ Azure AI      │  │ Azure SQL     │  │ MCP Server API        │  │
│  │ Search        │  │ Database      │  │ (public URL)          │  │
│  │ (Vector Store)│  │               │  │                       │  │
│  └───────────────┘  └───────────────┘  └───────────────────────┘  │
│                                                                      │
│  ⚡ All communication within Azure - LOW LATENCY                    │
│  🔒 Managed Identity - NO CONNECTION STRINGS                        │
│  📊 Auto-scaling - HIGH AVAILABILITY                                │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
           ↑                                    ↓
      User Query                          Final Response
```

**Pseudo Code: Azure Function Tools**

```
// AZURE FUNCTION 1: consult_rag
function consult_rag_handler(request):
    query = extract query from request
    top_k = extract top_k from request (default 5)
    filters = extract filters from request

    // Use Managed Identity - NO API KEYS!
    credential = get_managed_identity_credential()
    search_client = create_search_client(AZURE_SEARCH_ENDPOINT, credential)

    // Execute semantic search on Azure AI Search
    results = search_client.semantic_search(query, top_k, filters)

    // Format and return documents
    return {documents, scores, metadata}

// AZURE FUNCTION 2: execute_sql
function execute_sql_handler(request):
    query = extract SQL query from request
    database = extract database name from request

    // Get connection string from Key Vault using Managed Identity
    credential = get_managed_identity_credential()
    secret_client = create_keyvault_client(KEY_VAULT_URL, credential)
    connection_string = secret_client.get_secret(database_connection_string)

    // Connect to Azure SQL via private endpoint
    connection = connect_to_azure_sql(connection_string)
    results = execute_query(connection, query)

    return results_as_json

// AZURE FUNCTION 3: call_mcp_server
function call_mcp_server_handler(request):
    action = extract action from request
    params = extract parameters from request

    // Call external MCP server API
    mcp_url = get_env(MCP_SERVER_URL)
    api_key = get_env(MCP_API_KEY)

    response = http_post(
        url: mcp_url + "/api/execute",
        json: {action, parameters: params},
        headers: {Authorization: "Bearer " + api_key}
    )

    return response

// AGENT CREATION: Register Azure Function tools
function create_agent_with_cloud_tools():
    client = create_agents_client(AZURE_AI_PROJECT_ENDPOINT)

    tools = [
        {
            type: "function",
            name: "consult_rag",
            description: "Search documents using Azure AI Search",
            parameters: {query, top_k, filters}
        },
        {
            type: "function",
            name: "execute_sql_query",
            description: "Execute SQL on Azure SQL Database",
            parameters: {query, database}
        },
        {
            type: "function",
            name: "call_mcp_server",
            description: "Call MCP server API",
            parameters: {action, params}
        }
    ]

    // Create agent with cloud tools
    agent = client.create_agent(
        model: "gpt-4o",
        name: "cloud_tools_agent",
        instructions: "You have access to cloud-based Azure tools...",
        tools: tools
    )

    save_config(agent.id, tools)
    return agent
```

**Deployment (Simplified):**

```
DEPLOYMENT STEPS:
1. Deploy Azure Functions:
   - Create Function App in Azure Portal or via CLI
   - Deploy 3 functions: consult_rag, execute_sql, call_mcp_server
   - Enable Managed Identity on Function App

2. Configure Environment:
   - Set AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_INDEX
   - Set KEY_VAULT_URL for secure connection strings
   - Set MCP_SERVER_URL if using MCP

3. Grant Permissions:
   - Function App Managed Identity → Azure AI Search Reader
   - Function App Managed Identity → Key Vault Secrets User
   - Function App Managed Identity → Azure SQL Database Contributor

4. Create Agent:
   - Define tools pointing to Azure Function URLs
   - Agent calls functions automatically via Azure infrastructure
```

**Advantages:**
- ✅ **No local script running** - fully serverless
- ✅ **Lower latency** - Azure-to-Azure communication (< 50ms)
- ✅ **Managed Identity** - no connection strings, secure by default
- ✅ **Private endpoints** - databases not exposed to internet
- ✅ **Auto-scaling** - handles any load automatically
- ✅ **High availability** - built-in retry, failover
- ✅ **Monitoring** - Application Insights, logs, metrics
- ✅ **Cost-effective** - pay per execution, scale to zero

**Limitations:**
- ⚠️ Requires Azure Functions deployment
- ⚠️ Cannot access local files or on-premises data
- ⚠️ More complex initial setup

---

### Pattern C: Hybrid

**Use When:**
- ✅ Some data is local/on-premises
- ✅ Some data is in Azure/cloud
- ✅ Migrating incrementally from on-prem to cloud
- ✅ Multi-cloud setup (Azure + AWS + on-prem)

**Architecture:**

```
┌────────────────────────────────────────────────────────────────┐
│                      AZURE CLOUD                               │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Agents (GPT-4o)                                          │ │
│  └───────────┬──────────────────────────▲───────────────────┘ │
│              │                           │                     │
│    ┌─────────▼────────┐    ┌────────────┴────────┐           │
│    │ CLOUD TOOLS      │    │ CLOUD DATA          │           │
│    │ (Azure Functions)│───→│ - Azure AI Search   │           │
│    │                  │    │ - Azure SQL         │           │
│    └──────────────────┘    └─────────────────────┘           │
│                                                                │
└────────────────────┬───────────────────────▲───────────────────┘
                     │                       │
                     │ Local Tool Calls      │ Local Results
                     │                       │
┌────────────────────▼───────────────────────┴───────────────────┐
│                   YOUR LOCAL MACHINE                           │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Python Script (hybrid orchestrator)                      │ │
│  │                                                           │ │
│  │  LOCAL TOOLS                                             │ │
│  │  ├── access_onprem_database()  → Corporate SQL Server   │ │
│  │  ├── read_local_files()        → .csv, .pdf files       │ │
│  │  └── call_internal_api()       → Internal REST API      │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  LOCAL DATA SOURCES                                           │
│  ├── On-premises SQL Server                                  │
│  ├── Local file system                                        │
│  └── Internal APIs (not internet-accessible)                 │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Pseudo Code:**

```
class HybridTools:
    // LOCAL TOOLS (run on your machine)

    function access_onprem_database(query):
        connect to on-premises SQL Server (behind firewall)
        execute query
        return results

    function read_local_files(filename):
        read file from local filesystem
        return content

    function call_internal_api(endpoint):
        call corporate API (internal network only)
        return response

function create_hybrid_agent():
    client = create_agents_client(AZURE_AI_PROJECT_ENDPOINT)

    // Register LOCAL tools
    local_tools = create_function_tool({
        access_onprem_database,
        read_local_files,
        call_internal_api
    })
    client.enable_auto_function_calls(local_tools)

    // Define CLOUD tools (Azure Functions)
    cloud_tools = [
        {name: "consult_rag", type: "cloud"},
        {name: "execute_azure_sql", type: "cloud"}
    ]

    // Create agent with BOTH tool types
    agent = client.create_agent(
        model: "gpt-4o",
        name: "hybrid_agent",
        instructions: "You have access to BOTH local and cloud tools...",
        tools: cloud_tools
    )

    // Agent automatically uses:
    // - Local tools for on-prem data
    // - Cloud tools for Azure data

WORKFLOW EXAMPLE:
1. User asks: "Compare on-prem sales with Azure AI Search feedback"
2. Agent calls access_onprem_database() → executes on YOUR machine
3. Agent calls consult_rag() → executes in Azure Function
4. Agent combines results and responds
```

**Advantages:**
- ✅ Access data from anywhere (local + cloud)
- ✅ Incremental migration path (move tools to cloud over time)
- ✅ Optimal performance for each data source
- ✅ Security for on-prem data, scalability for cloud data

---

### Comparison and Recommendations

| Aspect | Local Tools | Cloud Tools | Hybrid |
|--------|-------------|-------------|--------|
| **Setup Complexity** | ⭐⭐ Easy | ⭐⭐⭐⭐ Moderate | ⭐⭐⭐⭐⭐ Complex |
| **Local Data Access** | ✅ Yes | ❌ No | ✅ Yes |
| **Cloud Data Access** | ✅ Yes (slower) | ✅ Yes (faster) | ✅ Yes (optimal) |
| **Latency (Cloud Data)** | ~500ms | ~50ms | ~50ms (cloud), ~500ms (local) |
| **Requires Local Script** | ✅ Yes | ❌ No | ✅ Yes |
| **Auto-Scaling** | ❌ Manual | ✅ Automatic | ⚙️ Cloud tools only |
| **High Availability** | ❌ Single machine | ✅ Built-in | ⚙️ Cloud tools only |
| **Cost (Azure Functions)** | $0 | ~$20-100/month | ~$10-50/month |
| **Security (Cloud Data)** | Good | Excellent (Managed Identity) | Excellent |
| **Best For** | Development, local data | Production, cloud data | Mixed environments |

### Cost Analysis

**Local Tools:**
- Azure AI Agents API: ~$0.03 per 1K tokens
- No Azure Functions cost
- **Total: ~$50-200/month** (API calls only)

**Cloud Tools:**
- Azure AI Agents API: ~$0.03 per 1K tokens
- Azure Functions: ~$20-100/month (depends on executions)
- **Total: ~$70-300/month**

**Trade-off:** Cloud tools cost more but provide:
- 10x lower latency for cloud data
- Auto-scaling and high availability
- Better security (Managed Identity, private endpoints)
- No local script maintenance

### Performance Comparison

**Scenario: Query Azure SQL Database**

```
LOCAL TOOLS:
User → Azure Agent → Your Laptop → Azure SQL → Laptop → Agent
Time: ~800ms
  - Agent to Laptop: 100ms
  - Laptop to Azure SQL: 300ms (internet)
  - SQL query: 200ms
  - Return path: 200ms

CLOUD TOOLS:
User → Azure Agent → Azure Function → Azure SQL → Function → Agent
Time: ~120ms
  - Agent to Function: 10ms (Azure internal)
  - Function to SQL: 5ms (VNet/private endpoint)
  - SQL query: 100ms
  - Return path: 5ms

RESULT: Cloud tools are 6-7x FASTER for cloud data sources
```

### Recommendation Summary

**Choose LOCAL TOOLS if:**
- Data is on your laptop (.db, .csv, .pdf files)
- Database is on-premises / behind firewall
- Quick prototyping / development phase
- Budget-conscious (no Azure Functions cost)

**Choose CLOUD TOOLS if:**
- Data is in Azure (Azure SQL, Azure AI Search, Cosmos DB)
- Data is in AWS but internet-accessible
- MCP servers are public
- Production deployment
- Performance is critical

**Choose HYBRID if:**
- Some data is local/on-prem, some in cloud
- Migrating to cloud incrementally
- Need both security (on-prem) and performance (cloud)

---

**What This Guide Uses:**

This guide demonstrates **Pattern A (Local Tools)** for maximum flexibility and ease of getting started. However, for production deployments with cloud data sources, we strongly recommend **Pattern B (Cloud Tools)** for better performance, security, and scalability.

**Migration Path:**

```
Start: Local Tools (development)
    ↓
  Deploy tools to Azure Functions (one at a time)
    ↓
  Run hybrid (some local, some cloud)
    ↓
  Migrate all cloud data access to cloud tools
    ↓
End: Full cloud deployment (production)
```

---

## Intelligent Workflow Orchestration with Human-in-the-Loop

This section describes an advanced workflow pattern that combines intelligent data source analysis, dynamic tool selection, planner-based workflow design, and human approval gates before execution.

### System Architecture

The system uses a multi-layer architecture that preprocesses user inputs, intelligently selects tools, generates execution plans, and requires human approval before execution:

```
┌────────────────────────────────────────────────────────────────────┐
│                       USER INTERFACE LAYER                         │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ Workflow Builder UI                                          │ │
│  │ - Workflow Name & Description                                │ │
│  │ - User Intent (Prompt)                                       │ │
│  │ - Data Sources (Files, Databases, MCP)                       │ │
│  │ - Agent Selection                                            │ │
│  └────────────────────┬─────────────────────────────────────────┘ │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│               PREPROCESSING & ORCHESTRATION LAYER                  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 1. DATA SOURCE ANALYZER                                      │ │
│  │    - Detects file types (.pdf, .db, .csv)                    │ │
│  │    - Detects connection strings (Azure SQL, AWS RDS)         │ │
│  │    - Detects MCP server URLs                                 │ │
│  │    ↓                                                          │ │
│  │ 2. INGESTION PIPELINE (for files)                            │ │
│  │    - .pdf → Azure AI Search (vector embeddings)              │ │
│  │    - .csv → Azure SQL or local storage                       │ │
│  │    - .db → Keep local or migrate                             │ │
│  │    ↓                                                          │ │
│  │ 3. TOOL REGISTRY & SELECTOR                                  │ │
│  │    - Maps data sources to appropriate tools                  │ │
│  │    - Decides: Local tools vs Cloud tools                     │ │
│  │    - Generates tool manifest                                 │ │
│  │    ↓                                                          │ │
│  │ 4. ENHANCED PLANNER AGENT                                    │ │
│  │    - Receives: User intent + Tool manifest + Data sources    │ │
│  │    - Generates: Detailed step-by-step execution plan (JSON)  │ │
│  │    ↓                                                          │ │
│  │ 5. ⚠️ HUMAN APPROVAL GATE ⚠️                                  │ │
│  │    - Display plan to user via UI                             │ │
│  │    - User approves, modifies, or rejects                     │ │
│  │    - Loop back to planner if modifications requested         │ │
│  │    ↓                                                          │ │
│  │ 6. SUPERVISOR AGENT (Workflow Executor)                      │ │
│  │    - Loads approved plan                                     │ │
│  │    - Executes agents in specified order                      │ │
│  │    - Manages handoffs and data flow                          │ │
│  │    - Handles errors and retries                              │ │
│  │    - Returns final results                                   │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────────┐
│                    AGENT & TOOL EXECUTION LAYER                    │
│                                                                    │
│  AZURE FOUNDRY AGENTS:                TOOLS:                      │
│  - RAG Agent                          - Local: SQLite, local PDFs │
│  - SQL Agent                          - Cloud: Azure AI Search    │
│  - Response Generator                        Azure SQL            │
│  - Planner Agent                             MCP Server APIs      │
│  - Supervisor Agent                                               │
└────────────────────────────────────────────────────────────────────┘
```

### Data Source Intelligence

The system automatically analyzes data sources and selects the appropriate tool deployment pattern:

**Decision Matrix:**

```
┌─────────────────────────────────────────────────────────────────┐
│ DATA SOURCE TYPE         → TOOL SELECTION                       │
├─────────────────────────────────────────────────────────────────┤
│ .pdf file provided       → Ingest to Azure AI Search            │
│                          → Use Cloud RAG tool                    │
│                                                                  │
│ .db or .duckdb file      → Keep local                           │
│                          → Use Local SQL tool                    │
│                                                                  │
│ Azure SQL connection     → Use Cloud SQL tool                   │
│   string                 → Azure Function with Managed Identity │
│                                                                  │
│ AWS RDS connection       → Use Cloud SQL tool                   │
│   string                 → Azure Function with connection string│
│                                                                  │
│ MCP server URL           → Use Cloud MCP tool                   │
│                          → Azure Function HTTP call             │
│                                                                  │
│ Local .csv file          → Local file tool                      │
│                          → Optional: Ingest to Azure SQL        │
└─────────────────────────────────────────────────────────────────┘
```

**Pseudo Code: Data Source Analyzer**

```
function analyze_data_sources(workflow_inputs):
    data_sources = workflow_inputs.data_sources
    tool_manifest = {}

    for source in data_sources:
        if source.type == "file":
            file_extension = get_file_extension(source.path)

            if file_extension == ".pdf":
                // Ingest PDF to Azure AI Search
                index_name = ingest_to_azure_search(source.path)
                tool_manifest.add({
                    tool: "consult_rag",
                    type: "cloud",
                    target: index_name,
                    description: "Search documents in Azure AI Search"
                })

            else if file_extension in [".db", ".duckdb"]:
                // Keep local database
                tool_manifest.add({
                    tool: "execute_sql_query",
                    type: "local",
                    target: source.path,
                    description: "Query local database"
                })

            else if file_extension == ".csv":
                // Local file access
                tool_manifest.add({
                    tool: "read_csv_file",
                    type: "local",
                    target: source.path,
                    description: "Read local CSV file"
                })

        else if source.type == "connection_string":
            if source.provider == "azure_sql":
                // Use cloud SQL tool
                tool_manifest.add({
                    tool: "execute_azure_sql",
                    type: "cloud",
                    target: source.connection_string,
                    description: "Query Azure SQL Database"
                })

            else if source.provider == "aws_rds":
                // Use cloud SQL tool
                tool_manifest.add({
                    tool: "execute_cloud_sql",
                    type: "cloud",
                    target: source.connection_string,
                    description: "Query AWS RDS Database"
                })

        else if source.type == "mcp_server":
            // Use cloud MCP tool
            tool_manifest.add({
                tool: "call_mcp_server",
                type: "cloud",
                target: source.url,
                description: "Call MCP server API"
            })

    return tool_manifest
```

### Workflow Execution Flow

**Complete End-to-End Flow:**

```
PHASE 1: USER INPUT (via UI)
├─ Workflow Name: "PI10 Assistant"
├─ Description: "Assistant for PI10 system specifications"
├─ User Intent: "Answer technical questions about PI10"
├─ Data Sources:
│  └─ File: eDrivePredM.pdf
└─ Agents: RAG Agent, Response Generator

                    ↓

PHASE 2: DATA SOURCE PREPROCESSING
├─ Analyzer detects: .pdf file
├─ Decision: Ingest to Azure AI Search
├─ Ingestion Pipeline:
│  ├─ Extract text from eDrivePredM.pdf
│  ├─ Generate embeddings (text-embedding-3)
│  ├─ Create index: "pi10-documents"
│  └─ Upload to Azure AI Search
└─ Tool Selected: Cloud RAG tool (consult_rag)

                    ↓

PHASE 3: TOOL MANIFEST GENERATION
└─ Tool Manifest:
   {
     "consult_rag": {
       "type": "cloud",
       "target": "pi10-documents",
       "description": "Search PI10 documentation",
       "parameters": ["query", "top_k"]
     }
   }

                    ↓

PHASE 4: PLANNER AGENT
├─ Inputs:
│  ├─ Workflow name & description
│  ├─ User intent
│  ├─ Available tools: {consult_rag}
│  └─ Available agents: {rag_agent, response_generator}
├─ Generates Plan (JSON):
   {
     "workflow": "PI10 Assistant",
     "steps": [
       {
         "step": 1,
         "action": "receive_user_question",
         "description": "Accept technical question from user"
       },
       {
         "step": 2,
         "agent": "rag_agent",
         "tool": "consult_rag",
         "action": "search_documents",
         "parameters": {
           "query": "$user_question",
           "top_k": 5
         },
         "description": "Search PI10 docs for relevant information"
       },
       {
         "step": 3,
         "agent": "response_generator",
         "action": "generate_response",
         "inputs": ["search_results", "user_question"],
         "description": "Generate technical, concise answer"
       }
     ],
     "expected_output": "Technical answer with citations"
   }
└─ Return plan to UI

                    ↓

PHASE 5: HUMAN APPROVAL GATE ⚠️
├─ Display plan in UI (formatted, readable)
├─ User reviews:
│  ├─ Check if steps make sense
│  ├─ Verify tools are appropriate
│  └─ Ensure agents are correctly assigned
├─ User Actions:
│  ├─ ✅ APPROVE → Continue to execution
│  ├─ ✏️ MODIFY → Loop back to planner with changes
│  └─ ❌ REJECT → Cancel workflow
└─ [User clicks APPROVE]

                    ↓

PHASE 6: SUPERVISOR EXECUTION
├─ Load approved plan
├─ Initialize tools (Cloud RAG tool)
├─ Execute Step 1: Receive user question
│  └─ Input: "What is the voltage range of PI10?"
├─ Execute Step 2: RAG Agent
│  ├─ Call consult_rag(query="PI10 voltage range", top_k=5)
│  ├─ Azure Function executes
│  ├─ Returns: 5 relevant documents with voltage specs
│  └─ Output: [{doc1}, {doc2}, {doc3}, {doc4}, {doc5}]
├─ Execute Step 3: Response Generator
│  ├─ Input: search_results + user_question
│  ├─ Agent generates: "The PI10 system operates at..."
│  └─ Output: Technical answer with citations
└─ Return final output to user

                    ↓

PHASE 7: RESULT DISPLAY
└─ Show answer to user in UI with:
   ├─ Generated response
   ├─ Source citations
   └─ Execution metadata (time, steps completed)
```

### Example: PI10 Assistant Workflow

**Workflow Configuration:**

```json
{
  "workflow_name": "PI10 Assistant",
  "description": "Assistant to help understand PI10 system specifications",
  "user_intent": "Answer technical questions about PI10 system in concise manner",
  "data_sources": [
    {
      "name": "PI10 Documentation",
      "type": "file",
      "path": "./documents/eDrivePredM.pdf",
      "format": "pdf"
    }
  ],
  "agents": [
    "rag_agent",
    "response_generator"
  ]
}
```

**Generated Plan (After Preprocessing):**

```json
{
  "workflow_id": "pi10-assistant-001",
  "status": "pending_approval",
  "preprocessing": {
    "ingestion_completed": true,
    "azure_search_index": "pi10-documents",
    "document_count": 245,
    "embedding_model": "text-embedding-3-large"
  },
  "tools_selected": [
    {
      "name": "consult_rag",
      "type": "cloud",
      "deployment": "azure_function",
      "endpoint": "https://agent-tools.azurewebsites.net/api/consult_rag"
    }
  ],
  "execution_plan": {
    "steps": [
      {
        "step_id": 1,
        "agent": "supervisor",
        "action": "receive_user_input",
        "description": "Accept user's technical question"
      },
      {
        "step_id": 2,
        "agent": "rag_agent",
        "tool": "consult_rag",
        "action": "semantic_search",
        "parameters": {
          "query": "$user_input",
          "index": "pi10-documents",
          "top_k": 5,
          "semantic_config": "default"
        },
        "description": "Search PI10 documentation for relevant sections"
      },
      {
        "step_id": 3,
        "agent": "response_generator",
        "action": "generate_technical_response",
        "inputs": [
          "$search_results",
          "$user_input"
        ],
        "constraints": {
          "style": "technical",
          "tone": "concise",
          "include_citations": true
        },
        "description": "Generate expert-level technical answer"
      }
    ]
  },
  "estimated_tokens": 2500,
  "estimated_cost": "$0.08"
}
```

**Human Approval UI Display:**

```
═══════════════════════════════════════════════════════════════
                    WORKFLOW APPROVAL REQUIRED
═══════════════════════════════════════════════════════════════

Workflow: PI10 Assistant
Purpose: Answer technical questions about PI10 system specifications

───────────────────────────────────────────────────────────────
PREPROCESSING SUMMARY:
───────────────────────────────────────────────────────────────
✓ Document ingested: eDrivePredM.pdf
✓ Azure AI Search index created: pi10-documents
✓ Documents indexed: 245 pages
✓ Tool deployed: Cloud RAG (Azure Function)

───────────────────────────────────────────────────────────────
EXECUTION PLAN (3 steps):
───────────────────────────────────────────────────────────────

Step 1: Receive User Question
  - Agent: Supervisor
  - Action: Accept technical question from user

Step 2: Search PI10 Documentation
  - Agent: RAG Agent
  - Tool: consult_rag (Cloud)
  - Action: Semantic search on pi10-documents index
  - Parameters: top_k=5, semantic ranking enabled

Step 3: Generate Technical Answer
  - Agent: Response Generator
  - Action: Create expert-level response
  - Style: Technical, concise, with citations

───────────────────────────────────────────────────────────────
ESTIMATED COST: $0.08 per query
───────────────────────────────────────────────────────────────

Actions:
  [✓ Approve and Deploy]  [✏️ Modify Plan]  [❌ Cancel]
```

**After Approval - Supervisor Executes:**

```
User Query: "What is the maximum torque output of the PI10 drive system?"

EXECUTION LOG:
[10:15:23] Step 1: Received user question
[10:15:24] Step 2: RAG Agent calling consult_rag tool...
[10:15:24]   → Azure Function: consult_rag triggered
[10:15:25]   → Searching pi10-documents index
[10:15:26]   → Found 5 relevant documents
[10:15:26]   ✓ Search completed
[10:15:27] Step 3: Response Generator creating answer...
[10:15:29]   ✓ Response generated

FINAL OUTPUT:
"The PI10 drive system delivers a maximum torque output of 450 Nm at peak
performance. The system maintains continuous torque of 350 Nm across the
operating range of 2000-6000 RPM. [Source: eDrivePredM.pdf, Section 3.2,
Page 47]"

Execution time: 6.2 seconds
Tokens used: 2,487
Cost: $0.075
```

---

## Prerequisites

### Assumed Already Deployed
This guide assumes you **already have**:
- ✅ Azure subscription
- ✅ Azure AI Foundry project (formerly AI Studio)
- ✅ Azure OpenAI resource with model deployment
- ✅ (Optional) Azure AI Search for RAG
- ✅ (Optional) Azure SQL for database access

### What You Need to Set Up
- Python 3.10+
- Azure CLI (for authentication)
- Git (for cloning the repository)

---

## Required Information from User

Before creating agents, gather the following information from your Azure environment:

### 1. **Azure AI Project Endpoint**
This is your Azure AI Foundry project endpoint.

**Format:** `https://{resource-name}.services.ai.azure.com/api/projects/{project-name}`

**How to find:**
- Azure Portal → AI Foundry / AI Studio → Your Project → Settings → Project Details
- Example: `https://pi12-resource.services.ai.azure.com/api/projects/pi12`

**Environment Variable:**
```bash
AZURE_AI_PROJECT_ENDPOINT="https://your-resource.services.ai.azure.com/api/projects/your-project"
```

---

### 2. **Azure OpenAI Endpoint and Model**
Your OpenAI resource endpoint and deployed model name.

**Format:** `https://{resource-name}.cognitiveservices.azure.com/`

**How to find:**
- Azure Portal → Azure OpenAI → Your Resource → Keys and Endpoint
- Model deployment: Azure OpenAI → Deployments → Model name

**Environment Variables:**
```bash
AZURE_OPENAI_ENDPOINT="https://your-resource.cognitiveservices.azure.com/"
AZURE_OPENAI_DEPLOYMENT="gpt-4o"  # Your model deployment name
AZURE_OPENAI_API_VERSION="2025-01-01-preview"
```

**Note:** API keys work for OpenAI calls but NOT for Agents API - use Azure CLI authentication instead.

---

### 3. **Azure AI Search (for RAG Agents)**
If using document search capabilities.

**Format:** `https://{search-name}.search.windows.net`

**How to find:**
- Azure Portal → Azure AI Search → Your Resource → Overview → URL

**Environment Variables:**
```bash
AZURE_SEARCH_ENDPOINT="https://your-search.search.windows.net"
AZURE_SEARCH_KEY="your-search-admin-key"  # Keys and Endpoint section
```

---

### 4. **Azure SQL (for SQL Agents)**
If using database agents.

**Connection Information:**
```bash
AZURE_SQL_SERVER="your-server.database.windows.net"
AZURE_SQL_DATABASE="your-database"
AZURE_SQL_USERNAME="your-username"
AZURE_SQL_PASSWORD="your-password"
```

---

### 5. **Azure Authentication**

**The Agents API requires OAuth tokens, NOT API keys.**

**Two authentication options:**

#### Option A: Azure CLI (Recommended)
```bash
# Install Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Login
az login

# Select your subscription
az account set --subscription "your-subscription-id"
```

#### Option B: Service Principal (Production)
```bash
AZURE_CLIENT_ID="your-client-id"
AZURE_CLIENT_SECRET="your-client-secret"
AZURE_TENANT_ID="your-tenant-id"
```

---

### 6. **Complete .env.azure File Template**

Create a `.env.azure` file in the project root:

```bash
# Azure AI Foundry Project
AZURE_AI_PROJECT_ENDPOINT=https://your-resource.services.ai.azure.com/api/projects/your-project

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2025-01-01-preview

# Azure AI Search (optional - for RAG)
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_KEY=your-search-admin-key

# Azure SQL (optional - for SQL agents)
AZURE_SQL_SERVER=your-server.database.windows.net
AZURE_SQL_DATABASE=your-database
AZURE_SQL_USERNAME=your-username
AZURE_SQL_PASSWORD=your-password

# Authentication (use CLI instead of API keys for Agents API)
# AZURE_OPENAI_API_KEY=your-key  # NOT used for Agents API
```

---

## SDK and Tools

### Python SDKs Required

Install all dependencies:

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Azure AI Agents SDK (beta)
pip install azure-ai-agents==1.2.0b5

# Install supporting libraries
pip install azure-identity==1.25.1
pip install azure-core==1.31.0
pip install openai==1.59.5
```

### Key Python Packages

```python
from azure.ai.agents.aio import AgentsClient          # Main client for agent operations
from azure.identity.aio import DefaultAzureCredential # Authentication
from azure.ai.agents.models import (
    AsyncFunctionTool,                                 # Tool definitions
    AsyncToolSet,                                      # Tool container
    FunctionTool,                                      # Sync version
    ToolSet                                            # Sync version
)
```

### Azure CLI

Required for OAuth authentication:

```bash
# Check version
az --version

# Should be 2.50.0 or higher
```

---

## Agent Anatomy

### What is an Agent in Azure Foundry?

An **Azure AI Agent** consists of:

1. **Name**: Unique identifier (e.g., `sql_agent`, `rag_agent`)
2. **Model**: Azure OpenAI deployment (e.g., `gpt-4o`)
3. **Instructions**: System prompt defining agent's role and capabilities
4. **Tools**: Functions the agent can call
5. **Tool Resources**: External resources (file search, code interpreter)

### Agent Definition Structure

```python
agent = {
    "name": "sql_agent",                    # Agent identifier
    "model": "gpt-4o",                      # OpenAI model deployment
    "instructions": "You are a SQL expert...",  # System prompt
    "tools": [                              # Tool definitions
        {
            "type": "function",
            "function": {
                "name": "execute_sql_query",
                "description": "Execute SQL query",
                "parameters": {             # JSON Schema
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "database": {"type": "string"}
                    },
                    "required": ["query"]
                }
            }
        }
    ],
    "tool_resources": {},                   # Optional: file_search, code_interpreter
    "metadata": {}                          # Custom key-value pairs
}
```

### Agent Components Explained

#### 1. Instructions (System Prompt)
Defines the agent's:
- Role and expertise
- Available capabilities
- Response format
- Behavioral guidelines

Example:
```python
instructions = """
You are a SQL database expert agent.

CAPABILITIES:
- Query databases using execute_sql_query tool
- Get schema information using get_database_schema tool
- Validate data sources before querying

RESPONSE FORMAT:
- Always explain query results
- Format data in tables when appropriate
- Report errors clearly

BEHAVIOR:
- Request schema before complex queries
- Validate database availability first
"""
```

#### 2. Tools (Function Definitions)

Tools are Python functions exposed to the agent. The SDK uses **docstring parsing** to generate JSON schemas automatically.

**Function Schema Requirements:**
```python
async def execute_sql_query(query: str, database: str = "default") -> str:
    """
    Execute SQL query on database.

    :param query: SQL query string to execute
    :param database: Database name to query against (default: "default")
    :return: Query results as JSON string
    """
    # Implementation
    pass
```

**The SDK extracts:**
- Function name: `execute_sql_query`
- Description: First line of docstring
- Parameters: From type hints and `:param` tags
- Return type: From return type hint

#### 3. Tool Resources

Optional resources for built-in capabilities:

```python
from azure.ai.agents.models import FileSearchToolResource, VectorStoreConfiguration

tool_resources = {
    "file_search": FileSearchToolResource(
        vector_stores=[
            VectorStoreConfiguration(
                file_ids=["file-123", "file-456"]
            )
        ]
    )
}
```

---

## Creating Agents: Step-by-Step

### Step 1: Project Setup

```bash
# Clone the repository
git clone https://github.com/your-org/agent-framework.git
cd agent-framework

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.azure.template .env.azure
# Edit .env.azure with your values

# Authenticate with Azure
az login
az account set --subscription "your-subscription-id"
```

---

### Step 2: Define Agent Configuration

Create agent definitions in Python:

**File: `scripts/agent_definitions.py`**

```python
"""Agent definitions for Azure Foundry deployment"""

AGENT_DEFINITIONS = {
    "supervisor": {
        "name": "supervisor_agent",
        "model": "gpt-4o",
        "instructions": """
You are the Supervisor Agent coordinating a team of specialized agents.

AVAILABLE AGENTS:
- planner_agent: Creates workflow plans
- executor_agent: Executes workflows step-by-step
- sql_agent: Queries databases
- rag_agent: Searches documents
- response_generator: Formats final outputs

YOUR ROLE:
1. Analyze user requests
2. Determine which agents to invoke
3. Coordinate agent handoffs
4. Return final formatted response

TOOLS:
- invoke_agent: Hand off tasks to specialized agents
- list_available_agents: See which agents are available
- validate_data_source: Check if data sources exist
        """,
        "tools": [
            "invoke_agent",
            "list_available_agents",
            "validate_data_source"
        ]
    },

    "sql_agent": {
        "name": "sql_agent",
        "model": "gpt-4o",
        "instructions": """
You are a SQL Database Expert Agent.

CAPABILITIES:
- Execute SQL queries using execute_sql_query tool
- Get database schema using get_database_schema tool
- Validate queries before execution

WORKFLOW:
1. If unsure about schema, call get_database_schema first
2. Construct appropriate SQL query
3. Execute using execute_sql_query
4. Return results with explanation

SAFETY:
- Never execute DROP, DELETE, or TRUNCATE without explicit confirmation
- Validate table names against schema
- Use parameterized queries when possible
        """,
        "tools": [
            "execute_sql_query",
            "get_database_schema"
        ]
    },

    "rag_agent": {
        "name": "rag_agent",
        "model": "gpt-4o",
        "instructions": """
You are a Document Search and Retrieval Agent.

CAPABILITIES:
- Search documents using consult_rag tool
- Extract relevant information from search results
- Cite sources accurately

WORKFLOW:
1. Receive search query
2. Use consult_rag to search documents
3. Analyze results for relevance
4. Return answer with citations

RESPONSE FORMAT:
- Provide clear, concise answers
- Always cite sources with document IDs
- Indicate confidence level in findings
        """,
        "tools": [
            "consult_rag"
        ],
        "tool_resources": {
            "file_search": {
                "vector_store_ids": ["vs_123456"]  # Pre-created vector store
            }
        }
    }
}
```

---

### Step 3: Define Tool Functions

Create tool implementations:

**File: `agent_framework/tools/database_tools.py`**

```python
"""Database tool functions for SQL Agent"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

class DatabaseTools:
    def __init__(self, db_connector):
        self.db_connector = db_connector

    async def execute_sql_query(self, query: str, database: str = "default") -> str:
        """
        Execute SQL query on specified database.

        :param query: SQL query string to execute
        :param database: Database name (default: "default")
        :return: Query results as JSON string
        """
        logger.info(f"Executing SQL on {database}: {query}")

        try:
            results = self.db_connector.execute(query, database)
            logger.info(f"Query returned {len(results)} rows")
            return json.dumps(results, indent=2)
        except Exception as e:
            error_msg = f"SQL execution error: {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

    async def get_database_schema(self, database: str = "default") -> str:
        """
        Get schema information for database.

        :param database: Database name (default: "default")
        :return: Schema description as string
        """
        logger.info(f"Getting schema for {database}")

        try:
            schema = self.db_connector.get_schema(database)
            return schema
        except Exception as e:
            error_msg = f"Schema retrieval error: {str(e)}"
            logger.error(error_msg)
            return error_msg
```

**File: `agent_framework/tools/rag_tools.py`**

```python
"""RAG tool functions for document search"""

import json
import logging

logger = logging.getLogger(__name__)

class RAGTools:
    def __init__(self, search_client):
        self.search_client = search_client

    async def consult_rag(
        self,
        query: str,
        top_k: int = 5,
        filters: str = ""
    ) -> str:
        """
        Search documents using RAG.

        :param query: Search query string
        :param top_k: Number of results to return (default: 5)
        :param filters: Optional filter expression as string
        :return: Search results as JSON string
        """
        logger.info(f"RAG search: {query} (top_k={top_k})")

        try:
            results = await self.search_client.search(
                query=query,
                top=top_k,
                filter=filters if filters else None
            )

            formatted_results = []
            for result in results:
                formatted_results.append({
                    "document_id": result["id"],
                    "title": result["title"],
                    "content": result["content"][:500],  # Truncate
                    "score": result["@search.score"]
                })

            logger.info(f"Found {len(formatted_results)} documents")
            return json.dumps(formatted_results, indent=2)

        except Exception as e:
            error_msg = f"RAG search error: {str(e)}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})
```

**File: `agent_framework/tools/orchestration_tools.py`**

```python
"""Tools for agent orchestration"""

import json
import logging

logger = logging.getLogger(__name__)

class OrchestrationTools:
    def __init__(self, agents_client, config):
        self.agents_client = agents_client
        self.config = config

    async def invoke_agent(
        self,
        agent_name: str,
        message: str,
        context: str = ""
    ) -> str:
        """
        Invoke another agent (agent-to-agent handoff).

        :param agent_name: Name of agent to invoke
        :param message: Message to send to agent
        :param context: Optional context as JSON string
        :return: Agent's response as string
        """
        logger.info(f"Agent handoff → {agent_name}")

        # Lookup agent ID
        agent_id = None
        for key, agent_data in self.config["agents"].items():
            if key == agent_name or agent_data.get("name") == agent_name:
                agent_id = agent_data.get("id")
                break

        if not agent_id:
            error = f"Agent not found: {agent_name}"
            logger.error(error)
            return json.dumps({"error": error})

        # Run agent
        result = await self.agents_client.create_thread_and_process_run(
            agent_id=agent_id,
            thread={"messages": [{"role": "user", "content": message}]}
        )

        return f"Agent {agent_name} completed. Thread: {result.thread_id}"

    async def list_available_agents(self) -> str:
        """
        List all available agents.

        :return: Agent list as JSON string
        """
        agents = []
        for key, data in self.config["agents"].items():
            agents.append({
                "name": data["name"],
                "description": f"Agent: {data['name']}"
            })

        return json.dumps({"agents": agents}, indent=2)
```

---

### Step 4: Create Agent Creation Script

**File: `scripts/create_azure_agents.py`**

```python
"""
Script to create all agents in Azure AI Foundry
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential

from agent_definitions import AGENT_DEFINITIONS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_agent(
    client: AgentsClient,
    agent_def: Dict[str, Any]
) -> Dict[str, str]:
    """Create a single agent in Azure Foundry"""

    name = agent_def["name"]
    logger.info(f"Creating agent: {name}")

    # Build tools array for Azure API
    tools = []
    for tool_name in agent_def.get("tools", []):
        tools.append({
            "type": "function",
            "function": {
                "name": tool_name,
                "description": f"Tool: {tool_name}",
                # Schema will be added by AsyncFunctionTool at runtime
            }
        })

    # Create agent
    agent = await client.create_agent(
        model=agent_def["model"],
        name=name,
        instructions=agent_def["instructions"],
        tools=tools,
        tool_resources=agent_def.get("tool_resources", {}),
        metadata={"created_by": "agent_framework"}
    )

    logger.info(f"✓ Created {name}: {agent.id}")

    return {
        "id": agent.id,
        "name": name
    }


async def main():
    """Create all agents in Azure Foundry"""

    # Load environment
    env_file = Path(__file__).parent.parent / ".env.azure"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

    project_endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    model = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    logger.info("="*70)
    logger.info("Creating Azure Foundry Agents")
    logger.info("="*70)
    logger.info(f"Project: {project_endpoint}")
    logger.info(f"Model: {model}")
    logger.info("")

    # Initialize Azure client
    credential = DefaultAzureCredential()
    agents_client = AgentsClient(
        endpoint=project_endpoint,
        credential=credential
    )

    try:
        created_agents = {}

        # Create each agent
        for agent_key, agent_def in AGENT_DEFINITIONS.items():
            agent_info = await create_agent(agents_client, agent_def)
            created_agents[agent_key] = agent_info

        # Save configuration
        config = {
            "created_at": datetime.utcnow().isoformat() + "Z",
            "project_endpoint": project_endpoint,
            "model": model,
            "agents": created_agents
        }

        config_file = Path(__file__).parent.parent / "azure_agents_config.json"
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

        logger.info("")
        logger.info("="*70)
        logger.info("✓ All agents created successfully!")
        logger.info(f"✓ Configuration saved: {config_file}")
        logger.info("="*70)

        # Print summary
        logger.info("\nAgent Summary:")
        for key, info in created_agents.items():
            logger.info(f"  {key:20} → {info['id']}")

    finally:
        await credential.close()
        await agents_client.close()


if __name__ == "__main__":
    asyncio.run(main())
```

---

### Step 5: Run Agent Creation

```bash
# Activate virtual environment
source venv/bin/activate

# Ensure authenticated
az login
az account set --subscription "your-subscription-id"

# Create agents
python scripts/create_azure_agents.py
```

**Expected Output:**
```
======================================================================
Creating Azure Foundry Agents
======================================================================
Project: https://pi12-resource.services.ai.azure.com/api/projects/pi12
Model: gpt-4o

Creating agent: supervisor_agent
✓ Created supervisor_agent: asst_m2QXNBwm581MG07JNMpEWrjp
Creating agent: sql_agent
✓ Created sql_agent: asst_WyXNFtXxcLqqUQKrlwkr3g3U
Creating agent: rag_agent
✓ Created rag_agent: asst_gt2ZvhKg1w23w5MVp4IlvGQ6

======================================================================
✓ All agents created successfully!
✓ Configuration saved: azure_agents_config.json
======================================================================

Agent Summary:
  supervisor           → asst_m2QXNBwm581MG07JNMpEWrjp
  sql_agent            → asst_WyXNFtXxcLqqUQKrlwkr3g3U
  rag_agent            → asst_gt2ZvhKg1w23w5MVp4IlvGQ6
```

**Generated Config File (`azure_agents_config.json`):**
```json
{
  "created_at": "2025-12-03T11:00:00Z",
  "project_endpoint": "https://pi12-resource.services.ai.azure.com/api/projects/pi12",
  "model": "gpt-4o",
  "agents": {
    "supervisor": {
      "id": "asst_m2QXNBwm581MG07JNMpEWrjp",
      "name": "supervisor_agent"
    },
    "sql_agent": {
      "id": "asst_WyXNFtXxcLqqUQKrlwkr3g3U",
      "name": "sql_agent"
    },
    "rag_agent": {
      "id": "asst_gt2ZvhKg1w23w5MVp4IlvGQ6",
      "name": "rag_agent"
    }
  }
}
```

---

## Agent Examples

### Example 1: SQL Agent Deep Dive

#### Agent Definition

```python
sql_agent = {
    "name": "sql_agent",
    "model": "gpt-4o",
    "instructions": """
You are a SQL Database Expert Agent specialized in querying databases.

AVAILABLE TOOLS:
1. get_database_schema(database: str) -> str
   - Returns table structure, columns, types
   - Use before writing complex queries

2. execute_sql_query(query: str, database: str) -> str
   - Executes SQL and returns results as JSON
   - Supports SELECT, INSERT, UPDATE (with caution)

WORKFLOW:
1. Understand the user's question
2. If table structure unknown, call get_database_schema
3. Construct SQL query based on schema
4. Execute query using execute_sql_query
5. Format results in a clear, readable format

BEST PRACTICES:
- Always use proper SQL syntax
- Use JOINs when querying multiple tables
- Add appropriate WHERE clauses for filtering
- Use ORDER BY and LIMIT for ranked results
- Explain the query before and results after

SAFETY:
- Never execute DROP, DELETE, or TRUNCATE without explicit user confirmation
- Validate table and column names against schema
- Use single quotes for string literals
- Handle NULL values gracefully

RESPONSE FORMAT:
1. Explain the approach
2. Show the SQL query
3. Present results in a table
4. Provide summary insights
    """,
    "tools": ["execute_sql_query", "get_database_schema"]
}
```

#### Tool Implementation

```python
# File: agent_framework/connectors/sql_connector.py

import sqlite3
from typing import Any, Dict, List

class SQLConnector:
    """Database connector for SQL operations"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_schema(self) -> str:
        """Get database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get all tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = cursor.fetchall()

            schema_parts = []
            for (table_name,) in tables:
                # Get columns
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()

                col_desc = []
                for _, col_name, col_type, not_null, _, pk in columns:
                    null_str = "NOT NULL" if not_null else "NULL"
                    pk_str = " PRIMARY KEY" if pk else ""
                    col_desc.append(
                        f"  {col_name} {col_type} {null_str}{pk_str}"
                    )

                schema_parts.append(
                    f"Table: {table_name}\n" + "\n".join(col_desc)
                )

            return "\n\n".join(schema_parts)

        finally:
            conn.close()

    def execute(self, query: str) -> List[Dict[str, Any]]:
        """Execute SQL query"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            cursor = conn.cursor()
            cursor.execute(query)

            # Handle SELECT vs INSERT/UPDATE/DELETE
            if cursor.description is None:
                conn.commit()
                return [{"rows_affected": cursor.rowcount}]

            # Fetch results
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        finally:
            conn.close()
```

#### Usage Example

```python
# User query: "Show me the top 5 products by price"

# Agent workflow:
# 1. Calls get_database_schema("products_db")
# 2. Receives schema:
#    Table: products
#      product_id INTEGER NOT NULL PRIMARY KEY
#      name TEXT NOT NULL
#      category TEXT
#      price REAL
#      stock INTEGER

# 3. Constructs query:
query = """
SELECT name, category, price, stock
FROM products
ORDER BY price DESC
LIMIT 5
"""

# 4. Calls execute_sql_query(query, "products_db")
# 5. Receives results:
[
  {"name": "Laptop Pro", "category": "Electronics", "price": 1299.99, "stock": 45},
  {"name": "Monitor 4K", "category": "Electronics", "price": 899.99, "stock": 30},
  ...
]

# 6. Formats response as table:
"""
Top 5 Products by Price:

| Product      | Category    | Price    | Stock |
|--------------|-------------|----------|-------|
| Laptop Pro   | Electronics | $1,299.99| 45    |
| Monitor 4K   | Electronics | $899.99  | 30    |
| ...          | ...         | ...      | ...   |
"""
```

---

### Example 2: RAG Agent Deep Dive

#### Agent Definition

```python
rag_agent = {
    "name": "rag_agent",
    "model": "gpt-4o",
    "instructions": """
You are a Document Search and Retrieval-Augmented Generation (RAG) Agent.

CAPABILITIES:
1. Search document collections using semantic search
2. Extract relevant information from search results
3. Synthesize answers from multiple sources
4. Cite sources accurately

AVAILABLE TOOLS:
- consult_rag(query: str, top_k: int, filters: str) -> str
  Returns: JSON array of relevant documents with scores

WORKFLOW:
1. Receive user question
2. Formulate effective search query
3. Call consult_rag with appropriate parameters
4. Analyze returned documents for relevance
5. Synthesize answer from document content
6. Cite sources with document IDs

RESPONSE FORMAT:
[Answer based on sources]

Sources:
- [Document Title] (ID: doc-123, Score: 0.89)
- [Document Title] (ID: doc-456, Score: 0.76)

QUALITY GUIDELINES:
- Only use information from returned documents
- If documents don't contain answer, say so explicitly
- Indicate confidence level (high/medium/low)
- Prefer recent documents when dates available
- Cross-reference multiple sources when possible

CITATION RULES:
- Always cite document ID
- Include relevance score
- Quote key passages directly when appropriate
- Indicate if answer is partial or incomplete
    """,
    "tools": ["consult_rag"],
    "tool_resources": {
        "file_search": {
            "vector_store_ids": ["vs_abc123"]
        }
    }
}
```

#### Tool Implementation

```python
# File: agent_framework/connectors/search_connector.py

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
import json
from typing import List, Dict, Any

class AzureSearchConnector:
    """Azure AI Search connector for RAG"""

    def __init__(self, endpoint: str, key: str, index_name: str):
        self.client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=AzureKeyCredential(key)
        )

    async def search(
        self,
        query: str,
        top: int = 5,
        filter: str = None
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search

        Args:
            query: Search query string
            top: Number of results (default 5)
            filter: OData filter expression

        Returns:
            List of document dictionaries
        """
        results = await self.client.search(
            search_text=query,
            top=top,
            filter=filter,
            include_total_count=True,
            query_type="semantic",
            semantic_configuration_name="default"
        )

        documents = []
        async for result in results:
            documents.append({
                "id": result["id"],
                "title": result.get("title", "Untitled"),
                "content": result.get("content", ""),
                "score": result.get("@search.score", 0.0),
                "reranker_score": result.get("@search.reranker_score", None),
                "metadata": {
                    "source": result.get("source", "Unknown"),
                    "created_at": result.get("created_at", None)
                }
            })

        return documents
```

#### Usage Example

```python
# User query: "What are the best practices for electric vehicle battery maintenance?"

# Agent workflow:
# 1. Formulates search query (may rephrase for better results)
search_query = "electric vehicle EV battery maintenance best practices"

# 2. Calls consult_rag
results = await consult_rag(
    query=search_query,
    top_k=5,
    filters=""  # No filters
)

# 3. Receives documents:
[
  {
    "id": "doc-ev-maintenance-2024",
    "title": "EV Battery Care Guidelines 2024",
    "content": "Best practices for EV battery maintenance include: 1) Keep charge between 20-80% for daily use, 2) Avoid extreme temperatures...",
    "score": 0.92
  },
  {
    "id": "doc-battery-longevity",
    "title": "Maximizing EV Battery Lifespan",
    "content": "Research shows that limiting fast charging to 10-15% of total charges significantly extends battery life...",
    "score": 0.87
  },
  ...
]

# 4. Synthesizes answer:
"""
Based on current EV maintenance guidelines, here are the key best practices:

1. **Optimal Charging Range**: Keep your battery between 20-80% for daily use. This reduces stress on battery cells and extends overall lifespan.

2. **Temperature Management**: Avoid exposing your EV to extreme temperatures. Park in shaded or climate-controlled areas when possible.

3. **Fast Charging Limits**: Limit DC fast charging to 10-15% of total charges. Regular use of fast charging can accelerate battery degradation.

4. **Regular Use**: Drive your EV regularly. Batteries perform best with consistent use rather than long periods of inactivity.

5. **Software Updates**: Keep your EV's battery management system updated for optimal performance.

Sources:
- EV Battery Care Guidelines 2024 (ID: doc-ev-maintenance-2024, Score: 0.92)
- Maximizing EV Battery Lifespan (ID: doc-battery-longevity, Score: 0.87)

Confidence: High (based on multiple authoritative sources)
"""
```

---

## Code Structure

### Project Directory Layout

```
agent-framework/
├── .env.azure                          # Environment variables
├── azure_agents_config.json            # Created agent IDs
├── requirements.txt                    # Python dependencies
│
├── scripts/
│   ├── create_azure_agents.py         # Agent creation script
│   ├── agent_definitions.py           # Agent configurations
│   ├── delete_all_agents.py           # Cleanup script
│   └── list_agents.py                 # View deployed agents
│
├── agent_framework/
│   ├── __init__.py
│   │
│   ├── agents/                        # Agent implementations
│   │   ├── __init__.py
│   │   ├── supervisor.py
│   │   ├── sql_agent.py
│   │   └── rag_agent.py
│   │
│   ├── connectors/                    # Data source connectors
│   │   ├── __init__.py
│   │   ├── sql_connector.py
│   │   └── search_connector.py
│   │
│   ├── tools/                         # Tool implementations
│   │   ├── __init__.py
│   │   ├── database_tools.py
│   │   ├── rag_tools.py
│   │   └── orchestration_tools.py
│   │
│   ├── orchestrator/                  # Multi-agent orchestration
│   │   ├── __init__.py
│   │   ├── workflow.py
│   │   └── runner.py
│   │
│   └── schemas/                       # Data models
│       ├── __init__.py
│       ├── agent_config.py
│       └── tool_schemas.py
│
├── examples/
│   ├── complete_e2e_test.py          # Full workflow test
│   ├── sql_agent_example.py          # SQL agent demo
│   └── rag_agent_example.py          # RAG agent demo
│
└── docs/
    ├── UserGuide.md                   # This file
    ├── Architecture.md
    └── API_Reference.md
```

---

## Azure Foundry YAML Representation

### What is YAML in Azure Foundry?

While agents are created via Python SDK, Azure Foundry internally represents them in YAML format. This is visible when:
- Exporting agent configurations
- Viewing agent details in Azure AI Studio
- CI/CD deployment pipelines

### SQL Agent YAML Representation

```yaml
# sql_agent.yaml
name: sql_agent
model: gpt-4o
description: SQL database expert agent for querying databases

instructions: |
  You are a SQL Database Expert Agent specialized in querying databases.

  AVAILABLE TOOLS:
  1. get_database_schema(database: str) -> str
  2. execute_sql_query(query: str, database: str) -> str

  WORKFLOW:
  1. Understand the user's question
  2. If table structure unknown, call get_database_schema
  3. Construct SQL query based on schema
  4. Execute query using execute_sql_query
  5. Format results clearly

tools:
  - type: function
    function:
      name: execute_sql_query
      description: Execute SQL query on specified database
      parameters:
        type: object
        properties:
          query:
            type: string
            description: SQL query string to execute
          database:
            type: string
            description: Database name to query against
            default: "default"
        required:
          - query

  - type: function
    function:
      name: get_database_schema
      description: Get schema information for database
      parameters:
        type: object
        properties:
          database:
            type: string
            description: Database name
            default: "default"

metadata:
  created_by: agent_framework
  version: "1.0"
  environment: production

temperature: 0.7
top_p: 0.95
```

### RAG Agent YAML Representation

```yaml
# rag_agent.yaml
name: rag_agent
model: gpt-4o
description: Document search and retrieval agent using RAG

instructions: |
  You are a Document Search and RAG Agent.

  CAPABILITIES:
  - Search documents using semantic search
  - Extract relevant information
  - Synthesize answers from sources
  - Cite sources accurately

  WORKFLOW:
  1. Receive question
  2. Call consult_rag tool
  3. Analyze returned documents
  4. Synthesize answer with citations

tools:
  - type: function
    function:
      name: consult_rag
      description: Search documents using RAG
      parameters:
        type: object
        properties:
          query:
            type: string
            description: Search query string
          top_k:
            type: integer
            description: Number of results to return
            default: 5
          filters:
            type: string
            description: Optional filter expression
            default: ""
        required:
          - query

tool_resources:
  file_search:
    vector_store_ids:
      - vs_abc123def456  # Azure AI Search vector store

metadata:
  created_by: agent_framework
  version: "1.0"
  capabilities:
    - document_search
    - semantic_search
    - citation_generation

temperature: 0.7
top_p: 0.95
```

### Supervisor Agent YAML Representation

```yaml
# supervisor_agent.yaml
name: supervisor_agent
model: gpt-4o
description: Orchestrates multi-agent workflows

instructions: |
  You are the Supervisor Agent coordinating specialized agents.

  AVAILABLE AGENTS:
  - sql_agent: Database queries
  - rag_agent: Document search
  - response_generator: Output formatting

  YOUR ROLE:
  1. Analyze user requests
  2. Determine which agents to invoke
  3. Coordinate agent handoffs
  4. Return final response

tools:
  - type: function
    function:
      name: invoke_agent
      description: Hand off task to specialized agent
      parameters:
        type: object
        properties:
          agent_name:
            type: string
            description: Name of agent to invoke
            enum:
              - sql_agent
              - rag_agent
              - response_generator
          message:
            type: string
            description: Message to send to agent
          context:
            type: string
            description: Optional context as JSON
            default: ""
        required:
          - agent_name
          - message

  - type: function
    function:
      name: list_available_agents
      description: List all available agents
      parameters:
        type: object
        properties: {}

metadata:
  created_by: agent_framework
  version: "1.0"
  role: orchestrator

temperature: 0.7
top_p: 0.95
```

### Converting Python to YAML

You can export agents to YAML for version control:

```python
# File: scripts/export_agents_yaml.py

import asyncio
import json
import yaml
from pathlib import Path
from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential

async def export_agent_to_yaml(client: AgentsClient, agent_id: str, output_dir: Path):
    """Export agent configuration to YAML"""

    # Get agent details
    agent = await client.get_agent(agent_id)

    # Convert to YAML-friendly dict
    agent_yaml = {
        "name": agent.name,
        "model": agent.model,
        "description": f"{agent.name} agent",
        "instructions": agent.instructions,
        "tools": [],
        "metadata": agent.metadata or {}
    }

    # Add tools
    if agent.tools:
        for tool in agent.tools:
            if tool.type == "function":
                agent_yaml["tools"].append({
                    "type": "function",
                    "function": {
                        "name": tool.function.name,
                        "description": tool.function.description,
                        "parameters": tool.function.parameters
                    }
                })

    # Add tool resources
    if agent.tool_resources:
        agent_yaml["tool_resources"] = json.loads(
            agent.tool_resources.model_dump_json()
        )

    # Write YAML
    output_file = output_dir / f"{agent.name}.yaml"
    with open(output_file, "w") as f:
        yaml.dump(agent_yaml, f, default_flow_style=False, sort_keys=False)

    print(f"✓ Exported {agent.name} → {output_file}")

async def main():
    # Load config
    with open("azure_agents_config.json") as f:
        config = json.load(f)

    # Initialize client
    credential = DefaultAzureCredential()
    client = AgentsClient(
        endpoint=config["project_endpoint"],
        credential=credential
    )

    output_dir = Path("exported_agents")
    output_dir.mkdir(exist_ok=True)

    try:
        for agent_key, agent_data in config["agents"].items():
            await export_agent_to_yaml(
                client,
                agent_data["id"],
                output_dir
            )
    finally:
        await credential.close()
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Running and Testing

### Test Individual Agent

```python
# File: examples/test_sql_agent.py

import asyncio
import json
from pathlib import Path
from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential

async def test_sql_agent():
    # Load config
    with open("azure_agents_config.json") as f:
        config = json.load(f)

    # Initialize client
    credential = DefaultAzureCredential()
    client = AgentsClient(
        endpoint=config["project_endpoint"],
        credential=credential
    )

    # Register tools (simplified - full implementation in workflow.py)
    from agent_framework.tools.database_tools import DatabaseTools
    from agent_framework.connectors.sql_connector import SQLConnector

    db_tools = DatabaseTools(SQLConnector("test.db"))

    from azure.ai.agents.models import AsyncFunctionTool
    function_tool = AsyncFunctionTool({
        db_tools.execute_sql_query,
        db_tools.get_database_schema
    })

    client.enable_auto_function_calls(function_tool, max_retry=10)

    try:
        # Run SQL agent
        agent_id = config["agents"]["sql_agent"]["id"]

        result = await client.create_thread_and_process_run(
            agent_id=agent_id,
            thread={
                "messages": [{
                    "role": "user",
                    "content": "Show me the top 5 products by price with their category and stock"
                }]
            }
        )

        print(f"Status: {result.status}")
        print(f"Thread: {result.thread_id}")

    finally:
        await credential.close()
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_sql_agent())
```

### Test Multi-Agent Workflow

```python
# File: examples/complete_e2e_test.py

import asyncio
from agent_framework.orchestrator.workflow import MultiAgentWorkflow
from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential

async def main():
    # Load config
    import json
    with open("azure_agents_config.json") as f:
        config = json.load(f)

    # Initialize
    credential = DefaultAzureCredential()
    client = AgentsClient(
        endpoint=config["project_endpoint"],
        credential=credential
    )

    try:
        # Create workflow
        workflow = MultiAgentWorkflow(client, config)
        workflow.setup_database("test.db")

        # Run workflow
        result = await workflow.execute_workflow(
            "Analyze our sales database. Show top 5 products by revenue and summarize trends."
        )

        print("="*70)
        print("FINAL RESULT")
        print("="*70)
        print(result["final_response"])
        print("\nExecution Log:")
        for log in result["execution_log"]:
            print(f"  {log}")

    finally:
        await credential.close()
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Run Tests

```bash
# Test individual SQL agent
python examples/test_sql_agent.py

# Test RAG agent
python examples/test_rag_agent.py

# Test complete workflow
python examples/complete_e2e_test.py
```

---

## Troubleshooting

### Common Issues

#### 1. Authentication Errors

**Error:**
```
Unauthorized. Access token is missing, invalid, audience is incorrect (https://ai.azure.com)
```

**Solution:**
```bash
# Re-authenticate with Azure CLI
az login
az account set --subscription "your-subscription-id"

# Verify authentication
az account show
```

#### 2. Agent Not Found

**Error:**
```
(None) No assistant found with id 'asst_xxxxxxxxxx'
```

**Solution:**
```bash
# List current agents
python scripts/list_agents.py

# If agents were deleted, recreate them
python scripts/create_azure_agents.py

# Update azure_agents_config.json with new IDs
```

#### 3. Function Not Found

**Error:**
```
Error executing function 'execute_sql_query': Function 'execute_sql_query' not found
```

**Solution:**
```python
# Ensure functions are registered BEFORE creating thread
client.enable_auto_function_calls(function_tool, max_retry=10)

# Then run agent
result = await client.create_thread_and_process_run(...)
```

#### 4. Circular Import

**Error:**
```
ImportError: cannot import name 'SQLConnector' from partially initialized module
```

**Solution:**
```python
# Use standalone connectors without framework dependencies
from agent_framework_azure_ai.connectors.standalone_sql import SimpleSQLiteConnector

# Or use importlib to avoid initialization
import importlib.util
spec = importlib.util.spec_from_file_location("connector", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
```

#### 5. Invalid Function Schema

**Error:**
```
(invalid_function_parameters) Invalid schema for function 'my_func': array schema missing items
```

**Solution:**
```python
# Don't use complex type hints like list[dict]
# BAD:
async def my_func(data: list[dict]) -> str:
    pass

# GOOD - use JSON strings:
async def my_func(data: str) -> str:
    """
    :param data: JSON string containing array of objects
    """
    parsed = json.loads(data)
    pass
```

### Debugging Tips

#### Enable Verbose Logging

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# See all Azure SDK calls
logging.getLogger("azure").setLevel(logging.DEBUG)
```

#### Inspect Agent Configuration

```python
# Get agent details
agent = await client.get_agent(agent_id)

print(f"Name: {agent.name}")
print(f"Model: {agent.model}")
print(f"Instructions: {agent.instructions[:200]}...")
print(f"Tools: {len(agent.tools)}")

for tool in agent.tools:
    if tool.type == "function":
        print(f"  - {tool.function.name}")
```

#### Test Tool Functions Directly

```python
# Test tools outside of agent context
from agent_framework.tools.database_tools import DatabaseTools
from agent_framework.connectors.sql_connector import SQLConnector

db_tools = DatabaseTools(SQLConnector("test.db"))

# Test schema retrieval
schema = await db_tools.get_database_schema("default")
print(schema)

# Test query execution
result = await db_tools.execute_sql_query(
    "SELECT * FROM products LIMIT 5",
    "default"
)
print(result)
```

### Getting Help

- **Azure AI Foundry Docs:** https://learn.microsoft.com/azure/ai-studio/
- **Azure AI Agents SDK:** https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/ai/azure-ai-agents
- **GitHub Issues:** Open issues in the framework repository
- **Azure Support:** Contact Azure support for platform issues

---

## Best Practices

### 1. Agent Design
- Keep instructions clear and concise
- Define specific roles and capabilities
- Provide examples in instructions
- Set clear boundaries and limitations

### 2. Tool Design
- Use descriptive function names
- Include comprehensive docstrings
- Use type hints for parameter validation
- Return JSON strings for complex data
- Handle errors gracefully

### 3. Security
- Never hardcode credentials
- Use Azure Key Vault for secrets
- Implement approval workflows for destructive operations
- Validate all inputs in tool functions
- Log all agent actions for auditing

### 4. Performance
- Register tools once at startup (use `enable_auto_function_calls`)
- Reuse `AgentsClient` instances
- Implement caching for expensive operations
- Use async/await properly
- Monitor token usage and costs

### 5. Testing
- Test tools independently before integration
- Create unit tests for tool functions
- Test agent workflows end-to-end
- Validate error handling
- Monitor agent performance

### 6. Monitoring
- Log all agent interactions
- Track tool execution times
- Monitor token consumption
- Set up alerts for failures
- Analyze user queries for improvements

---

## Summary

You now have a complete guide to creating agents in Azure AI Foundry. Key takeaways:

✅ **Required Information:**
- Azure AI Project endpoint
- Azure OpenAI endpoint and deployment
- Azure CLI authentication
- Optional: Search endpoint, SQL connection

✅ **Key Steps:**
1. Set up environment variables
2. Define agent configurations
3. Implement tool functions
4. Run creation script
5. Test agents

✅ **Agent Components:**
- Name, model, instructions
- Tools (function definitions)
- Tool resources (file search, code interpreter)

✅ **Code Structure:**
- `scripts/` - Agent creation and management
- `agent_framework/agents/` - Agent implementations
- `agent_framework/tools/` - Tool functions
- `agent_framework/connectors/` - Data source connectors
- `examples/` - Usage examples

✅ **Critical SDK Method:**
```python
# Register tools globally for automatic execution
client.enable_auto_function_calls(function_tool, max_retry=10)
```

Happy agent building! 🚀
