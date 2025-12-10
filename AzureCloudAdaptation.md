# Azure Cloud-Based Agentic Framework - Architecture & Implementation Plan

## Executive Summary

This document analyzes the existing local agentic framework and proposes a cloud-based adaptation using Azure AI Foundry (formerly Azure AI Studio) agents, Azure Functions, and cloud-native tools. The goal is to maintain the same user experience while leveraging Azure's scalability, security, and managed services.

---

## Part 1: Existing Architecture Analysis

### System Overview

The current system is a **local-first** agentic framework built with:
- **Backend**: FastAPI (Python)
- **Frontend**: Next.js 14 (React with TypeScript)
- **Agent Library**: `agno` (local open-source framework)
- **Tools**: Local SQL, Knowledge Base (ChromaDB/LanceDB), MCP servers
- **Execution**: Synchronous step-by-step orchestration with HIL support

### Core Components

#### 1. Data Models (`framework/schema.py`)

```
DataSourceConfig
├── type: "database" | "file" | "mcp_server" | "url"
├── connection_string (for databases)
├── path (for files)
└── url (for MCP/web)

AgentConfig
├── name, role, instructions
├── model_provider, model_name
├── tools[] (tool names like "duckduckgo", "yfinance")
├── data_sources[] (IDs of DataSourceConfig)
└── mcp_servers[] (MCP server configurations)

WorkflowConfig
├── name, description, user_intent
├── agents[]
├── teams[] (groups of agents with optional leader)
├── data_sources[]
└── steps[] (sequence of agent_call, team_call, tool_call, user_confirmation)

JobStatus
├── workflow_id
├── status: "pending" | "running" | "completed" | "failed" | "waiting_for_user"
├── current_step_index
├── context{} (execution context with variables)
├── logs[]
└── hil_mode (Human-in-the-Loop flag)

StepOutput (Rich structured output)
├── thought_process (reasoning)
├── content (markdown response)
├── metrics{} (KPIs like row counts)
├── visualizations[] (chart data)
└── insights[] (bullet points)
```

#### 2. Workflow Builder (`framework/builder.py`)

**Key Responsibilities:**
- Loads tools dynamically (duckduckgo, yfinance, calculator, wikipedia, python, shell)
- Loads MCP tools (stdio or HTTP/SSE)
- Builds agents with model, tools, and knowledge base
- Creates knowledge base from files using vector DB (ChromaDB) + embeddings
- Creates SQL tools from database connections
- Builds teams from agent collections
- Returns executable workflow object

**Tool Loading Logic:**
```
File Data Source (.pdf, .md, .txt)
→ Create Knowledge Base
→ Vector DB (ChromaDB) with embeddings
→ Agent gets knowledge.add_content(path)
→ Auto-adds search_knowledge_base tool

Database Data Source
→ SQLStrategyTool(db_url, model, knowledge)
→ Combines schema inspection + RAG context + query generation

MCP Server Data Source
→ MCPTools(server_url or stdio params)
→ Agent can call MCP server tools
```

#### 3. Orchestrator (`framework/agents/orchestrator.py`)

**Execution Flow:**
```
1. start_workflow(workflow_id, input_data, hil_mode=True)
   └── Create JobStatus
   └── Call _execute_job()

2. _execute_job(job, config)
   └── Build agents from config
   └── Loop through steps:
       ├── agent_call: Run agent, parse StepOutput
       ├── team_call: Run team, parse output
       ├── tool_call: Execute tool
       └── user_confirmation: Pause for input
   └── HIL Check: If hil_mode=True, pause after EVERY step
   └── Store results in job.context
   └── Update job.status

3. resume_workflow(job_id, user_input)
   └── Load job
   └── If user provided feedback: Retry current step
   └── If user approved (empty input): Move to next step
   └── Continue _execute_job() from current_step_index
```

**HIL (Human-in-the-Loop) Mechanism:**
- After every step, if `hil_mode=True`, status → "waiting_for_user"
- Frontend polls job status, displays step output
- User can:
  - Approve (empty input) → Proceeds to next step
  - Provide feedback (text) → Retries current step with feedback injected
  - Cancel → Stops workflow
- Special case: Agent outputs "QUESTION:" → Always pauses for user response

#### 4. Planner Agent (`framework/agents/planner.py`)

