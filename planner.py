from typing import Optional, List
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.models.azure import AzureOpenAI
from pydantic import BaseModel, Field

from ..schema import WorkflowConfig, AgentConfig, DataSourceConfig, StepConfig

class PlannerAgent:
    def __init__(self, model_provider="openai", model_name="gpt-4o"):
        if model_provider == "azure_openai":
            self.model = AzureOpenAI(id=model_name)
        else:
            self.model = OpenAIChat(id=model_name)
            
        # --- Intent Analyst ---
        self.intent_analyst = Agent(
            name="IntentAnalyst",
            role="Requirements Engineer",
            instructions="""
            You are an expert Requirements Engineer.
            Your goal is to analyze the user's request and extract structured requirements.
            
            Analyze the request for:
            1. **Goal**: What is the primary objective?
            2. **Scope**: What are the boundaries?
            3. **Constraints**: Time, resources, specific tools?
            4. **Missing Info**: Is anything critical missing?
            
            Output a concise summary of these points.
            If critical info is missing, explicitly state what is needed.
            """,
            model=self.model,
            markdown=True,
        )

        # --- Plan Reviewer ---
        self.plan_reviewer = Agent(
            name="PlanReviewer",
            role="Senior Architect",
            instructions="""
            You are a Senior Workflow Architect.
            Your goal is to critique and validate a proposed Agentic Workflow.
            
            Check for:
            1. **Logical Flow**: Do steps follow a logical sequence?
            2. **Data Availability**: Do agents have access to the required data sources?
            3. **Tool Appropriateness**: Are the assigned tools suitable for the tasks?
            4. **Robustness**: Are there fallback mechanisms or clear instructions?
            
            If the plan is good, output "APPROVED".
            If there are issues, list them clearly and suggest specific fixes.
            """,
            model=self.model,
            markdown=True,
        )

        self.agent = Agent(
            name="Planner",
            role="Workflow Architect",
            instructions="""
            You are an expert AI Workflow Architect.
            Your goal is to design a detailed Agentic Workflow based on the user's request.
            
            You must output a valid JSON object matching the WorkflowConfig schema.
            
            Guidelines:
            1. **Analyze Intent:** Understand the user's goal, roles, and desired workflow from their description.
            2. **Infer Agents:** Design agents based on the specific responsibilities mentioned.
               - **CRITICAL:** You MUST set the `id` field for each agent in the `agents` list.
               - Do NOT let the system generate a UUID. Use a simple string key.
               - Example: `{"id": "agent_analyst", "name": "Senior Analyst", ...}`
            3. **Data Sources:**
               - Use ONLY the data sources explicitly mentioned or provided by the user.
               - **Single Database Rule:** If the user provides ONE database file (e.g., "tdn_op.db"), assume ALL database data (actuals, plans, capacity) comes from this SINGLE source. Do NOT create separate data sources for each table/concept.
               - **Database Files:** Set `connection_string` to `sqlite:///filename.db`.
               - **Document Files:** If the user mentions files (PDF, Markdown, Text, etc.), set `type` to "file" and `path` to the filename.
               - **CRITICAL:** Do NOT create placeholder paths (e.g., "schema_registry_file_path"). Only use files explicitly named by the user or found in the request. If no file is mentioned, do not add a file data source.
            5. **Define Steps:**
               - Create a logical sequence of steps.
               - **CRITICAL:** Use the EXACT `agent_id` defined in the Agents section.
               - **Context Chaining:** For every step after the first one, you MUST include the output of the previous step in the `input_template`.
                 - Example: If Step 1 has `output_key="analysis_result"`, Step 2's template MUST be: "Using the findings from {analysis_result}, generate a report..."
               - **Action-Oriented Prompts:** The `input_template` for each step MUST be an imperative command telling the agent to EXECUTE tools immediately.
                 - For Database: "Run SQL queries to..."
                 - For Files/Knowledge: "Use the `search_knowledge_base` tool to search for..."
               - **Constraint Propagation (CRITICAL):**
                 - You MUST explicitly include ALL extracted constraints and context in the `input_template` of the relevant steps.
                 - Do NOT assume the agent knows the global context. Pass specific instructions (e.g., time references, filters) directly in the step template.
                 - If the user specified a logic (e.g., "relative to X"), that logic MUST be present in the step instruction.
            5. **Clarification:**
               - If the request is too vague (e.g., "Build an agent"), create a default "General Assistant" workflow but include a description noting that more details are needed.
            6. **Agent Instructions & Rich Outputs:**
               - **CRITICAL:** You MUST instruct ALL agents to use the `StepOutput` schema for their responses.
               - Add this instruction to EVERY agent:
                 "You MUST format your response using the `StepOutput` schema.
                  - `thought_process`: Explain your reasoning.
                  - `content`: Your main answer in Markdown.
                  - `metrics`: Key numbers (e.g., {'rows_processed': 100}).
                  - `visualizations`: Structured data for charts if applicable.
                  - `insights`: List of key technical findings."
               - For agents interacting with databases, explicitly add this instruction: 
                 "Always inspect the database schema (list tables and columns) BEFORE generating any SQL queries. Do not assume column names exist.
                 Limit your query results to 50 rows to avoid context overflow."
            7. **Tools & Knowledge:**
               - **CRITICAL:** Do NOT add "knowledge_retrieval", "rag", or "search_tool" to the `tools` list.
               - If `data_sources` contains files, the agent AUTOMATICALLY gets knowledge retrieval capabilities. Leave `tools` empty unless specific external tools (like `duckduckgo`) are needed.
            8. **Global Analysis & Summarization:**
               - **Summarization**: Use **Smart Summarization**. Instruct the agent to:
                 1. Call `get_document_outline` to see the structure.
                 2. Call `read_document_section` for relevant sections.
                 3. Summarize the content.
               - **Specific Questions**: Use `search_knowledge_base` (RAG).
            9. **External Tools (MCP):**
               - If the user asks to use an external tool (e.g., "weather server", "database tool") and provides a URL, create a **Data Source** for it.
               - **Format**:
                 `"data_sources": [{"name": "weather_mcp", "type": "mcp_server", "url": "http://localhost:8000/sse"}]`
               - **Assignment**:
                 Then, assign this Data Source ID to the Agent's `data_sources` list.
                 `"agents": [{"name": "Weather Agent", "data_sources": ["weather_mcp"], ...}]`
            """,
            model=self.model,
            output_schema=WorkflowConfig,
            markdown=True,
        )

    def create_plan(self, user_request: str) -> WorkflowConfig:
        print(f"--- Phase 1: Intent Analysis ---")
        intent_analysis = self.intent_analyst.run(f"Analyze this request: {user_request}")
        print(intent_analysis.content)
        
        print(f"--- Phase 2: Drafting Plan ---")
        response = self.agent.run(f"User Request: {user_request}\n\nRequirements Analysis:\n{intent_analysis.content}")
        plan = response.content
        
        print("--- Generated Plan (Draft) ---")
        # print(plan.model_dump_json(indent=2))
        
        # Self-Correction / Review Loop (Simplified for now)
        print(f"--- Phase 3: Plan Review ---")
        review = self.plan_reviewer.run(f"Review this workflow plan:\n{plan.model_dump_json()}")
        print(review.content)
        
        self._fix_ids(plan)
        self._fix_data_sources(plan, user_request)
        self._inject_db_instructions(plan)
        self._fix_model_config(plan)
        
        print("--- Fixed Plan ---")
        print(plan.model_dump_json(indent=2))
        
        return plan

    def _inject_db_instructions(self, plan: WorkflowConfig):
        # Detect DB type from data sources
        db_type = "sqlite" # Default
        for ds in plan.data_sources:
            if ds.type == "database" and ds.connection_string:
                if "duckdb" in ds.connection_string:
                    db_type = "duckdb"
                    break
                elif "postgresql" in ds.connection_string:
                    db_type = "postgresql"
                    break
        
        print(f"Fixing: Injecting instructions for DB type: {db_type}")
        
        instruction = ""
        if db_type == "sqlite":
            instruction = (
                "You are using **SQLite**. Use `strftime('%Y', col)` / `strftime('%m', col)` for date parts. "
                "Use `datetime('now','-2 months')` style for relative windows. Avoid `YEAR()`/`MONTH()`/`DATEADD()`."
            )
        elif db_type == "duckdb":
            instruction = (
                "You are using **DuckDB**. "
                "Use INTERVAL arithmetic, e.g., `ts >= now() - INTERVAL 2 MONTH` or `ts >= latest_ts - INTERVAL 2 MONTH`. "
                "Avoid `DATEADD`/`DATE_ADD`; prefer interval subtraction. "
                "For bucketing, use `date_trunc('month', ts)`; avoid window functions in WHERE—compute aggregates in a CTE and join."
            )
        elif db_type == "postgresql":
            instruction = (
                "You are using **PostgreSQL**. Use standard `INTERVAL` syntax (e.g., `ts >= now() - INTERVAL '2 months'`). "
                "Use `date_trunc` for time bucketing; avoid non-Postgres functions like `DATEADD`."
            )
            
        common_instruction = "Always inspect the database schema (list tables and columns) BEFORE generating any SQL queries. Do not assume column names exist. Limit your query results to 50 rows to avoid context overflow."
        
        # Rich Output Instruction
        rich_output_instruction = (
            "You MUST format your response as a VALID JSON object matching the `StepOutput` schema. "
            "Do NOT return Markdown text outside of the JSON object. "
            "Do NOT wrap the JSON in ` ```StepOutput ` blocks; use ` ```json ` or no blocks. "
            "Include `metrics` (e.g., row counts, query time) and `insights` (key findings) in your output. "
            "CRITICAL: If your result contains tabular data (e.g., from a SQL query), you MUST include the FULL table in the `content` field as a Markdown table. "
            "Do NOT just summarize the table; show the data. If the table is too large (over 50 rows), show the top 50 rows and mention the truncation."
        )

        full_instruction = f"{instruction} {common_instruction}\n\n{rich_output_instruction}"
        
        for agent in plan.agents:
            # Append to existing instructions
            if agent.instructions:
                if isinstance(agent.instructions, list):
                    agent.instructions.append(full_instruction)
                else:
                    agent.instructions += f"\n\n{full_instruction}"
            else:
                agent.instructions = full_instruction
        print(plan.model_dump_json(indent=2))
        
        return plan

    def _fix_model_config(self, plan: WorkflowConfig):
        import os
        # Check if we are in Azure mode
        if os.getenv("AZURE_OPENAI_API_KEY"):
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
            print(f"Fixing: Enforcing Azure OpenAI configuration (Deployment: {deployment})")
            
            for agent in plan.agents:
                agent.model_provider = "azure_openai"
                agent.model_name = deployment

    def _fix_data_sources(self, plan: WorkflowConfig, user_request: str):
        import re
        import os
        print(f"DEBUG: _fix_data_sources received request: {user_request}")
        
        # Improved regex to capture paths with slashes, dots, and hyphens
        # Matches: path/to/file.ext, ./file.ext, file.ext, and @[file.ext]
        path_pattern = r'(?:@\[)?([\w\-./\\]+\.(?:db|sqlite|duckdb|pdf|md|txt|json|csv|yml|yaml|graphml))(?:\])?'
        
        # Find all potential file references
        all_files = re.findall(path_pattern, user_request)
        print(f"DEBUG: Found potential files: {all_files}")
        
        db_files = [f for f in all_files if f.endswith(('.db', '.sqlite', '.duckdb'))]
        doc_files = [f for f in all_files if not f.endswith(('.db', '.sqlite', '.duckdb'))]
        
        # --- Fix Databases ---
        if db_files:
            # Heuristic: If only 1 DB file is mentioned, assume ALL database sources use it.
            target_db = db_files[0]
            is_duckdb = target_db.endswith(".duckdb") or "duckdb" in user_request.lower()
            
            connection_prefix = "duckdb:///" if is_duckdb else "sqlite:///"
            
            for ds in plan.data_sources:
                if ds.type == "database":
                    if len(db_files) == 1:
                         # Update connection string, but verify path first
                         final_path = self._resolve_file_path(target_db)
                         print(f"Fixing: Forcing connection string '{ds.connection_string}' to '{connection_prefix}{final_path}'")
                         ds.connection_string = f"{connection_prefix}{final_path}"
                    elif not ds.connection_string or "://" not in ds.connection_string:
                        final_path = self._resolve_file_path(target_db)
                        print(f"Fixing: Replacing invalid connection string '{ds.connection_string}' with '{connection_prefix}{final_path}'")
                        ds.connection_string = f"{connection_prefix}{final_path}"
        
        # --- Fix/Add Documents ---
        # If the plan missed some files mentioned in the prompt, add them.
        existing_paths = {ds.path for ds in plan.data_sources if ds.type == "file"}
        
        for doc in doc_files:
            if doc not in existing_paths:
                final_path = self._resolve_file_path(doc)
                if not final_path:
                    print(f"Warning: File '{doc}' not found. Skipping.")
                    continue
                    
                print(f"Fixing: Adding missing file data source '{final_path}'")
                plan.data_sources.append(DataSourceConfig(
                    id=f"file_{doc.replace('.', '_').replace('/', '_').replace('\\', '_')}",
                    name=f"File {os.path.basename(doc)}",
                    type="file",
                    path=final_path
                ))
                # Also ensure the agent has access to it
                for agent in plan.agents:
                    if not agent.data_sources:
                        agent.data_sources = []
                    ds_id = f"file_{doc.replace('.', '_').replace('/', '_').replace('\\', '_')}"
                    if ds_id not in agent.data_sources:
                        agent.data_sources.append(ds_id)

    def _resolve_file_path(self, filename: str) -> Optional[str]:
        """
        Tries to find the file. 
        1. Checks exact path.
        2. Checks current directory.
        3. Returns corrected path or None if not found.
        """
        import os
        
        # 1. Check exact path
        if os.path.exists(filename):
            return filename
            
        # 2. Check basename in current directory
        basename = os.path.basename(filename)
        if os.path.exists(basename):
            print(f"Auto-Correction: Found '{basename}' in current directory (requested '{filename}')")
            return basename
            
        # 3. Check if it's a relative path from current dir
        abs_path = os.path.abspath(filename)
        if os.path.exists(abs_path):
             return filename # It was valid relative path
             
        return None # Not found

    def _fix_ids(self, plan: WorkflowConfig):
        # 1. Collect available agent IDs
        agent_ids = {a.id for a in plan.agents}
        
        # 2. Check steps
        for step in plan.steps:
            if step.type == "agent_call" and step.agent_id:
                if step.agent_id not in agent_ids:
                    print(f"Warning: Step {step.name} refers to missing agent {step.agent_id}")
                    
                    # Heuristic 1: If only 1 agent exists, use it.
                    if len(plan.agents) == 1:
                        print(f"Fixing: Mapping {step.agent_id} to {plan.agents[0].id}")
                        step.agent_id = plan.agents[0].id
                        continue
                        
                    # Heuristic 2: If agent_id looks like a name, try to match with agent name
                    # (Simple case-insensitive match)
                    for agent in plan.agents:
                        # Normalize strings (remove 'agent_', spaces, lowercase)
                        s_id = step.agent_id.lower().replace("agent_", "").replace("_", "")
                        a_id = agent.id.lower().replace("agent_", "").replace("_", "")
                        a_name = agent.name.lower().replace(" ", "")
                        
                        if s_id in a_id or s_id in a_name or a_id in s_id:
                             print(f"Fixing: Mapping {step.agent_id} to {agent.id}")
                             step.agent_id = agent.id
                             break
