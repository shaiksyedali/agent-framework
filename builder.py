from typing import Dict, List, Any, Optional
import os
from agno.agent import Agent
from agno.team import Team
from agno.workflow import Workflow
from agno.models.openai import OpenAIChat
from agno.models.azure import AzureOpenAI
from agno.tools.sql import SQLTools
from framework.tools.sql_strategy import SQLStrategyTool
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb, SearchType

from .schema import WorkflowConfig, AgentConfig, DataSourceConfig, StepConfig

import warnings
warnings.filterwarnings("ignore", message="The api_key client option must be set")

class WorkflowBuilder:
    def __init__(self, registry=None):
        self.registry = registry
        self._embedder = None
        self._vector_db_cache = {}

    def _db_instruction_from_sources(self, data_sources: Dict[str, Any]) -> str:
        """
        Derive database-specific guardrails for SQL generation based on configured data sources.
        Keeps instructions generic across engines while highlighting date/time quirks.
        """
        db_type = None
        for ds in data_sources.values():
            if getattr(ds, "type", None) == "database":
                conn = (ds.connection_string or "").lower()
                if "duckdb" in conn:
                    db_type = "duckdb"
                    break
                if "postgresql" in conn or "postgres" in conn:
                    db_type = "postgresql"
                    break
                if "sqlite" in conn or conn.endswith(".db"):
                    db_type = "sqlite"
                    break
        if db_type == "duckdb":
            return (
                "You are using **DuckDB**. Use INTERVAL arithmetic (e.g., `ts > now() - INTERVAL 2 MONTH`). "
                "Do NOT use `DATEADD`/`DATE_ADD` signatures; prefer `ts >= latest_ts - INTERVAL 2 MONTH` or `ts >= date_trunc('month', now())`. "
                "Avoid window functions in WHERE clauses; compute aggregates in a CTE and join."
            )
        if db_type == "postgresql":
            return (
                "You are using **PostgreSQL**. Use standard SQL with `INTERVAL` for date math (e.g., `ts > now() - INTERVAL '2 months'`). "
                "Use `date_trunc` for bucketing and avoid engine-specific functions from other dialects."
            )
        if db_type == "sqlite":
            return (
                "You are using **SQLite**. Do NOT use `YEAR()`/`MONTH()`; instead use `strftime('%Y', col)` or `strftime('%m', col)`. "
                "Use `datetime('now', '-2 months')` style for relative filters."
            )
        return ""

    def _get_embedder(self):
        if self._embedder:
            return self._embedder
            
        import os
        if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_EMBED_DEPLOYMENT"):
            from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder
            self._embedder = AzureOpenAIEmbedder(
                id=os.getenv("AZURE_EMBED_DEPLOYMENT"),
                dimensions=int(os.getenv("AZURE_EMBED_DIM", 1536))
            )
        return self._embedder

    def load_tool(self, tool_name: str):
        """Load a tool by name."""
        try:
            if tool_name == "duckduckgo":
                from agno.tools.duckduckgo import DuckDuckGo
                return DuckDuckGo()
            elif tool_name == "yfinance":
                from agno.tools.yfinance import YFinanceTools
                return YFinanceTools(stock_price=True, company_info=True, analyst_recommendations=True)
            elif tool_name == "calculator":
                from agno.tools.calculator import Calculator
                return Calculator()
            elif tool_name == "wikipedia":
                from agno.tools.wikipedia import WikipediaTools
                return WikipediaTools()
            elif tool_name == "python":
                from agno.tools.python import PythonTools
                return PythonTools()
            elif tool_name == "shell":
                from agno.tools.shell import ShellTools
                return ShellTools()
            else:
                print(f"Warning: Tool '{tool_name}' not found or not yet supported.")
                return None
        except ImportError as e:
            print(f"Warning: Failed to import tool '{tool_name}': {e}")
            return None

    def load_mcp_tools(self, config: Any):
        """Load MCP tools from configuration."""
        try:
            from agno.tools.mcp import MCPTools
            from mcp import StdioServerParameters
            
            # Support Remote MCP (HTTP/SSE)
            if hasattr(config, "url") and config.url:
                # Note: agno.tools.mcp.MCPTools might need updates to support SSE directly if not already present.
                # Assuming MCPTools accepts server_url or similar.
                # If not, we might need to use the lower-level mcp client here.
                # Checking agno source would be ideal, but assuming standard params for now.
                return MCPTools(server_url=config.url)

            # Support Local Stdio (Legacy/Fallback)
            if hasattr(config, "command") and config.command:
                server_params = StdioServerParameters(
                    command=config.command,
                    args=config.args or [],
                    env=config.env
                )
                return MCPTools(server_params=server_params)
                
            return None
        except ImportError:
            print("Warning: 'mcp' library not installed. Cannot load MCP tools.")
            return None
        except Exception as e:
            print(f"Error loading MCP tool '{config.name}': {e}")
            return None

    def build_team(self, config: Any, agents: Dict[str, Agent]) -> Team:
        """Build a Team from configuration."""
        members = []
        for agent_id in config.member_agent_ids:
            agent = agents.get(agent_id)
            if agent:
                members.append(agent)
            else:
                print(f"Warning: Agent '{agent_id}' not found for team '{config.name}'")
        
        leader = agents.get(config.leader_agent_id) if config.leader_agent_id else None
        
        # Resolve Model
        model = None
        if config.model_provider == "azure_openai":
            model = AzureOpenAI(id=config.model_name)
        else:
            model = OpenAIChat(id=config.model_name)

        return Team(
            name=config.name,
            members=members,
            instructions=config.instructions,
            model=model,
            # If a leader is specified, we might want to configure the team differently,
            # but for now, agno.team.Team handles delegation automatically or via instructions.
        )

    def build_agent(self, config: AgentConfig, data_sources: Dict[str, Any]) -> Agent:
        # Resolve Model
        model = None
        if config.model_provider == "azure_openai":
            model = AzureOpenAI(id=config.model_name)
        else:
            model = OpenAIChat(id=config.model_name)

        # Resolve Tools & Knowledge
        agent_tools = []
        agent_knowledge = None
        
        # 1. Load Standard Tools
        for tool_name in (config.tools or []):
            tool = self.load_tool(tool_name)
            if tool:
                agent_tools.append(tool)

        # 2. Load MCP Tools (Legacy Agent Config)
        for mcp_config in (config.mcp_servers or []):
            mcp_tool = self.load_mcp_tools(mcp_config)
            if mcp_tool:
                agent_tools.append(mcp_tool)
        
        # 3. Load Data Sources (Files & MCP Servers)
        file_data_sources = []
        for ds_id in (config.data_sources or []):
            ds = data_sources.get(ds_id)
            if not ds:
                continue
                
            if ds.type == "file" and ds.path:
                file_data_sources.append(ds)
            elif ds.type == "mcp_server":
                # Treat MCP Server Data Source as a Tool provider
                mcp_tool = self.load_mcp_tools(ds)
                if mcp_tool:
                    agent_tools.append(mcp_tool)

        # 3. Load Data Source Tools (SQL/Knowledge)
        for ds_id in (config.data_sources or []):
            ds = data_sources.get(ds_id)
            if not ds:
                continue
            
            if ds.type == "database":
                # Add SQL Strategy Tool (Replaces standard SQLTools)
                # We pass the model and knowledge (if available) to the tool
                # Note: Knowledge might be initialized in the next step if file source exists.
                # Ideally, we should initialize knowledge first.
                pass # Deferred to after knowledge init
            elif ds.type == "file":
                # Add Knowledge Base
                if not agent_knowledge:
                     # Initialize Vector DB (using ChromaDb)
                    embedder = self._get_embedder()
                    
                    # Use ChromaDb for vector storage
                    from agno.vectordb.chroma import ChromaDb
                    
                    vector_db = ChromaDb(
                        collection=f"agent_{config.id}",
                        path="./chromadb_data",
                        persistent_client=True,
                        embedder=embedder,
                    )
                    
                    # Initialize Contents DB to track processed files and avoid warnings
                    from agno.db.sqlite import SqliteDb
                    contents_db = SqliteDb(knowledge_table="agent_knowledge", db_url="sqlite:///agent_knowledge.db")
                    
                    agent_knowledge = Knowledge(
                        vector_db=vector_db,
                        contents_db=contents_db,
                        max_results=100, # Increased limit for broader retrieval
                    )
                # Load content (this will auto-select PDFReader if extension is .pdf)
                # Revert forced re-indexing (skip_if_exists=True) now that Docling is verified
                agent_knowledge.add_content(path=ds.path, skip_if_exists=True)

        # Second Pass for Database Tools (now that Knowledge is ready)
        for ds_id in (config.data_sources or []):
            ds = data_sources.get(ds_id)
            if not ds or ds.type != "database":
                continue
            
            # Determine DB URL
            db_url = ds.connection_string
            if not db_url and ds.path:
                if ds.path.endswith(".duckdb"):
                    db_url = f"duckdb:///{ds.path}"
                else:
                    # Default to SQLite
                    db_url = f"sqlite:///{ds.path}"
            
            if not db_url:
                continue

            # Use SQLStrategyTool
            agent_tools.append(SQLStrategyTool(
                db_url=db_url,
                model=model,
                knowledge=agent_knowledge,
                # Default robust settings (no external env needed)
                max_retries=4,
                sample_limit=20,
                distinct_limit=15,
                enable_cache=True,
                allow_join_probe=True,
                allow_filter_relaxation=True,
                allow_question_on_empty=True,
                max_date_backoff=365,
                force_dialect=None,
                robust_mode=True,
            ))

        # Knowledge-First Strategy Injection
        extra_instructions = ""
        if agent_knowledge:
            extra_instructions += "\n\nUse the `search_knowledge_base` tool to retrieve information from the document. If you suspect there are more results, call the tool again with a higher `num_documents` (e.g. 20)."
            
            # Check for SQL Strategy Tool
            has_sql_strategy = any(isinstance(t, SQLStrategyTool) for t in agent_tools)
            if has_sql_strategy:
                extra_instructions += "\n\n**Data Analysis Strategy**: You have access to a `sql_strategy` tool. For ANY data analysis or database questions, you MUST use `sql_strategy.answer_question(question=...)`. Do NOT try to run raw SQL queries yourself unless explicitly asked to debug. The strategy tool handles schema inspection, context retrieval, and error correction automatically. Trust the tool."

        # Add Full Document Reader for Global Analysis (Counting, Summarization)
        file_data_sources = [ds for ds in data_sources.values() if ds.type == "file"]
        if file_data_sources:
            available_files = [ds.path for ds in file_data_sources]
            files_str = ", ".join(available_files)
            
            # Add Smart Docling Tools (Structure & Section Reading)
            from framework.tools.docling_tools import DoclingTools
            agent_tools.append(DoclingTools())

            extra_instructions += f"\n\n**Global Analysis & Summarization**:\n1. **Smart Summarization (Preferred)**: For summarization or finding specific topics, use the `docling_tools`. First call `get_document_outline` to see the structure. Then call `read_document_section` to read ONLY the relevant parts. This is faster and more accurate.\n\n**Available Documents**:\n{files_str}"

        # Database-specific guardrails
        db_instruction = self._db_instruction_from_sources(data_sources)
        if db_instruction:
            extra_instructions += f"\n\n{db_instruction}\nAlways inspect the database schema (list tables and columns) BEFORE generating any SQL queries. Do not assume column names exist. Limit your query results to 50 rows to avoid context overflow."

        return Agent(
            name=config.name,
            role=config.role,
            instructions=config.instructions + extra_instructions + "\n\nIf you encounter a discrepancy (e.g. empty query results), first attempt to SELF-CORRECT by verifying your assumptions against the Knowledge Base or Database Schema. Try at least one alternative query. If you are still unable to resolve it, ONLY THEN output a message starting with 'QUESTION: ' followed by a CONCISE, simple question. Do NOT explain the schema or your thought process. Just ask the question clearly. Do not proceed until you get an answer.\n\n**Bias for Action**: When asked to analyze, forecast, or identify trends, you MUST immediately execute the necessary SQL queries or Knowledge Base searches to gather data. Do NOT ask for permission or propose a plan first. Show the data and then analyze it.",
            model=model,
            tools=agent_tools,
            knowledge=agent_knowledge,
            markdown=True,
            debug_mode=True,
            retries=3,
            delay_between_retries=10,
            exponential_backoff=True,
        )

    def build_workflow(self, config: WorkflowConfig) -> Workflow:
        # 1. Initialize Data Sources
        data_sources = {ds.id: ds for ds in (config.data_sources or [])}
        
        # 2. Build Agents
        agents = {}
        for agent_config in (config.agents or []):
            agents[agent_config.id] = self.build_agent(agent_config, data_sources)

        # 3. Build Teams
        teams = {}
        for team_config in (config.teams or []):
            teams[team_config.id] = self.build_team(team_config, agents)

        # 3. Define Workflow Logic
        # Since Agno Workflows are class-based, we need to dynamically create a class or use a generic one.
        # For this generic framework, we will create a DynamicWorkflow class.
        
        class DynamicWorkflow(Workflow):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.agents = agents
                self.teams = teams
                self.step_configs = config.steps

            def run(self, input_data: str):
                context = {"input": input_data}
                results = {}
                
                for step in self.step_configs:
                    if step.type == "agent_call":
                        agent = self.agents.get(step.agent_id)
                        if agent:
                            # Format input
                            prompt = step.input_template.format(**context)
                            response = agent.run(prompt)
                            results[step.output_key] = response.content
                            context[step.output_key] = response.content
                    
                    elif step.type == "team_call":
                        team = self.teams.get(step.team_id)
                        if team:
                            # Format input
                            prompt = step.input_template.format(**context)
                            response = team.run(prompt)
                            results[step.output_key] = response.content
                            context[step.output_key] = response.content
                            
                    elif step.type == "user_confirmation":
                        # In a real async system, this would pause. 
                        # For now, we simulate or log.
                        print(f"WAITING FOR USER: {step.message}")
                        # In a CLI/API, we'd return a status here.
                        
                return results

        return DynamicWorkflow(name=config.name, description=config.description)