**3-Phase Planning:**
```
Phase 1: Intent Analysis
└── IntentAnalyst agent extracts goal, scope, constraints, missing info

Phase 2: Plan Drafting
└── Planner agent generates WorkflowConfig JSON
└── Uses structured output (output_schema=WorkflowConfig)

Phase 3: Plan Review
└── PlanReviewer agent validates logical flow, data availability, tool appropriateness
```

**Post-Processing:**
- `_fix_ids()`: Ensure agent IDs are set
- `_fix_data_sources()`: Validate data source references
- `_inject_db_instructions()`: Add DB-specific SQL syntax instructions (SQLite/DuckDB/PostgreSQL)
- `_fix_model_config()`: Ensure model provider is set correctly

#### 5. API Layer (`framework/api.py`)

```
POST /plan
└── Generate workflow from user request using PlannerAgent

POST /workflows
└── Save workflow to registry

GET /workflows
└── List all workflows

GET /workflows/{id}
└── Get specific workflow

DELETE /workflows/{id}
└── Delete workflow

POST /execute
└── Start workflow execution (returns JobStatus)

POST /resume
└── Resume workflow after HIL gate

GET /jobs/{id}
└── Get job status (polled by frontend)

POST /chat
└── Chat with context of completed job (uses agents + knowledge)

GET /files
└── List files (file explorer)

POST /upload
└── Upload file
```

#### 6. Frontend (`frontend/`)

**Pages:**
- `/` - Dashboard: List workflows, edit/delete/run
- `/builder` - Workflow Builder: Create/edit workflows with tabs (Agents, Teams, Data Sources, Steps)
- `/execute` - Execution View: Timeline of steps, HIL approval, visualizations, chat

**Key Features:**
- **Auto-Plan with AI**: Calls `/plan` endpoint, generates workflow from user intent
- **File Explorer**: Browse local filesystem, select files for data sources
- **Form Validation**: React Hook Form + Zod schema
- **Real-time Polling**: React Query polling job status every 1s until complete/failed
- **Rich Output Display**: Metrics cards, collapsible thought process, markdown content, insights, visualizations
- **HIL UI**: When status="waiting_for_user", show approval buttons (Proceed/Provide Feedback)
- **Visualizations Tab**: Recharts for bar/pie/line/area charts
- **Chat Tab**: Chat with completed workflow context

---

## Part 2: Azure Cloud-Based Adaptation

### Architecture Comparison

| Component | Current (Local) | Azure Cloud-Based |
|-----------|-----------------|-------------------|
| **Agents** | `agno` library (local Python) | Azure AI Foundry Agents (cloud-hosted) |
| **Model** | OpenAI API or Azure OpenAI | Azure OpenAI (required for Foundry) |
| **Tools** | Local Python functions | Azure Functions (serverless) |
| **Knowledge Base** | ChromaDB/LanceDB (local) | Azure AI Search (cloud vector store) |
| **SQL Database** | SQLite/DuckDB (local files) | Azure SQL or connection strings |
| **MCP Servers** | stdio (local) or HTTP | HTTP/SSE (cloud URLs) |
| **Orchestration** | FastAPI backend (local) | FastAPI + Azure Agents SDK |
| **Execution** | Synchronous in Python process | Asynchronous via Azure agents |
| **Authentication** | API keys in .env | Managed Identity + Azure CLI |
| **Deployment** | Single machine | Distributed (Azure Functions + VM/Container) |

