# HIL Agentic Workflow Framework

A Human-in-the-Loop (HIL) multi-agent workflow framework built on [Microsoft Agent Framework](https://github.com/microsoft/agent-framework), extended with Azure AI Foundry integration.

## 🚀 Features

- **Multi-Agent Orchestration** - Coordinate multiple specialized agents
- **Human-in-the-Loop** - Approval gates, clarification requests, feedback integration
- **RAG Pipeline** - Azure AI Search with hybrid retrieval and reranking
- **SQL Agent** - Natural language to SQL with dialect-aware generation
- **Document Processing** - Azure Document Intelligence integration
- **Dynamic Workflows** - User-defined personas, prompts, and data sources

## 📦 Components

```
agent-framework/
├── python/packages/
│   ├── core/                    # Core agent framework
│   ├── azure-ai/                # Azure AI integrations
│   └── api/                     # Backend API server
├── azure-functions/             # Serverless backend (RAG, SQL, indexing)
├── ui/hil-workflow/             # React/Next.js frontend
├── framework/                   # High-level orchestration
└── docs/                        # Documentation
```

## 🏃 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_ORG/agent-framework.git
cd agent-framework

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: .\venv\Scripts\activate  # Windows

# Install packages
pip install -e python/packages/core
pip install -e python/packages/azure-ai
pip install -e python/packages/api
```

### 2. Configure Azure

```bash
cp .env.azure.template .env.azure
# Edit .env.azure with your Azure credentials
```

Required Azure resources:
- Azure OpenAI (GPT-4o, text-embedding-3-large)
- Azure AI Search
- Azure Storage Account
- Azure AI Foundry Project (for agents)

### 3. Deploy Azure Functions

```bash
./scripts/deploy_azure_functions.sh
```

### 4. Run the UI

```bash
cd ui/hil-workflow
npm install
npm run dev
```

Open http://localhost:3000

## 📖 Documentation

- [Getting Started Guide](docs/GETTING_STARTED.md) - Detailed setup
- [Architecture Overview](docs/ARCHITECTURE.md) - System design
- [SQL Agent Guide](docs/SQLAgent.md) - SQL query generation
- [Configuration Reference](docs/CONFIGURATION.md) - Environment variables

## 🔧 Key Agents

| Agent | Purpose |
|-------|---------|
| **RAG Agent** | Document retrieval with hybrid search |
| **SQL Agent** | Natural language to SQL queries |
| **Planner Agent** | Workflow step planning |
| **Orchestrator** | Multi-agent coordination |

## 💡 Example Usage

```python
from agent_framework.agents.sql import SQLAgent
from agent_framework.data.connectors import DuckDBConnector

# Create connector with auto-detected dialect
connector = DuckDBConnector("data.duckdb")
print(f"Dialect: {connector.dialect}")  # "duckdb"

# SQL Agent with dialect-aware prompts
sql_agent = SQLAgent(llm=my_llm)
result = await sql_agent.generate_and_execute(
    goal="What are the top 5 customers by revenue?",
    connector=connector,
)
print(result.sql)
print(result.rows)
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/my-feature`)
3. Commit changes (`git commit -am 'Add feature'`)
4. Push branch (`git push origin feature/my-feature`)
5. Open Pull Request

## 📄 License

This project extends Microsoft Agent Framework. See [LICENSE](LICENSE) for details.
