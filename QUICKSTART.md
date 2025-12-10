# Quick Start Guide - Azure Tools Integration

Get started with Azure tools integration in 5 minutes.

## 🚀 Quick Start (5 Minutes)

### Step 1: Clone and Install (2 min)

```bash
# Clone the repository (if not already done)
cd agent-framework

# Install core package
cd python/packages/core
pip install -e .

# Install Azure package
cd ../azure-ai
pip install -e .

# Install Azure Functions dependencies
cd ../../../azure-functions
pip install -r requirements.txt
```

### Step 2: Configure Environment (1 min)

```bash
# Copy environment template
cp .env.azure .env.azure

# Edit with your Azure credentials
nano .env.azure
```

**Minimum required:**
```bash
AZURE_AI_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com/api/projects/yourproject
AZURE_OPENAI_ENDPOINT=https://your-openai.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_EMBED_DEPLOYMENT=text-embedding-3-small
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_INDEX=your-index
```

### Step 3: Test Local Tools (1 min)

```bash
# Test local SQL tools
python python/packages/core/examples/test_local_sql_tools.py
```

Expected output:
```
✓ Initialized with database: /data/test.db
✓ Database type: sqlite
[TEST 1] Listing tables...
{
  "success": true,
  "tables": ["customers"],
  ...
}
```

### Step 4: Deploy Azure Functions (Optional, 5-10 min)

```bash
# Login to Azure
az login

# Deploy
chmod +x scripts/deploy_azure_functions.sh
./scripts/deploy_azure_functions.sh
```

### Step 5: Run Example (1 min)

```bash
# Run complete example
python python/packages/core/examples/azure_sql_rag_example.py
```

## 📖 What You Get

After completing the quick start, you have:

✅ **Local SQL Tools** - Query `.db` and `.duckdb` files directly  
✅ **Tool Selection** - Automatic routing between local and cloud  
✅ **Azure Integration** - Ready to use Azure SQL and RAG  
✅ **Multi-Agent System** - All agents configured with tools  
✅ **Examples** - Working code you can customize  

## 🎯 Common Use Cases

### Use Case 1: Query Local Database

```python
from agent_framework.tools import LocalSQLTools

tools = LocalSQLTools("/path/to/database.db")
result = await tools.query_database("SELECT * FROM users LIMIT 10")
print(result)
```

### Use Case 2: Create Agent with Tools

```python
from agent_framework.azure import create_agent_with_tools

sql_agent = create_agent_with_tools(
    agents_client=project_client.agents,
    agent_id="your-agent-id",
    agent_name="sql_agent",
    data_sources=[db_datasource],
    azure_functions_url="https://yourapp.azurewebsites.net"
)

result = await sql_agent.run("What are the top customers?")
```

### Use Case 3: Multi-Agent Workflow

```python
from agent_framework.azure import create_multi_agent_system

agents = create_multi_agent_system(
    agents_client=project_client.agents,
    agent_configs=agent_configs,
    data_sources=data_sources,
    azure_functions_url=azure_functions_url
)

# Use different agents for different tasks
sql_result = await agents["sql_agent"].run("Query database")
rag_result = await agents["rag_agent"].run("Search documents")
```

## 🔍 Verify Installation

Run this verification script:

```python
# verify.py
import sys

def check_module(module_name, package_name=None):
    try:
        __import__(module_name)
        print(f"✓ {package_name or module_name}")
        return True
    except ImportError:
        print(f"✗ {package_name or module_name} - MISSING")
        return False

print("Checking dependencies...")
print("-" * 40)

all_ok = True
all_ok &= check_module("agent_framework.tools", "agent_framework (core)")
all_ok &= check_module("agent_framework.azure", "agent_framework (azure integration)")
all_ok &= check_module("agent_framework_azure_ai", "agent_framework_azure_ai")
all_ok &= check_module("azure.ai.projects", "azure-ai-projects")
all_ok &= check_module("azure.identity", "azure-identity")
all_ok &= check_module("httpx", "httpx")

print("-" * 40)
if all_ok:
    print("✓ All dependencies installed!")
else:
    print("✗ Some dependencies are missing")
    sys.exit(1)
```

Run:
```bash
python verify.py
```

## 📚 Next Steps

1. **Customize Data Sources** - Edit `data_sources` in examples to match your data
2. **Explore Tools** - Review `AZURE_TOOLS_README.md` for detailed documentation
3. **Build Workflows** - Create your own multi-agent workflows
4. **Deploy to Production** - Use managed identity and Key Vault

## 🆘 Need Help?

**Issue: Module not found errors**
```bash
# Solution: Ensure proper installation
pip install -e python/packages/core
pip install -e python/packages/azure-ai
```

**Issue: Azure authentication fails**
```bash
# Solution: Login to Azure
az login
az account set --subscription YOUR_SUBSCRIPTION_ID
```

**Issue: Function not found errors**
```bash
# Solution: Verify tool registration
# Check that tools are registered in ToolExecutor
# See examples/azure_sql_rag_example.py for reference
```

## 📞 Resources

- **Full Documentation**: `AZURE_TOOLS_README.md`
- **Implementation Guide**: `AzureToolsImplementation.md`
- **Architecture Guide**: `AzureCloudAdaptation.md`
- **Deployment Scripts**: `scripts/`
- **Examples**: `python/packages/core/examples/`

---

**You're all set!** 🎉

Start building your Azure multi-agent workflows!
