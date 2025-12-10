# Getting Started Guide

This guide walks you through setting up the HIL Agentic Workflow Framework from scratch.

## Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend runtime |
| Azure CLI | 2.50+ | Azure resource management |
| Git | 2.x | Version control |

### Required Azure Resources

| Resource | Service | Purpose |
|----------|---------|---------|
| Azure OpenAI | GPT-4o | LLM for agents |
| Azure OpenAI | text-embedding-3-large | Vector embeddings |
| Azure AI Search | Standard tier | RAG vector store |
| Azure Storage | Blob | Document and cache storage |
| Azure Functions | Python 3.11 | Serverless backend |
| Azure AI Foundry | Project | Agent management |

---

## Step 1: Clone Repository

```bash
git clone https://github.com/YOUR_ORG/agent-framework.git
cd agent-framework
```

## Step 2: Python Environment

```bash
# Create virtual environment
python -m venv venv

# Activate (Linux/Mac)
source venv/bin/activate

# Activate (Windows)
.\venv\Scripts\activate

# Install core packages
pip install -e python/packages/core
pip install -e python/packages/azure-ai
pip install -e python/packages/api

# Install additional dependencies
pip install duckdb psycopg2-binary azure-ai-textanalytics azure-ai-documentintelligence
```

## Step 3: Azure Configuration

### 3.1 Create Configuration File

```bash
cp .env.azure.template .env.azure
```

### 3.2 Required Environment Variables

Edit `.env.azure` with your Azure credentials:

```bash
# ===================== AZURE OPENAI =====================
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# ===================== AZURE AI SEARCH =====================
AZURE_SEARCH_ENDPOINT=https://YOUR-SEARCH.search.windows.net
AZURE_SEARCH_KEY=your-search-key
AZURE_SEARCH_INDEX=documents

# ===================== EMBEDDINGS =====================
AZURE_EMBEDDING_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com
AZURE_EMBEDDING_API_KEY=your-api-key
AZURE_EMBEDDING_DEPLOYMENT=text-embedding-3-large

# ===================== AZURE STORAGE =====================
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...

# ===================== AZURE AI FOUNDRY (Optional) =====================
AZURE_AI_FOUNDRY_PROJECT_CONNECTION_STRING=your-connection-string

# ===================== AZURE FUNCTIONS =====================
AZURE_FUNCTIONS_URL=https://your-functions.azurewebsites.net
AZURE_FUNCTIONS_KEY=your-functions-key
```

### 3.3 How to Get Azure Credentials