### Proposed Azure Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                           USER INTERFACE                               │
│  Next.js Frontend (Azure Static Web Apps or VM)                       │
│  - Workflow Builder                                                    │
│  - Execution Monitor                                                   │
│  - HIL Approval Gates                                                  │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │ HTTPS
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     BACKEND API (FastAPI)                              │
│  Azure VM or Container (Azure Container Apps)                         │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Endpoints:                                                       │ │
│  │ - POST /plan (Planner Agent)                                     │ │
│  │ - POST /workflows, GET /workflows                                │ │
│  │ - POST /execute (Start Azure agent workflow)                     │ │
│  │ - POST /resume (HIL resume)                                      │ │
│  │ - GET /jobs/{id} (Poll status)                                   │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Components:                                                      │ │
│  │ - WorkflowRegistry (Cosmos DB or Blob Storage)                   │ │
│  │ - AzureWorkflowBuilder (creates Azure Foundry agents)            │ │
│  │ - AzureOrchestrator (manages execution with Azure Agents SDK)    │ │
│  │ - PlannerAgent (generates workflows - can be local or Azure)     │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└────────────────────────┬───────────────────────────────────────────────┘
                         │ Azure Agents SDK
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 AZURE AI FOUNDRY PROJECT                               │
│  Project Endpoint: https://{resource}.services.ai.azure.com           │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ AGENTS (Cloud-hosted GPT-4o instances)                           │ │
│  │ - Supervisor Agent (orchestration)                               │ │
│  │ - Planner Agent (optional, can generate plans)                   │ │
│  │ - RAG Agent (searches Azure AI Search)                           │ │
│  │ - SQL Agent (queries Azure SQL)                                  │ │
│  │ - Response Generator                                             │ │
│  │ - Domain-specific agents (created dynamically)                   │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  Agent Configuration:                                                 │
│  - model: "gpt-4o"                                                    │
│  - instructions: "You are a {role}..."                                │
│  - tools: [function definitions for Azure Functions]                 │
│  - tool_resources: {code_interpreter, file_search} (optional)        │
└────────────────────────┬───────────────────────────────────────────────┘
                         │ Function Tool Calls
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    AZURE FUNCTIONS (TOOLS)                             │
│  Serverless Tool Execution                                            │
│                                                                        │
│  ┌─────────────────────┐  ┌─────────────────────┐                    │
│  │ consult_rag         │  │ execute_sql         │                    │
│  │ (HTTP Trigger)      │  │ (HTTP Trigger)      │                    │
│  ├─────────────────────┤  ├─────────────────────┤                    │
│  │ 1. Parse request    │  │ 1. Parse SQL query  │                    │
│  │ 2. Get Managed ID   │  │ 2. Get connection   │                    │
│  │ 3. Query AI Search  │  │    from Key Vault   │                    │
│  │ 4. Return docs      │  │ 3. Execute query    │                    │
│  └────────┬────────────┘  └────────┬────────────┘                    │
│           │                        │                                  │
│           ▼                        ▼                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐                    │
│  │ Azure AI Search     │  │ Azure SQL Database  │                    │
│  │ (Vector Store)      │  │ (Cloud SQL)         │                    │
│  └─────────────────────┘  └─────────────────────┘                    │
│                                                                        │
│  ┌─────────────────────┐  ┌─────────────────────┐                    │
│  │ call_mcp_server     │  │ read_blob_storage   │                    │
│  │ (HTTP Trigger)      │  │ (HTTP Trigger)      │                    │
│  └────────┬────────────┘  └────────┬────────────┘                    │
│           │                        │                                  │
│           ▼                        ▼                                  │
│  External MCP Server      Azure Blob Storage                          │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                      SUPPORTING SERVICES                               │
│                                                                        │
│  - Azure Key Vault (connection strings, secrets)                      │
│  - Cosmos DB or Blob Storage (workflow registry, job status)          │
│  - Application Insights (logging, monitoring)                         │
│  - Azure Monitor (alerts, dashboards)                                 │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Part 3: Implementation Mapping

### 1. Schema Translation

**No changes needed** - The existing Pydantic models work perfectly with Azure agents:
- `WorkflowConfig` → Same structure
- `AgentConfig` → Maps to Azure agent creation parameters
- `DataSourceConfig` → Determines tool selection (local vs cloud)
- `JobStatus` → Tracking execution state (store in Cosmos DB or Blob)
- `StepOutput` → Rich output format (compatible with Azure agent responses)

### 2. Workflow Builder Adaptation

