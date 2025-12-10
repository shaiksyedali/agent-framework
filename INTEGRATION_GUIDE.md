# Azure AI Foundry Integration Guide

## Current Status

✅ **You Have:**
- Azure AI Foundry Project: `pi12`
- Project Endpoint: `https://pi12-resource.services.ai.azure.com/api/projects/pi12`
- Azure OpenAI Deployment: `gpt-4o`
- Azure AI Search: `https://datasearchpi12.search.windows.net`
- Embeddings Model: `text-embedding-3-small`
- API Key: Available

✅ **What's Configured:**
- `.env.azure` with all your endpoints
- Agent creation script ready (`scripts/create_azure_agents.py`)
- Test connection script ready (`scripts/test_azure_connection.py`)
- All 6 agent definitions prepared

## Authentication Issue

**Problem:** Azure AI Agents API requires OAuth tokens, not API keys.

**Error:**
```
Unauthorized. Access token is missing, invalid, audience is incorrect (https://ai.azure.com), or have expired.
```

**Solution:** You need to authenticate with Azure using one of these methods:

---

## Option 1: Azure CLI Authentication (Recommended for Development)

### Install Azure CLI

```bash
# Ubuntu/Debian/WSL
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Or manually download
wget https://aka.ms/installazureclilinux
bash installazureclilinux
```

### Login and Configure

```bash
# Login to Azure
az login

# Set your subscription
az account set --subscription "27ee6def-fabd-4f7e-9c13-8b5bdcce23e4"

# Verify
az account show
```

### Create Agents

```bash
# Activate virtual environment
source venv/bin/activate

# Test connection
python scripts/test_azure_connection.py

# Create all 6 agents
python scripts/create_azure_agents.py
```

---

## Option 2: Service Principal Authentication (For CI/CD)

### Create Service Principal

```bash
az ad sp create-for-rbac \
  --name "pi12-agents-sp" \
  --role "Cognitive Services User" \
  --scopes "/subscriptions/27ee6def-fabd-4f7e-9c13-8b5bdcce23e4/resourceGroups/rg-divt-pi12emob-dev-westeurope"
```

This will output:
```json
{
  "appId": "<AZURE_CLIENT_ID>",
  "password": "<AZURE_CLIENT_SECRET>",
  "tenant": "<AZURE_TENANT_ID>"
}
```

### Configure Environment Variables

Add to `.env.azure`:
```bash
AZURE_CLIENT_ID=<appId from above>
AZURE_CLIENT_SECRET=<password from above>
AZURE_TENANT_ID=<tenant from above>
```

### Create Agents

```bash
source venv/bin/activate
python scripts/create_azure_agents.py
```

---

## Option 3: Use Azure Portal (Manual)

You can also create agents manually through the Azure AI Foundry portal:

1. Go to https://ai.azure.com/
2. Navigate to your project `pi12`
3. Go to "Agents" section
4. Click "Create agent" for each:
   - supervisor_agent
   - planner_agent
   - executor_agent
   - sql_agent
   - rag_agent
   - response_generator

Then save the agent IDs to `azure_agents_config.json`:
```json
{
  "created_at": "2025-12-03",
  "project_endpoint": "https://pi12-resource.services.ai.azure.com/api/projects/pi12",
  "model": "gpt-4o",
  "agents": {
    "supervisor": {"id": "asst_xxx", "name": "supervisor_agent"},
    "planner": {"id": "asst_yyy", "name": "planner_agent"},
    "executor": {"id": "asst_zzz", "name": "executor_agent"},
    "sql_agent": {"id": "asst_aaa", "name": "sql_agent"},
    "rag_agent": {"id": "asst_bbb", "name": "rag_agent"},
    "response_generator": {"id": "asst_ccc", "name": "response_generator"}
  }
}
```

---

## Quick Decision Matrix

| Method | Best For | Setup Time | Pros | Cons |
|--------|----------|------------|------|------|
| **Azure CLI** | Development | 5 min | Easy, local dev-friendly | Need to re-login periodically |
| **Service Principal** | CI/CD, Production | 10 min | Automated, no manual login | Need to manage secrets |
| **Manual Portal** | One-time setup | 30 min | No SDK needed | Tedious for updates |

---

## Next Steps After Authentication

Once authentication is working:

### 1. Create Agents

```bash
source venv/bin/activate
python scripts/create_azure_agents.py
```

This creates all 6 agents and saves config to `azure_agents_config.json`.

### 2. Test with Examples

```bash
# Simple SQL query example
python examples/azure_simple_sql_example.py

# Streaming responses
python examples/azure_streaming_example.py

# Full workflow with mixed data sources
python examples/azure_foundry_workflow_example.py
```

### 3. Optional: Upload Documentation for RAG

```python
from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential

credential = DefaultAzureCredential()
client = AgentsClient(
    endpoint="https://pi12-resource.services.ai.azure.com/api/projects/pi12",
    credential=credential
)

# Upload schema documentation
file = await client.upload_file("schema_docs.pdf", purpose="assistants")

# Create vector store
vector_store = await client.create_vector_store(
    name="schema_docs",
    file_ids=[file.id]
)

# Update RAG agent (get ID from azure_agents_config.json)
await client.update_agent(
    agent_id="<rag_agent_id>",
    tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}}
)
```

---

## Troubleshooting

### "az: command not found"
Azure CLI not installed. See Option 1 above.

### "No subscriptions found"
Run: `az login` and select your subscription.

### "Insufficient permissions"
You need "Cognitive Services User" role on the Azure AI project.
Ask your Azure admin to grant permissions, or run:
```bash
az role assignment create \
  --assignee <your-email@domain.com> \
  --role "Cognitive Services User" \
  --scope "/subscriptions/27ee6def-fabd-4f7e-9c13-8b5bdcce23e4/resourceGroups/rg-divt-pi12emob-dev-westeurope"
```

### "Model deployment not found"
Verify your model deployment name in Azure AI Foundry portal matches `AZURE_OPENAI_DEPLOYMENT=gpt-4o` in `.env.azure`.

---

## Architecture Overview

Once agents are created, your system will look like this:

```
┌─────────────────────────────────────────────────────────┐
│         Azure AI Foundry Project (pi12)                 │
│  ┌────────────────────────────────────────────────────┐ │
│  │   Supervisor Agent (orchestration)                 │ │
│  │        ↓                                            │ │
│  │   Planner Agent (workflow planning)                │ │
│  │        ↓                                            │ │
│  │   Executor Agent (step execution)                  │ │
│  │        ↓          ↓                                 │ │
│  │   SQL Agent    RAG Agent                           │ │
│  │        ↓          ↓                                 │ │
│  │   Response Generator Agent                         │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                    ↓           ↓
        ┌───────────┘           └──────────────┐
        ↓                                       ↓
┌──────────────────┐                 ┌────────────────────┐
│  Azure SQL       │                 │  Azure AI Search   │
│  (if configured) │                 │  (for RAG)         │
└──────────────────┘                 └────────────────────┘
        ↓
┌──────────────────┐
│  Local SQLite    │
│  (for testing)   │
└──────────────────┘
```

---

## Need Help?

1. Check Azure AI Foundry portal: https://ai.azure.com/
2. View agent logs in Application Insights (if configured)
3. Review README_AZURE_FOUNDRY.md for detailed documentation
4. Check Azure service health: https://status.azure.com/