**Azure OpenAI:**
1. Go to [Azure Portal](https://portal.azure.com) → Azure OpenAI
2. Create resource → Deploy models (gpt-4o, text-embedding-3-large)
3. Copy endpoint and keys from "Keys and Endpoint"

**Azure AI Search:**
1. Create Azure AI Search resource (Standard tier for semantic ranking)
2. Copy endpoint from Overview, keys from Settings → Keys

**Azure Storage:**
1. Create Storage Account
2. Go to Access Keys → Copy connection string

---

## Step 4: Create Search Index

```bash
# Create the index with proper schema
python scripts/create_search_index.py
```

This creates an index with:
- Vector field for embeddings
- Semantic configuration for reranking
- Facetable fields for entity aggregation

---

## Step 5: Deploy Azure Functions

```bash
# Login to Azure
az login

# Deploy functions
./scripts/deploy_azure_functions.sh
```

The deployment includes these functions:
- `index_document` - Document processing and indexing
- `consult_rag` - RAG retrieval
- `execute_azure_sql` - SQL execution
- `invoke_agent` - Agent invocation

---

## Step 6: Create Azure Agents (Optional)

If using Azure AI Foundry agents:

```bash
python scripts/create_azure_agents.py
```

This creates:
- RAG Agent - Document Q&A
- SQL Agent - Database queries
- Orchestrator Agent - Multi-agent coordination

---

## Step 7: Run the API Server

```bash
cd python/packages/api
python -m api.main
```

API runs on http://localhost:8000

---

## Step 8: Run the Frontend

```bash
cd ui/hil-workflow

# Install dependencies
npm install

# Configure local environment
cp .env.local.example .env.local
# Edit .env.local with API_URL=http://localhost:8000

# Start development server
npm run dev
```

UI runs on http://localhost:3000

---

## Verify Installation

### Test SQL Agent

```bash
python scripts/test_sql_dialect.py
```

Expected output:
```
=== Dialect Instructions Test ===
duckdb: OK
postgresql: OK
sqlite: OK
mssql: OK
...
=== All Tests Passed ===
```

### Test RAG Pipeline

```bash
# Upload a test document via UI or API
curl -X POST http://localhost:8000/api/upload \
  -F "file=@test_document.pdf"

# Query the document
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "summarize the document"}'
```

---

## Project Structure

```
agent-framework/
├── python/packages/
│   ├── core/                           # Core agent framework
│   │   └── agent_framework/
│   │       ├── agents/                 # Agent implementations
│   │       │   ├── sql.py              # SQL Agent with dialect support
│   │       │   ├── structured_data_agent.py
│   │       │   └── rag_retrieval_agent.py
│   │       ├── data/
│   │       │   └── connectors.py       # Database connectors
│   │       └── tools/
│   │           └── local_sql_tools.py  # Local database tools
│   │
│   ├── azure-ai/                       # Azure integrations
│   │   └── agent_framework_azure_ai/
│   │       └── connectors/
│   │           └── azure_sql_connector.py
│   │
│   └── api/                            # Backend API
│       └── src/api/
│           └── azure_executor.py       # Workflow executor
│
├── azure-functions/                    # Serverless backend
│   ├── index_document/                 # Document indexing
│   ├── consult_rag/                    # RAG retrieval
│   ├── execute_azure_sql/              # SQL execution
│   └── shared_code/                    # Shared utilities
│       ├── rag.py                      # RAG pipeline
│       ├── sql.py                      # SQL tools
│       └── summarizer.py               # Azure AI Language
│
├── ui/hil-workflow/                    # React/Next.js frontend
│   └── app/
│       ├── builder/                    # Workflow builder
│       └── execute/                    # Execution monitoring
│
├── docs/                               # Documentation
│   ├── SQLAgent.md                     # SQL Agent guide
│   └── ARCHITECTURE.md                 # System design
│
└── scripts/                            # Utility scripts
    ├── create_search_index.py
    ├── create_azure_agents.py
    └── deploy_azure_functions.sh
```

---

## Scripts Reference

All scripts are in the `/scripts` directory. Run from project root.

### Setup & Deployment

| Script | Command | Purpose |
|--------|---------|---------|
| `create_search_index.py` | `python scripts/create_search_index.py` | Create Azure AI Search index |
| `create_azure_agents.py` | `python scripts/create_azure_agents.py` | Create/update Azure AI agents |
| `deploy_azure_functions.sh` | `./scripts/deploy_azure_functions.sh` | Deploy Azure Functions |
| `deploy_infrastructure.sh` | `./scripts/deploy_infrastructure.sh` | Deploy Azure resources |

### Running the Application

| Script | Command | Purpose |
|--------|---------|---------|
| `start_api.sh` | `./scripts/start_api.sh` | Start API server (port 8000) |
| `start_ui.sh` | `./scripts/start_ui.sh` | Start UI server (port 3000) |

**Or manually:**
```bash
# API
cd python/packages/api && python -m api.main

# UI
cd ui/hil-workflow && npm run dev
```

### Testing & Debugging

| Script | Command | Purpose |
|--------|---------|---------|
| `test_azure_connection.py` | `python scripts/test_azure_connection.py` | Test Azure connectivity |
| `test_azure_functions.py` | `python scripts/test_azure_functions.py` | Test deployed functions |
| `test_sql_dialect.py` | `python scripts/test_sql_dialect.py` | Test SQL dialect support |
| `test_evaluator.py` | `python scripts/test_evaluator.py` | Test SQL result evaluator |

### Agent Management

| Script | Command | Purpose |
|--------|---------|---------|
| `list_openai_assistants.py` | `python scripts/list_openai_assistants.py` | List Azure AI agents |
| `update_agent_tools.py` | `python scripts/update_agent_tools.py` | Update agent tools |
| `update_rag_agent.py` | `python scripts/update_rag_agent.py` | Update RAG agent |

---

## Sharing the Framework

To share this codebase with another user:

```bash
cd /home/crossfitdev

zip -r agent-framework.zip agent-framework \
  -x "agent-framework/venv/*" \
  -x "agent-framework/.venv/*" \
  -x "agent-framework/**/node_modules/*" \
  -x "agent-framework/**/.next/*" \
  -x "agent-framework/**/__pycache__/*" \
  -x "agent-framework/**/*.pyc" \
  -x "agent-framework/.env.azure" \
  -x "agent-framework/azure-functions/.venv/*" \
  -x "agent-framework/azure-functions/venv/*" \
  -x "*.db" \
  -x "*.duckdb" \
  -x "*.sqlite" \
  -x "*.sqlite3"
```

**What to share:**
- The zip file
- This Getting Started guide

**What the recipient needs:**
- Their own Azure subscription with required resources
- Copy `.env.azure.template` to `.env.azure` and fill in credentials

---

## Next Steps

1. **Upload Documents** - Index your knowledge base via the UI
2. **Create Workflows** - Build custom multi-agent workflows
3. **Configure Personas** - Define custom agent behaviors
4. **Connect Databases** - Add your SQL databases for querying

See [Architecture Overview](ARCHITECTURE.md) for system design details.