```python
# framework/azure_builder.py

from azure.ai.agents.aio import AgentsClient
from azure.ai.agents.models import AsyncFunctionTool
from azure.identity.aio import DefaultAzureCredential
from .schema import WorkflowConfig, AgentConfig, DataSourceConfig

class AzureWorkflowBuilder:
    def __init__(self, project_endpoint: str):
        self.project_endpoint = project_endpoint
        self.agents_client = AgentsClient(
            endpoint=project_endpoint,
            credential=DefaultAzureCredential()
        )

    async def build_workflow(self, config: WorkflowConfig) -> dict:
        """
        Build workflow by creating Azure Foundry agents and tools
        Returns dict with agent_ids and tool_manifest
        """
        # 1. Analyze data sources and select tools
        tool_manifest = await self._analyze_data_sources(config.data_sources)

        # 2. Create or retrieve agents
        agent_ids = {}
        for agent_config in config.agents:
            agent_id = await self._create_or_get_agent(
                agent_config,
                tool_manifest
            )
            agent_ids[agent_config.id] = agent_id

        # 3. Register local tools (if any) with enable_auto_function_calls
        if tool_manifest.get("local_tools"):
            await self._register_local_tools(tool_manifest["local_tools"])

        return {
            "agent_ids": agent_ids,
            "tool_manifest": tool_manifest,
            "azure_agents_created": True
        }

    async def _analyze_data_sources(self, data_sources: list[DataSourceConfig]) -> dict:
        """
        Analyze data sources and decide tool deployment strategy
        Returns tool manifest with local/cloud tool definitions
        """
        manifest = {
            "local_tools": [],
            "cloud_tools": [],
            "data_source_map": {}
        }

        for ds in data_sources:
            if ds.type == "file":
                if ds.path and ds.path.endswith(".pdf"):
                    # Ingest to Azure AI Search
                    index_name = await self._ingest_to_azure_search(ds.path)
                    manifest["cloud_tools"].append({
                        "name": "consult_rag",
                        "type": "azure_function",
                        "url": f"{AZURE_FUNCTIONS_URL}/api/consult_rag",
                        "parameters": {
                            "index": index_name,
                            "query": "string",
                            "top_k": "int"
                        }
                    })
                elif ds.path and (ds.path.endswith(".db") or ds.path.endswith(".duckdb")):
                    # Local database - use local SQL tool
                    manifest["local_tools"].append({
                        "name": "execute_sql_query",
                        "function": self._create_local_sql_tool(ds.path)
                    })

            elif ds.type == "database" and ds.connection_string:
                if "azure" in ds.connection_string or "sqlserver" in ds.connection_string:
                    # Azure SQL - use cloud tool
                    manifest["cloud_tools"].append({
                        "name": "execute_azure_sql",
                        "type": "azure_function",
                        "url": f"{AZURE_FUNCTIONS_URL}/api/execute_sql"
                    })
                else:
                    # Other databases - use local tool
                    manifest["local_tools"].append({
                        "name": "execute_sql_query",
                        "function": self._create_local_sql_tool(ds.connection_string)
                    })

            elif ds.type == "mcp_server" and ds.url:
                # MCP server - use cloud tool
                manifest["cloud_tools"].append({
                    "name": "call_mcp_server",
                    "type": "azure_function",
                    "url": f"{AZURE_FUNCTIONS_URL}/api/call_mcp_server",
                    "mcp_url": ds.url
                })

        return manifest

    async def _create_or_get_agent(self, config: AgentConfig, tool_manifest: dict) -> str:
        """
        Create Azure Foundry agent or retrieve existing one
        Returns agent ID
        """
        # Check if agent already exists (by name or stored mapping)
        # If exists, return ID. Otherwise, create new.

        # Define tools for this agent based on data_sources
        agent_tools = []
        for ds_id in config.data_sources:
            # Find tools in manifest for this data source
            # Add tool definitions to agent_tools
            pass

        # Create agent in Azure
        agent = await self.agents_client.create_agent(
            model="gpt-4o",
            name=config.name,
            instructions=config.instructions,
            tools=agent_tools  # Function tool definitions
        )

        return agent.id

    async def _ingest_to_azure_search(self, file_path: str) -> str:
        """
        Ingest PDF to Azure AI Search
        Returns index name
        """
        # 1. Extract text from PDF (using PyPDF2 or similar)
        # 2. Generate embeddings (using Azure OpenAI Embeddings API)
        # 3. Create/update Azure AI Search index
        # 4. Upload documents with embeddings
        # 5. Return index name
        pass

    async def _register_local_tools(self, local_tools: list[dict]):
        """
        Register local tools with Azure Agents SDK
        Uses enable_auto_function_calls
        """
        tool_functions = set()
        for tool_def in local_tools:
            tool_functions.add(tool_def["function"])

        function_tool = AsyncFunctionTool(tool_functions)
        await self.agents_client.enable_auto_function_calls(
            function_tool,
            max_retry=10
        )
```

### 3. Orchestrator Adaptation

```python
# framework/azure_orchestrator.py

from azure.ai.agents.aio import AgentsClient
from azure.identity.aio import DefaultAzureCredential
from .schema import WorkflowConfig, JobStatus, StepConfig
from .azure_builder import AzureWorkflowBuilder

class AzureOrchestrator:
    def __init__(self, project_endpoint: str, registry):
        self.project_endpoint = project_endpoint
        self.agents_client = AgentsClient(
            endpoint=project_endpoint,
            credential=DefaultAzureCredential()
        )
        self.builder = AzureWorkflowBuilder(project_endpoint)
        self.registry = registry

    async def start_workflow(self, workflow_id: str, input_data: dict, hil_mode: bool = True) -> JobStatus:
        """
        Start workflow execution with Azure agents
        """
        workflow_config = self.registry.get_workflow(workflow_id)
        if not workflow_config:
            raise ValueError(f"Workflow {workflow_id} not found")

        # Build Azure agents and tools
        build_result = await self.builder.build_workflow(workflow_config)

        # Create job status
        job = JobStatus(
            workflow_id=workflow_id,
            status="running",
            context=input_data,
            logs=["Workflow started", f"Created {len(build_result['agent_ids'])} Azure agents"],
            hil_mode=hil_mode
        )
        self.registry.save_job(job)

        # Start execution
        await self._execute_job(job, workflow_config, build_result)
        return job

    async def resume_workflow(self, job_id: str, user_input: str) -> JobStatus:
        """
        Resume workflow after HIL gate
        Similar to current implementation
        """
        job = self.registry.get_job(job_id)
        if not job or job.status != "waiting_for_user":
            raise ValueError(f"Job {job_id} cannot be resumed")

        workflow_config = self.registry.get_workflow(job.workflow_id)

        # Handle user input (feedback or approval)
        if user_input.strip():
            # User provided feedback - retry current step
            job.logs.append(f"User feedback: {user_input}")
            job.context["user_feedback"] = user_input
        else:
            # User approved - move to next step
            job.logs.append("User approved step. Proceeding.")
            job.current_step_index += 1

        job.status = "running"
        self.registry.save_job(job)

        # Resume execution
        build_result = await self.builder.build_workflow(workflow_config)
        await self._execute_job(job, workflow_config, build_result)
        return job

    async def _execute_job(self, job: JobStatus, config: WorkflowConfig, build_result: dict):
        """
        Execute workflow steps using Azure agents
        """
        agent_ids = build_result["agent_ids"]

        try:
            while job.current_step_index < len(config.steps):
                step = config.steps[job.current_step_index]

                if step.type == "agent_call":
                    # Get Azure agent ID
                    agent_id = agent_ids.get(step.agent_id)
                    if not agent_id:
                        raise ValueError(f"Agent {step.agent_id} not found in build result")

                    # Format prompt
                    prompt = step.input_template.format(**job.context)

                    # Inject user feedback if exists
                    if "user_feedback" in job.context:
                        prompt += f"\n\n[USER FEEDBACK]: {job.context['user_feedback']}"
                        del job.context["user_feedback"]

                    job.logs.append(f"Executing step {step.name} with Azure agent {agent_id}")

                    # Run Azure agent
                    result = await self.agents_client.create_thread_and_process_run(
                        agent_id=agent_id,
                        thread={"messages": [{"role": "user", "content": prompt}]}
                    )

                    # Parse response
                    step_output = self._parse_azure_response(result)

                    # Store results
                    job.context[step.output_key] = step_output.content
                    if "step_outputs" not in job.context:
                        job.context["step_outputs"] = {}
                    job.context["step_outputs"][step.name] = step_output.model_dump()

                    job.logs.append(f"Step {step.name} completed")

                elif step.type == "user_confirmation":
                    # Pause for user confirmation
                    job.status = "waiting_for_user"
                    job.logs.append(f"Waiting for user confirmation: {step.message}")
                    self.registry.save_job(job)
                    return

                # HIL Check
                if job.hil_mode:
                    job.status = "waiting_for_user"
                    job.logs.append(f"Step {step.name} completed. Pausing for review.")
                    self.registry.save_job(job)
                    return

                # Move to next step
                job.current_step_index += 1
                self.registry.save_job(job)

            # Workflow complete
            job.status = "completed"
            job.logs.append("Workflow completed successfully")
            self.registry.save_job(job)

        except Exception as e:
            job.status = "failed"
            job.logs.append(f"Execution failed: {str(e)}")
            self.registry.save_job(job)

    def _parse_azure_response(self, result) -> StepOutput:
        """
        Parse Azure agent response into StepOutput format
        """
        from .schema import StepOutput
        import json

        # Azure agents return messages in result.messages
        # Last message is the agent's response
        if result.messages:
            last_message = result.messages[-1]
            content = last_message.content

            # Try to parse as JSON (if agent was instructed to output StepOutput)
            try:
                data = json.loads(content)
                return StepOutput(**data)
            except:
                # Fallback to plain text
                return StepOutput(
                    thought_process="Azure agent response",
                    content=content,
                    metrics={},
                    insights=[],
                    visualizations=[]
                )

        return StepOutput(
            thought_process="Empty response",
            content="No output from agent",
            metrics={},
            insights=[],
            visualizations=[]
        )
```

### 4. Planner Agent Adaptation

**Option A: Keep Local Planner (Recommended for Phase 1)**
- Use current `agno`-based PlannerAgent
- It generates WorkflowConfig which is compatible with Azure agents
- Faster iteration, no Azure agent creation needed for planning

**Option B: Azure-based Planner**
- Create a planner agent in Azure Foundry
- Configure with `output_schema=WorkflowConfig`
- Pro: Fully cloud-based
- Con: More complex to debug and iterate

**Recommended**: Start with Option A, migrate to Option B later if needed.

### 5. API Layer Updates

```python
# framework/azure_api.py

from fastapi import FastAPI
from .azure_orchestrator import AzureOrchestrator
from .registry import WorkflowRegistry
from .agents.planner import PlannerAgent  # Keep local planner
import os

app = FastAPI(title="Azure Agentic Framework API")

# Initialize components
project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
registry = WorkflowRegistry(storage_type="cosmos_db")  # or "blob_storage"
orchestrator = AzureOrchestrator(project_endpoint, registry)
planner = PlannerAgent(model_provider="azure_openai", model_name="gpt-4o")

# All endpoints remain the same!
# POST /plan → planner.create_plan()
# POST /workflows → registry.save_workflow()
# GET /workflows → registry.list_workflows()
# POST /execute → orchestrator.start_workflow()
# POST /resume → orchestrator.resume_workflow()
# GET /jobs/{id} → registry.get_job()
```

**Key Point**: The API layer remains **mostly unchanged**. Only the backend implementation (orchestrator + builder) is swapped.

### 6. Frontend Updates

**Minimal changes needed:**
- API endpoints remain the same
- UI components unchanged
- Only backend URL needs to point to Azure-hosted API

**Optional enhancements:**
- Show "Azure Agent ID" in agent cards
- Display "Cloud Tool" vs "Local Tool" badges in data sources
- Add Azure-specific monitoring links (Application Insights)

---

## Part 4: Data Source Intelligence & Tool Selection

### Decision Flow

```
User adds Data Source in Workflow Builder
│
├─ Type: "file"
│  ├─ Extension: .pdf, .docx, .md, .txt
│  │  ├─ Action: Ingest to Azure AI Search
│  │  ├─ Generate embeddings (text-embedding-3)
│  │  ├─ Create index: "{workflow_id}-documents"
│  │  └─ Tool: Cloud RAG (Azure Function: consult_rag)
│  │
│  ├─ Extension: .db, .duckdb
│  │  ├─ Action: Keep local (file too large for cloud ingestion)
│  │  └─ Tool: Local SQL (Python function: execute_sql_query)
│  │
│  └─ Extension: .csv
│     ├─ Action: Option A - Keep local (Local tool)
│     └─ Action: Option B - Ingest to Azure SQL (Cloud tool)
│
├─ Type: "database"
│  ├─ Connection String contains "azure" or "sqlserver"
│  │  ├─ Action: Use cloud connection
│  │  └─ Tool: Cloud SQL (Azure Function: execute_azure_sql)
│  │
│  └─ Connection String: other (PostgreSQL, MySQL, etc.)
│     ├─ Action: Check if internet-accessible
│     ├─ If YES: Tool: Cloud SQL (Azure Function with connection string)
│     └─ If NO: Tool: Local SQL (Python function)
│
├─ Type: "mcp_server"
│  ├─ URL provided
│  │  └─ Tool: Cloud MCP (Azure Function: call_mcp_server)
│  │
│  └─ Command provided (stdio)
│     └─ Tool: Local MCP (stdio subprocess) - NOT RECOMMENDED for cloud
│
└─ Type: "url"
   └─ Tool: Web Scraper (Azure Function: fetch_url)
```

### Tool Manifest Example

```json
{
  "workflow_id": "pi10-assistant-001",
  "data_sources": [
    {
      "id": "ds-pdf-001",
      "name": "PI10 Documentation",
      "type": "file",
      "path": "./documents/eDrivePredM.pdf",
      "preprocessing": {
        "action": "ingest_to_azure_search",
        "index_name": "pi10-documents",
        "documents_count": 245,
        "embedding_model": "text-embedding-3-large"
      }
    }
  ],
  "tools": [
    {
      "name": "consult_rag",
      "type": "cloud",
      "deployment": "azure_function",
      "url": "https://agent-tools.azurewebsites.net/api/consult_rag",
      "method": "POST",
      "parameters": {
        "query": {"type": "string", "required": true},
        "index": {"type": "string", "default": "pi10-documents"},
        "top_k": {"type": "integer", "default": 5}
      },
      "authentication": "managed_identity"
    }
  ],
  "agents": [
    {
      "id": "agent-rag-001",
      "name": "RAG Agent",
      "azure_agent_id": "asst_xyz123",
      "tools": ["consult_rag"],
      "data_sources": ["ds-pdf-001"]
    }
  ]
}
```

---

## Part 5: Implementation Phases

### Phase 1: Foundation (Week 1-2)

**Goals:**
- Set up Azure infrastructure
- Create proof-of-concept with single agent + single tool

**Tasks:**
1. Provision Azure Resources
   - Azure AI Foundry project
   - Azure OpenAI with gpt-4o + text-embedding-3 deployments
   - Azure AI Search (vector search enabled)
   - Azure Functions app
   - Azure Key Vault (for secrets)
   - Cosmos DB or Blob Storage (for workflow registry)

2. Create AzureWorkflowBuilder
   - Implement `_analyze_data_sources()`
   - Implement `_create_or_get_agent()` - basic version
   - Implement `_ingest_to_azure_search()` for PDFs

3. Create Azure Function: `consult_rag`
   - HTTP trigger
   - Accept: {query, index, top_k}
   - Use Managed Identity to access Azure AI Search
   - Return: [{id, title, content, score}]

4. Test End-to-End
   - Create simple workflow: "RAG Assistant"
   - 1 agent + 1 PDF data source
   - Execute via API, verify Azure agent calls Azure Function

### Phase 2: Core Tools & Orchestration (Week 3-4)

**Goals:**
- Implement all core tools (SQL, MCP)
- Complete orchestrator with HIL support
- Test multi-agent workflows

**Tasks:**
1. Create Azure Functions
   - `execute_azure_sql` (with Key Vault integration)
   - `call_mcp_server` (HTTP client)

2. Implement AzureOrchestrator
   - `start_workflow()` - builds agents, executes steps
   - `resume_workflow()` - HIL support
   - `_execute_job()` - step-by-step execution with Azure SDK

3. Update WorkflowRegistry
   - Store workflows in Cosmos DB
   - Store job status with polling support

4. Test Multi-Agent Workflow
   - Supervisor → SQL Agent → RAG Agent → Response Generator
   - Verify handoffs work correctly
   - Test HIL pause/resume

### Phase 3: Planner & Auto-Generation (Week 5)

**Goals:**
- Integrate PlannerAgent
- Enable auto-planning feature
- UI adjustments for Azure

**Tasks:**
1. Update PlannerAgent
   - Add Azure-specific instructions (e.g., "Use Azure AI Search for RAG")
   - Ensure generated workflows use correct tool types

2. API Testing
   - POST /plan → generates Azure-compatible workflow
   - POST /workflows → saves to Cosmos DB
   - POST /execute → runs on Azure agents

3. Frontend Updates
   - Connect to Azure-hosted backend
   - Test workflow builder
   - Test execution monitor with HIL

### Phase 4: Advanced Features (Week 6-7)

**Goals:**
- Teams support
- Local tools (for hybrid scenarios)
- Performance optimization

**Tasks:**
1. Teams Support
   - Implement multi-agent teams with Azure agents
   - Test team coordination

2. Hybrid Tools
   - Support for local SQL tools (when needed)
   - Use `enable_auto_function_calls()` for local tools

3. Monitoring & Logging
   - Application Insights integration
   - Workflow execution dashboards
   - Cost tracking

### Phase 5: Production Readiness (Week 8)

**Goals:**
- Security hardening
- Performance tuning
- Documentation

**Tasks:**
1. Security
   - Remove all API keys (use Managed Identity everywhere)
   - Add authentication to frontend (Azure AD)
   - RBAC for workflow access

2. Performance
   - Optimize Azure Function cold starts
   - Cache agent IDs (avoid recreation)
   - Batch Azure AI Search queries

3. Documentation
   - Deployment guide
   - API documentation
   - User guide updates

---

## Part 6: Key Differences & Migration Notes

### What Stays the Same

✅ **Frontend**: Minimal changes (just backend URL)
✅ **API Contracts**: All endpoints remain compatible
✅ **Data Models**: Pydantic schemas unchanged
✅ **Planner Agent**: Can keep local implementation (Phase 1)
✅ **Workflow Builder UI**: Same UX, same form fields
✅ **HIL Mechanism**: Pause/resume logic identical

### What Changes

🔄 **Agent Execution**: `agno` → Azure AI Agents SDK
🔄 **Tools**: Python functions → Azure Functions (for cloud data)
🔄 **Knowledge Base**: ChromaDB → Azure AI Search
🔄 **Storage**: Local files → Cosmos DB / Blob Storage
🔄 **Authentication**: API keys → Managed Identity

### Benefits of Azure Cloud Approach

1. **Scalability**: Auto-scaling agents and tools
2. **Security**: Managed Identity, no connection strings in code
3. **Performance**: 6-7x faster for cloud data (see UserGuide.md)
4. **High Availability**: Built-in redundancy
5. **Cost Optimization**: Pay per execution (serverless)
6. **Monitoring**: Application Insights, Azure Monitor
7. **Compliance**: Azure certifications (SOC 2, HIPAA, etc.)

### Challenges & Mitigations

| Challenge | Mitigation |
|-----------|------------|
| **Azure SDK Learning Curve** | Start with simple single-agent POC |
| **Cold Start Latency** | Premium plan for Functions, keep agents warm |
| **Debugging Complexity** | Application Insights, verbose logging |
| **Cost (if high usage)** | Use consumption plan, optimize queries |
| **Local Data Access** | Support hybrid mode with local tools |
| **Agent Limits** | Azure Foundry has quotas - request increase if needed |

---

## Part 7: Next Steps

### Immediate Actions

1. **Review this document** with team
2. **Provision Azure resources** (Phase 1 infrastructure)
3. **Clone existing repo** → Create `azure-cloud-branch`
4. **Start with POC**: Single agent + RAG tool (2-3 days)

### Decision Points

**Decision 1**: Planner Agent
- [ ] Keep local (faster iteration)
- [ ] Move to Azure (full cloud)
- **Recommendation**: Keep local for Phase 1

**Decision 2**: Workflow Registry Storage
- [ ] Cosmos DB (scalable, query-able)
- [ ] Blob Storage (cheaper, simpler)
- **Recommendation**: Cosmos DB for production

**Decision 3**: Frontend Hosting
- [ ] Azure Static Web Apps (CDN, auto SSL)
- [ ] Azure VM (more control)
- [ ] Azure Container Apps (Kubernetes-like)
- **Recommendation**: Azure Static Web Apps

**Decision 4**: Hybrid Mode Support
- [ ] Cloud-only (no local tools)
- [ ] Hybrid (support both)
- **Recommendation**: Hybrid (see UserGuide.md deployment patterns)

---

## Conclusion

The existing agentic framework provides an **excellent foundation** for Azure cloud migration. The architecture is well-designed with:
- Clean separation of concerns (schema, builder, orchestrator, API, UI)
- HIL support built-in
- Rich structured outputs
- Extensible tool system

**Migration Path**: The adaptation to Azure is **straightforward**:
1. Swap `agno` agents → Azure AI Agents SDK
2. Swap local tools → Azure Functions (where appropriate)
3. Swap ChromaDB → Azure AI Search
4. Keep everything else the same

**Timeline**: 8 weeks to production-ready system with all features.

**Risk**: Low - The existing code quality is high, and Azure SDK is well-documented.

**Recommendation**: Proceed with Phase 1 POC immediately. Success criteria: Single agent workflow executing on Azure within 1 week.
