"""
Azure Workflow Executor - Hybrid HIL Orchestrator
REFACTORED: Implements "Local Orchestration" with "Cloud Agents" and "Cloud Tools".
- User -> Local Executor -> AI Foundry Agent
- AI Foundry Agent -> 'requires_action' -> Local Executor -> Azure Function (Cloud Tool)
"""

import asyncio
import json
import logging
import os
import httpx
import sqlite3
from typing import Any, Dict, List, Optional
from pathlib import Path

# Optional DuckDB support
try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    duckdb = None
    HAS_DUCKDB = False

from azure.identity.aio import DefaultAzureCredential
from azure.ai.agents.aio import AgentsClient

from .models import WorkflowConfig, JobStatus, StepConfig
from .db import db

# Lazy import for sql_evaluator to avoid import errors if not needed
_sql_evaluator = None

def _get_evaluator():
    """Lazy-load SQLResultEvaluator."""
    global _sql_evaluator
    if _sql_evaluator is None:
        try:
            from .sql_evaluator import SQLResultEvaluator
            _sql_evaluator = SQLResultEvaluator()
        except ImportError:
            pass
    return _sql_evaluator

logger = logging.getLogger(__name__)

class AzureWorkflowExecutor:
    """Executes workflows by orchestrating Azure AI Foundry Agents locally / Dispatching Tools"""

    def __init__(self):
        self.agents_config = self._load_agents_config()
        self.azure_functions_url = os.environ.get("AZURE_FUNCTIONS_URL")
        self.azure_functions_key = os.environ.get("AZURE_FUNCTIONS_KEY")
        
        # Initialize AI Foundry Client
        self.client = None
        self._credential = None
        
    async def upload_file(self, file_path: str) -> str:
        """Upload a file to Azure OpenAI for use by agents"""
        try:
            logger.info(f"Uploading file to Azure OpenAI: {file_path}")
            # Ensure path is absolute
            path_obj = Path(file_path)
            if not path_obj.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            # Check if file already exists in Azure (by name) to avoid duplicates?
            # For now, just upload.
            file = await self.client.files.create(
                file=open(path_obj, "rb"),
                purpose="assistants"
            )
            logger.info(f"File uploaded successfully. ID: {file.id}")
            return file.id
        except Exception as e:
            logger.error(f"Failed to upload file to Azure: {e}")
            raise

    async def _get_or_create_vector_store(self, name: str, file_ids: List[str]) -> Optional[str]:
        """
        Create a vector store for file_search.
        Note: Vector Stores API may not be available in all Azure OpenAI SDK versions.
        Falls back gracefully if not available.
        """
        try:
            # Try the vector_stores API if available
            if hasattr(self.client.beta, 'vector_stores'):
                vs = await self.client.beta.vector_stores.create(name=name)
                if file_ids:
                    await self.client.beta.vector_stores.file_batches.create_and_poll(
                        vector_store_id=vs.id,
                        file_ids=file_ids
                    )
                return vs.id
            else:
                logger.warning("Vector Stores API not available. Files will be attached directly to messages.")
                return None
        except Exception as e:
            logger.warning(f"Vector Store creation failed (will attach files directly): {e}")
            return None

    async def initialize(self):
        """Initialize Azure AI Foundry AgentsClient"""
        try:
            # Get AI Foundry project endpoint
            endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
            if not endpoint:
                endpoint = self.agents_config.get("project_endpoint")
            
            if not endpoint:
                logger.warning("AZURE_AI_PROJECT_ENDPOINT not set. execution may fail.")
                return

            # Use DefaultAzureCredential for AI Foundry
            self._credential = DefaultAzureCredential()
            self.client = AgentsClient(
                endpoint=endpoint,
                credential=self._credential
            )
            logger.info(f"AzureWorkflowExecutor initialized with AI Foundry AgentsClient")
            logger.info(f"Endpoint: {endpoint}")
            
        except Exception as e:
            logger.error(f"Failed to initialize AI Foundry client: {e}")

    async def cleanup(self):
        if self._credential:
            await self._credential.close()

    def _load_agents_config(self) -> Dict[str, Any]:
        """Load Azure agents configuration"""
        # Load from the correct location
        config_file = Path(__file__).parent.parent.parent.parent.parent.parent / "azure_agents_config.json"
        try:
            with open(config_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Could not load azure_agents_config.json: {e}")
            return {"agents": {}}
            
    # =========================================================================
    # TOOL DISPATCHER (Local vs Cloud Routing)
    # =========================================================================
    
    def _is_local_database(self, database: str, job: Optional[JobStatus] = None) -> bool:
        """Determine if database should be executed locally"""
        if not database:
            return False
        
        db_lower = database.lower()
        local_extensions = ['.db', '.duckdb', '.sqlite', '.sqlite3', '.csv']
        
        # Check file extension in database name
        if any(db_lower.endswith(ext) for ext in local_extensions):
            return True
        
        # Check keywords indicating local
        if 'local' in db_lower or 'file:' in db_lower:
            return True
        
        # Check if database matches a name in job's data sources (dict format)
        if job and job.context.get("database_paths"):
            db_paths = job.context["database_paths"]
            if isinstance(db_paths, dict):
                # Check by name
                if database in db_paths:
                    db_path = db_paths[database]
                    if any(db_path.lower().endswith(ext) for ext in local_extensions):
                        logger.info(f"Local DB detected by name '{database}': {db_path}")
                        return True
                # Check if ANY stored path is a local file
                for name, path in db_paths.items():
                    if any(path.lower().endswith(ext) for ext in local_extensions):
                        logger.info(f"Local DB detected from job context: {name} → {path}")
                        return True
            else:
                # Legacy list format support
                for db_path in db_paths:
                    if any(db_path.lower().endswith(ext) for ext in local_extensions):
                        logger.info(f"Local DB detected from job context: {db_path}")
                        return True
        
        return False
    
    def _resolve_database_path(self, database: str, job: Optional[JobStatus] = None) -> Optional[Path]:
        """Resolve database file path from job context or relative paths"""
        local_extensions = ['.db', '.duckdb', '.sqlite', '.sqlite3', '.csv']
        
        # Direct path (if database is already a valid path)
        db_path = Path(database)
        if db_path.exists():
            return db_path
        
        # Check job context for database paths (dict format: name → path)
        if job and job.context.get("database_paths"):
            db_paths = job.context["database_paths"]
            
            if isinstance(db_paths, dict):
                # First, try exact name match
                if database in db_paths:
                    path = Path(db_paths[database])
                    if path.exists():
                        logger.info(f"Resolved '{database}' to exact match: {path}")
                        return path
                
                # Second, try fuzzy match - database name might be substring of stored name
                db_lower = database.lower().replace(' ', '_').replace('-', '_')
                for name, stored_path in db_paths.items():
                    name_lower = name.lower().replace(' ', '_').replace('-', '_')
                    path_stem = Path(stored_path).stem.lower().replace(' ', '_').replace('-', '_')
                    
                    # Match if database is substring of name or path stem
                    if db_lower in name_lower or db_lower in path_stem or name_lower in db_lower or path_stem in db_lower:
                        path = Path(stored_path)
                        if path.exists():
                            logger.info(f"Resolved '{database}' to fuzzy match '{name}': {path}")
                            return path
                
                # Third, if still no match and database is a descriptive name (not a file path), use first local DB
                is_descriptive = not any(database.lower().endswith(ext) for ext in local_extensions)
                
                if is_descriptive:
                    for name, stored_path in db_paths.items():
                        stored_lower = stored_path.lower()
                        if any(stored_lower.endswith(ext) for ext in local_extensions):
                            path = Path(stored_path)
                            if path.exists():
                                logger.info(f"Resolved descriptive '{database}' to first local DB '{name}': {path}")
                                return path
            else:
                # Legacy list format support
                for stored_path in db_paths:
                    if database in stored_path or stored_path.endswith(database):
                        path = Path(stored_path)
                        if path.exists():
                            return path
        
        # Check common locations
        project_root = Path(__file__).parent.parent.parent.parent.parent.parent
        search_paths = [
            Path.cwd() / database,
            Path.cwd() / "data" / database,
            project_root / database,
            project_root / "data" / database,
            project_root / "ui" / "hil-workflow" / database,
        ]
        
        for path in search_paths:
            if path.exists():
                return path
        
        return None
    
    async def _execute_local_sql(self, query: str, database: str, job: Optional[JobStatus] = None) -> str:
        """Execute SQL on local file database (SQLite, DuckDB, or CSV via DuckDB)"""
        try:
            db_path = self._resolve_database_path(database, job)
            if not db_path:
                return json.dumps({
                    "success": False,
                    "error": f"Database file not found: {database}",
                    "searched_paths": "Check file exists and is accessible"
                })
            
            db_str = str(db_path)
            logger.info(f"Executing local SQL on: {db_str}")
            logger.info(f"Query: {query[:200]}...")
            
            # CSV files - use DuckDB with read_csv_auto
            if db_str.lower().endswith('.csv'):
                if not HAS_DUCKDB:
                    return json.dumps({
                        "success": False,
                        "error": "DuckDB not installed. Run: pip install duckdb (required for CSV queries)"
                    })
                
                # Create in-memory DuckDB connection
                conn = duckdb.connect(':memory:')
                
                # Load ALL CSVs from job context so JOINs work across tables
                loaded_tables = []
                if job and job.context.get("database_paths"):
                    for db_name, csv_path in job.context["database_paths"].items():
                        if csv_path.lower().endswith('.csv'):
                            csv_path_esc = csv_path.replace("'", "''")
                            # Create view with normalized table name (lowercase, underscores)
                            csv_table_name = Path(csv_path).stem.lower().replace(' ', '_').replace('-', '_')
                            try:
                                conn.execute(f"CREATE VIEW {csv_table_name} AS SELECT * FROM read_csv_auto('{csv_path_esc}')")
                                loaded_tables.append(csv_table_name)
                            except Exception as e:
                                logger.warning(f"Failed to load CSV {csv_path}: {e}")
                
                logger.info(f"Loaded {len(loaded_tables)} CSV tables: {loaded_tables}")
                
                # Also create 'data' view pointing to the primary CSV as fallback
                primary_table_name = db_path.stem.lower().replace(' ', '_').replace('-', '_')
                csv_path_escaped = db_str.replace("'", "''")
                if primary_table_name not in loaded_tables:
                    conn.execute(f"CREATE VIEW {primary_table_name} AS SELECT * FROM read_csv_auto('{csv_path_escaped}')")
                    loaded_tables.append(primary_table_name)
                conn.execute(f"CREATE VIEW data AS SELECT * FROM read_csv_auto('{csv_path_escaped}')")
                
                # Execute the query - with retry loop for multiple table name fixes
                import re
                current_query = query
                max_retries = 10  # Prevent infinite loops
                
                for retry in range(max_retries):
                    try:
                        result = conn.execute(current_query).fetchdf()
                        break  # Success!
                    except duckdb.CatalogException as e:
                        # Table not found - try to fix table name references
                        if "Catalog Error" not in str(e):
                            raise
                        
                        error_str = str(e)
                        logger.info(f"[Retry {retry+1}] Table not found: {error_str[:150]}...")
                        
                        # Extract the missing table name from error message
                        missing_table_match = re.search(r'(?:Table|View) with name "?([^"]+)"? does not exist', error_str)
                        if not missing_table_match:
                            missing_table_match = re.search(r'(?:Table|View) with name (\S+) does not exist', error_str)
                        missing_table = missing_table_match.group(1).strip() if missing_table_match else None
                        
                        if not missing_table:
                            raise
                        
                        # Normalize the missing table name for comparison
                        normalized_missing = missing_table.lower().replace(' ', '_').replace('-', '_')
                        
                        # Find matching loaded table
                        similar = [t for t in loaded_tables if normalized_missing in t or t in normalized_missing]
                        replacement_table = similar[0] if similar else primary_table_name
                        
                        if not similar:
                            logger.warning(f"No similar table for '{missing_table}', using primary: {primary_table_name}")
                        
                        # Replace references to missing table
                        for pattern in [f'FROM\\s+"{re.escape(missing_table)}"', f'FROM\\s+{re.escape(missing_table)}\\b',
                                       f'JOIN\\s+"{re.escape(missing_table)}"', f'JOIN\\s+{re.escape(missing_table)}\\b']:
                            current_query = re.sub(pattern, f'FROM {replacement_table}', current_query, flags=re.IGNORECASE)
                        
                        logger.info(f"Replaced '{missing_table}' with '{replacement_table}'")
                else:
                    # Max retries exceeded
                    raise Exception(f"Failed to fix query after {max_retries} retries")
                
                conn.close()
                rows = result.to_dict('records')
                columns = list(result.columns)
            
            # DuckDB files
            elif db_str.endswith('.duckdb'):
                if not HAS_DUCKDB:
                    return json.dumps({
                        "success": False,
                        "error": "DuckDB not installed. Run: pip install duckdb"
                    })
                conn = duckdb.connect(db_str, read_only=True)
                result = conn.execute(query).fetchdf()
                conn.close()
                rows = result.to_dict('records')
                columns = list(result.columns)
            
            # SQLite
            else:
                conn = sqlite3.connect(db_str)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query)
                
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    rows = [dict(row) for row in cursor.fetchall()]
                else:
                    columns = []
                    rows = []
                    conn.commit()
                
                conn.close()
            
            # Limit results
            max_rows = 500
            if len(rows) > max_rows:
                rows = rows[:max_rows]
                truncated = True
            else:
                truncated = False
            
            # Determine dialect (CSV uses DuckDB engine)
            if db_str.lower().endswith('.csv'):
                dialect = "duckdb"  # CSV queries use DuckDB
            elif db_str.endswith('.duckdb'):
                dialect = "duckdb"
            else:
                dialect = "sqlite"
            
            result_data = {
                "success": True,
                "rows": rows,
                "columns": columns,
                "row_count": len(rows),
                "truncated": truncated,
                "database": database,
                "database_type": dialect,
                "dialect": dialect
            }
            
            # Phase 3: Evaluate result quality (non-blocking)
            evaluator = _get_evaluator()
            if evaluator:
                try:
                    eval_result = evaluator.evaluate_result(query, result_data)
                    result_data["evaluation"] = {
                        "is_valid": eval_result.is_valid,
                        "confidence": eval_result.confidence,
                        "issues": eval_result.issues[:3] if eval_result.issues else []
                    }
                except Exception as eval_err:
                    logger.debug(f"Evaluation skipped: {eval_err}")
            
            return json.dumps(result_data, default=str)
            
        except Exception as e:
            logger.error(f"Local SQL execution failed: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": str(e),
                "database": database
            })
    
    async def _execute_tool_call(self, function_name: str, arguments: Dict[str, Any], job: Optional[JobStatus] = None) -> str:
        """Execute a tool call - routes to local execution or Azure Function"""
        
        # =====================================================================
        # SQL TOOL ROUTING: Local vs Azure
        # =====================================================================
        if function_name in ["execute_sql_query", "get_database_schema"]:
            database = arguments.get("database", "")
            
            if self._is_local_database(database, job):
                logger.info(f"Routing SQL to LOCAL execution for: {database}")
                if function_name == "execute_sql_query":
                    return await self._execute_local_sql(
                        arguments.get("query", ""),
                        database,
                        job
                    )
                elif function_name == "get_database_schema":
                    # Schema query for local databases
                    db_path = self._resolve_database_path(database, job)
                    if db_path:
                        db_path_str = str(db_path).lower()
                        if db_path_str.endswith('.csv'):
                            # For CSV, return column info using DuckDB DESCRIBE
                            csv_path_escaped = str(db_path).replace("'", "''")
                            table_name = db_path.stem.lower().replace(' ', '_').replace('-', '_')
                            schema_query = f"SELECT column_name, column_type as data_type FROM (DESCRIBE SELECT * FROM read_csv_auto('{csv_path_escaped}'))"
                        elif db_path_str.endswith('.duckdb'):
                            schema_query = "SELECT table_name, column_name, data_type FROM information_schema.columns"
                        else:
                            schema_query = "SELECT name, sql FROM sqlite_master WHERE type='table'"
                    else:
                        schema_query = "SELECT name, sql FROM sqlite_master WHERE type='table'"
                    return await self._execute_local_sql(schema_query, database, job)
            else:
                logger.info(f"Routing SQL to AZURE for: {database}")
        
        # =====================================================================
        # DEFAULT: Route to Azure Function
        # =====================================================================
        if not self.azure_functions_url:
            return json.dumps({"error": "AZURE_FUNCTIONS_URL not configured locally."})

        # Map function names to endpoints
        endpoint_map = {
            "execute_sql_query": "execute_azure_sql",
            "get_database_schema": "get_azure_sql_schema",
            "consult_rag": "consult_rag",
            "get_document_summary": "get_document_summary",  # Pre-computed summaries
            "graph_query": "graph_query",  # NEW: GraphRAG entity queries
            "query_knowledge_graph": "graph_query",  # Alias for agent tool name
            "get_entity_facets": "consult_rag",  # Uses consult_rag with pipeline=facets
            "validate_data_source": "validate_data_source",
            "extract_citations": "extract_citations",
            "generate_followup_questions": "generate_followup_questions"
        }
        
        endpoint = endpoint_map.get(function_name)
        if not endpoint:
            return json.dumps({"error": f"Tool '{function_name}' not mapped to an Azure Function."})
        
        # Inject workflow_id for all RAG-related tools
        rag_tools = ["consult_rag", "get_document_summary", "graph_query", "query_knowledge_graph", "get_entity_facets"]
        if function_name in rag_tools and job:
            workflow_id = job.context.get("workflow_id")
            if workflow_id:
                arguments["workflow_id"] = workflow_id
                logger.info(f"Injecting workflow_id={workflow_id} into {function_name} call")
        
        # Special handling for get_entity_facets - set pipeline=facets
        if function_name == "get_entity_facets":
            arguments["pipeline"] = "facets"
            arguments["query"] = "*"  # Required by consult_rag endpoint
            
        url = f"{self.azure_functions_url}/api/{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.azure_functions_key:
            headers["x-functions-key"] = self.azure_functions_key
            
        logger.info(f"Dispatching tool '{function_name}' to {url}")
        
        async with httpx.AsyncClient(timeout=180.0) as http_client:
            try:
                response = await http_client.post(url, json=arguments, headers=headers)
                return response.text 
            except Exception as e:
                logger.error(f"Error calling tool {function_name}: {e}")
                return json.dumps({"error": str(e)})

    # =========================================================================
    # OPENAI RUN LOGIC
    # =========================================================================

    async def _run_foundry_agent(self, job: JobStatus, agent_id: str, prompt: str) -> str:
        """Run an interaction with a Foundry Agent (Assistant)"""
        if not self.client:
            return "Error: Executor not initialized (Client is None)."

        try:
            # Prepare Tool Resources (RAG / Code Interpreter)
            tool_resources = {}
            
            # File Search (RAG)
            vector_store_id = job.context.get("azure_vector_store_id")
            if vector_store_id:
                tool_resources["file_search"] = {
                    "vector_store_ids": [vector_store_id]
                }
            
            # Code Interpreter
            file_ids = job.context.get("azure_file_ids", [])
            if file_ids:
                tool_resources["code_interpreter"] = {
                    "file_ids": file_ids
                }

            # 1. Create Thread with Resources (if vector store available)
            thread_kwargs = {}
            if tool_resources:
                thread_kwargs["tool_resources"] = tool_resources
                
            thread = await self.client.threads.create(**thread_kwargs)
            
            # 2. Add Message with file attachments if no vector store
            message_kwargs = {
                "thread_id": thread.id,
                "role": "user",
                "content": prompt
            }
            
            # Attach files directly to message if vector store failed
            if file_ids and not vector_store_id:
                # Use attachments with file_search tool
                message_kwargs["attachments"] = [
                    {"file_id": fid, "tools": [{"type": "file_search"}]}
                    for fid in file_ids
                ]
                logger.info(f"Attaching {len(file_ids)} files directly to message")
            
            await self.client.messages.create(**message_kwargs)
            
            # 3. Create Run (AI Foundry uses agent_id instead of assistant_id)
            run = await self.client.runs.create(
                thread_id=thread.id,
                agent_id=agent_id
            )
            
            # 4. Poll
            while True:
                await asyncio.sleep(1) # Basic polling
                run = await self.client.runs.get(thread_id=thread.id, run_id=run.id)
                
                if run.status == "completed":
                    # messages.list() returns AsyncItemPaged - iterate, don't await
                    messages_paged = self.client.messages.list(thread_id=thread.id)
                    async for msg in messages_paged:
                         if msg.role == "assistant":
                             # Handle different content formats
                             if hasattr(msg, 'content') and msg.content:
                                 if isinstance(msg.content, list) and len(msg.content) > 0:
                                     content_item = msg.content[0]
                                     if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                                         return content_item.text.value
                                     elif hasattr(content_item, 'text'):
                                         return str(content_item.text)
                                 elif isinstance(msg.content, str):
                                     return msg.content
                    return "No output from assistant."
                
                elif run.status == "requires_action":
                    # HANDLE TOOL CALLS
                    tool_outputs = []
                    if run.required_action and run.required_action.submit_tool_outputs:
                        for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                            func_name = tool_call.function.name
                            args_str = tool_call.function.arguments
                            try:
                                args = json.loads(args_str)
                            except:
                                args = {}
                            
                            self._add_log(job, f"  → Executing Tool: {func_name}...")
                            
                            # Execute locally/dispatch (pass job for context like workflow_id)
                            output = await self._execute_tool_call(func_name, args, job)
                            
                            self._add_log(job, f"  ← Tool Result ({func_name}): {output[:200]}...")
                            
                            tool_outputs.append({
                                "tool_call_id": tool_call.id,
                                "output": output
                            })
                        
                        # Submit back
                        await self.client.runs.submit_tool_outputs(
                            thread_id=thread.id,
                            run_id=run.id,
                            tool_outputs=tool_outputs
                        )
                
                elif run.status in ["failed", "cancelled", "expired"]:
                    error_msg = run.last_error if hasattr(run, 'last_error') else "Unknown error"
                    return f"Run ended with status: {run.status}. Error: {error_msg}"

        except Exception as e:
            logger.error(f"Agent Run Failed: {e}", exc_info=True)
            return f"Error running agent: {str(e)}"

    # =========================================================================
    # ORCHESTRATION LOGIC (Same as before, just uses _run_foundry_agent)
    # =========================================================================

    async def execute_workflow(self, workflow_id: str, input_data: Dict[str, Any]) -> str:
        workflow = db.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        job_id = db.create_job(workflow_id)
        # Ensure steps exist
        if not workflow.steps:
            workflow.steps = []
            db.create_workflow(workflow)

        asyncio.create_task(self._process_job_steps(job_id, workflow, input_data))
        return job_id

    async def _process_job_steps(self, job_id: str, workflow: WorkflowConfig, input_data: Dict[str, Any]):
        try:
            job = db.get_job(job_id)
            if not job: return

            if job.status == "pending":
                job.status = "in_progress"
                self._add_log(job, "Starting workflow execution...")
                user_query = workflow.user_intent or input_data.get("input", "Execute workflow")
                job.context["user_request"] = user_query
                self._add_log(job, f"User Request: {user_query}")
                db.update_job(job)
            
            # Always ensure workflow_id is set (for RAG tool calls)
            if "workflow_id" not in job.context:
                job.context["workflow_id"] = workflow.id
                db.update_job(job)

            if not self.client:
                await self.initialize()

            # =========================================================
            # HANDLE DATA SOURCES (Index to Azure AI Search via Azure Function)
            # =========================================================
            if workflow.data_sources and not job.context.get("documents_indexed"):
                indexed_files = []
                
                import base64
                
                for ds in workflow.data_sources:
                    if ds.type == "file" and ds.path:
                        try:
                            # Resolve file path
                            file_path = Path(ds.path)
                            if not file_path.is_absolute():
                                file_path = Path.cwd() / ds.path
                            
                            if not file_path.exists():
                                # Try common upload locations
                                project_root = Path(__file__).parent.parent.parent.parent.parent.parent
                                alt_paths = [
                                    Path.cwd() / "uploads" / ds.path,
                                    Path.cwd().parent / ds.path,
                                    project_root / ds.path,
                                    project_root / "ui" / "hil-workflow" / ds.path,
                                    project_root / "uploads" / ds.path,
                                ]
                                for alt in alt_paths:
                                    if alt.exists():
                                        file_path = alt
                                        self._add_log(job, f"📁 Found file at: {file_path}")
                                        break
                            
                            if not file_path.exists():
                                self._add_log(job, f"⚠️ File not found: {ds.path}")
                                continue
                            
                            file_type = file_path.suffix.lower().lstrip('.')
                            
                            # CSV files should be queried via SQL, not indexed via RAG
                            if file_type == 'csv':
                                # Add CSV to database_paths for SQL agent
                                if "database_paths" not in job.context:
                                    job.context["database_paths"] = {}
                                job.context["database_paths"][ds.name] = str(file_path)
                                
                                # Pre-fetch CSV column names for agent context
                                columns = []
                                try:
                                    if HAS_DUCKDB:
                                        import duckdb
                                        conn = duckdb.connect(':memory:')
                                        csv_path_esc = str(file_path).replace("'", "''")
                                        result = conn.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{csv_path_esc}')").fetchall()
                                        columns = [row[0] for row in result]  # column_name is first element
                                        conn.close()
                                except Exception as e:
                                    logger.warning(f"Failed to pre-fetch schema for {ds.name}: {e}")
                                
                                self._add_log(job, f"📊 CSV file registered for SQL queries: {ds.name} → {file_path}")
                                if columns:
                                    self._add_log(job, f"   Columns: {', '.join(columns[:5])}{'...' if len(columns) > 5 else ''}")
                                
                                # Store csv_files list with column info for prompt context
                                if "csv_files" not in job.context:
                                    job.context["csv_files"] = []
                                job.context["csv_files"].append({
                                    "name": ds.name,
                                    "path": str(file_path),
                                    "columns": columns if columns else None
                                })
                                continue  # Skip RAG indexing for CSVs
                            
                            # Non-CSV files: Index via RAG (Azure Function)
                            self._add_log(job, f"📄 Indexing via Azure: {file_path.name}")
                            
                            with open(file_path, 'rb') as f:
                                file_content = f.read()
                            
                            file_content_b64 = base64.b64encode(file_content).decode('utf-8')
                            
                            # Call Azure Function
                            url = f"{self.azure_functions_url}/api/index_document"
                            headers = {"Content-Type": "application/json"}
                            if self.azure_functions_key:
                                headers["x-functions-key"] = self.azure_functions_key
                            
                            payload = {
                                "workflow_id": workflow.id,
                                "file_name": ds.name or file_path.name,
                                "file_content": file_content_b64,
                                "file_type": file_type
                            }
                            
                            async with httpx.AsyncClient(timeout=300.0) as http_client:
                                response = await http_client.post(url, json=payload, headers=headers)
                                
                                # Log raw response for debugging
                                if response.status_code != 200:
                                    self._add_log(job, f"⚠️ Azure Function returned {response.status_code}: {response.text[:500]}")
                                    continue
                                
                                try:
                                    result = response.json()
                                except Exception as json_err:
                                    self._add_log(job, f"⚠️ JSON parse error: {json_err}. Raw: {response.text[:300]}")
                                    continue
                            
                            if result.get("success"):
                                chunk_count = result.get("chunks", 0)
                                indexed_files.append({
                                    "name": ds.name or file_path.name,
                                    "chunks": chunk_count
                                })
                                self._add_log(job, f"✓ Indexed {chunk_count} chunks from {ds.name}")
                                
                                # Log if entity extraction was started (optional, disabled by default)
                                extraction_instance_id = result.get("entity_extraction_instance_id")
                                if extraction_instance_id:
                                    self._add_log(job, f"🔄 LLM entity extraction running in background: {extraction_instance_id}")
                                    job.context["entity_extraction_instance_id"] = extraction_instance_id
                            else:
                                self._add_log(job, f"⚠️ Indexing failed: {result.get('error')}")
                                
                        except Exception as e:
                            self._add_log(job, f"⚠️ Failed to process file {ds.name}: {e}")
                    
                    # Handle database data sources
                    elif ds.type == "database" and ds.path:
                        db_path = Path(ds.path)
                        if not db_path.is_absolute():
                            db_path = Path.cwd() / ds.path
                        
                        # Search for database file
                        if not db_path.exists():
                            project_root = Path(__file__).parent.parent.parent.parent.parent.parent
                            alt_paths = [
                                Path.cwd() / ds.path,
                                Path.cwd() / "data" / ds.path,
                                project_root / ds.path,
                                project_root / "data" / ds.path,
                            ]
                            for alt in alt_paths:
                                if alt.exists():
                                    db_path = alt
                                    break
                        
                        if db_path.exists():
                            # Store database name-to-path mapping for local SQL routing
                            if "database_paths" not in job.context:
                                job.context["database_paths"] = {}
                            # Store both the friendly name and the path
                            job.context["database_paths"][ds.name] = str(db_path)
                            self._add_log(job, f"📊 Found database: {ds.name} at {db_path}")
                        else:
                            self._add_log(job, f"⚠️ Database file not found: {ds.path}")
                
                if indexed_files:
                    job.context["indexed_files"] = indexed_files
                    job.context["workflow_id"] = workflow.id  # Store for RAG filtering
                    self._add_log(job, f"✓ Indexed {len(indexed_files)} file(s) for RAG retrieval")
                    # Add clear message for agents that data is ready
                    total_chunks = sum(f.get("chunks", 0) for f in indexed_files)
                    job.context["data_ready_message"] = (
                        f"Data is indexed and ready for querying. "
                        f"{len(indexed_files)} file(s), {total_chunks} chunks indexed. "
                        f"Use consult_rag for searches and get_entity_facets for aggregation queries."
                    )
                
                # Add message about CSV files available for SQL
                csv_files = job.context.get("csv_files", [])
                db_paths = job.context.get("database_paths", {})
                if csv_files or db_paths:
                    csv_msg = f"📊 {len(csv_files)} CSV file(s) available for SQL queries: {list(db_paths.keys())}"
                    self._add_log(job, csv_msg)
                    # Update or create data_ready_message
                    existing_msg = job.context.get("data_ready_message", "")
                    job.context["data_ready_message"] = (
                        f"{existing_msg} "
                        f"CSV data sources for SQL: {list(db_paths.keys())}. "
                        f"Use execute_sql_query with database=<name> to query."
                    ).strip()
                
                job.context["documents_indexed"] = True
                db.update_job(job)
            # =========================================================

            start_index = job.current_step_index
            if job.status == "waiting_for_user":
                job.status = "in_progress"
            
            # Lookup Agent IDs if step uses names
            agents_map = self.agents_config.get("agents", {})

            for i in range(start_index, len(workflow.steps)):
                step = workflow.steps[i]
                job.current_step_index = i
                db.update_job(job)

                self._add_log(job, f"=== Step {i+1}: {step.name} ===")
                
                # Resolve Agent ID
                agent_id = step.agent_id
                # If agent_id is a name like "sql_agent", resolve it
                if agent_id in agents_map:
                    agent_id = agents_map[agent_id]["id"]
                elif agent_id and "_" in agent_id: # fallback lookup
                     for k, v in agents_map.items():
                         if v.get("name") == agent_id:
                             agent_id = v["id"]
                             break
                
                self._add_log(job, f"Agent: {step.agent_id} ({agent_id})")
                
                # Construct Prompt (Includes Feedback if retrying)
                step_input = self._build_step_context(job, step, i)
                
                # DEBUG: Log full prompt being sent to agent
                logger.debug(f"[Job {job.id}] Full prompt to agent:\n{step_input}")
                
                # Execute Agent
                self._add_log(job, f"→ Sending task to Agent...")
                response = await self._run_foundry_agent(job, agent_id, step_input)
                
                # Log Response
                self._add_log(job, f"← Response:")
                self._add_log(job, response[:500] + "..." if len(response) > 500 else response)
                
                # Store Output
                job.context[f"step_{i+1}_output"] = response
                if step.id:
                    job.context[step.id] = response
                if step.output_key:
                    job.context[step.output_key] = response

                # Populate Rich Step Output for UI
                # We attempt to parse metrics/insights if response is JSON, otherwise just content
                from .models import StepOutput # Ensure visibility
                rich_output = StepOutput(
                    content=response,
                    thought_process=None # Could extract if agents provided chain-of-thought
                )
                job.step_outputs[step.name] = rich_output
                
                db.update_job(job)

                # =========================================================
                # HIL: Pause after EVERY step for user review
                # User can either:
                #   1. Approve (proceed to next step / complete workflow)
                #   2. Provide feedback (retry current step with modifications)
                # =========================================================
                is_last_step = (i == len(workflow.steps) - 1)
                if is_last_step:
                    self._add_log(job, f"⏸️ Final step completed. Review: '{step.name}'")
                else:
                    self._add_log(job, f"⏸️ Step completed. Review: '{step.name}'")
                
                job.status = "waiting_for_user"
                job.context["pending_step_index"] = i
                job.context["pending_step_name"] = step.name
                job.context["is_last_step"] = is_last_step
                db.update_job(job)
                return  # Exit loop, wait for resume_job

            job.status = "completed"
            self._add_log(job, "✓ Workflow completed successfully.")
            db.update_job(job)


        except Exception as e:
            logger.error(f"Orchestration failed: {e}", exc_info=True)
            job = db.get_job(job_id)
            if job:
                job.status = "failed"
                job.error = str(e)
                self._add_log(job, f"✗ Execution failed: {str(e)}")
                db.update_job(job)

    def _build_step_context(self, job: JobStatus, step: StepConfig, step_index: int) -> str:
        user_request = job.context.get("user_request", "")
        prompt = f"User Request: {user_request}\n\n"
        
        # Add History
        if step_index > 0:
            prompt += "PREVIOUS STEPS OUTPUT:\n"
            for j in range(step_index):
                output = job.context.get(f"step_{j+1}_output")
                if output:
                    prompt += f"Step {j+1} Result: {output}\n\n"
        
        # Add data ready message if documents were indexed (critical for RAG agent)
        if job.context.get("documents_indexed"):
            indexed_files = job.context.get("indexed_files", [])
            workflow_id = job.context.get("workflow_id", "")
            
            # Pass data context - agent instructions handle behavior
            prompt += "\n=== DATA CONTEXT ===\n"
            prompt += f"workflow_id: {workflow_id}\n"
            prompt += f"status: indexed\n"
            if indexed_files:
                prompt += f"files: {', '.join(f.get('name', '') for f in indexed_files)}\n"
                prompt += f"total_chunks: {sum(f.get('chunks', 0) for f in indexed_files)}\n"
            prompt += "===================\n\n"
        
        # Add CSV schema context for SQL agent - helps agent understand data structure
        csv_files = job.context.get("csv_files", [])
        database_paths = job.context.get("database_paths", {})
        
        if csv_files or database_paths:
            prompt += "\n=== CSV DATA SOURCES (for SQL queries) ===\n"
            prompt += "Use get_database_schema(database='<name>') to verify columns before querying.\n"
            prompt += "Use execute_sql_query(database='<name>', query='...') to run SQL.\n"
            prompt += "Table names in DuckDB: use the lowercase underscore version (e.g., 'tdn_plan_demand').\n\n"
            
            for db_name, db_path in database_paths.items():
                if db_path.lower().endswith('.csv'):
                    csv_filename = Path(db_path).stem
                    table_name = csv_filename.lower().replace(' ', '_').replace('-', '_')
                    prompt += f"📊 {db_name}\n"
                    prompt += f"   Path: {csv_filename}.csv\n"
                    prompt += f"   Table name: {table_name}\n"
                    
                    # Try to get cached schema from csv_files
                    for cf in csv_files:
                        if cf.get("name") == db_name and cf.get("columns"):
                            columns = cf["columns"]
                            prompt += f"   Columns: {', '.join(columns[:10])}"
                            if len(columns) > 10:
                                prompt += f" ... (+{len(columns)-10} more)"
                            prompt += "\n"
                            break
                    prompt += "\n"
            
            prompt += "IMPORTANT: When joining CSVs, verify column names match between tables.\n"
            prompt += "If data structures differ (e.g., monthly columns vs rows), transform first.\n"
            prompt += "==========================================\n\n"
        
        # Add Current Task
        prompt += f"CURRENT TASK ({step.name}):\n"
        # Prioritize 'instructions' from step, fallback to description
        instructions = getattr(step, 'instructions', step.description)
        prompt += f"{instructions}\n"

        # Add Feedback if Retrying
        feedback_key = f"user_feedback_step_{step_index+1}" # 1-based index matching step output
        feedback = job.context.get(feedback_key)
        if feedback:
             prompt += f"\n\nCRITICAL USER FEEDBACK (This is a retry - fix previous issues):\n{feedback}\nPlease address this feedback specifically in your response."

        prompt += "\nPlease execute this task based on the User Request, Previous Context, and specific Instructions."
        return prompt

    def _add_log(self, job: JobStatus, message: str):
        job.logs.append(message)
        logger.info(f"[Job {job.id}] {message}")

    async def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        return db.get_job(job_id)

    async def resume_job(self, job_id: str, user_input: str, approved: Optional[bool] = None) -> JobStatus:
        job = db.get_job(job_id)
        if not job: return None
        
        if job.status == "waiting_for_user":
            step_index = job.current_step_index
            
            if approved:
                self._add_log(job, f"✅ User Approved Step {step_index+1}")
                # Move to next step
                job.current_step_index += 1
                job.status = "in_progress"
                # Clear legacy feedback if any, though context persists
            else:
                self._add_log(job, f"🔄 User Rejected Step {step_index+1}. Retrying...")
                # Stay on current step (don't increment)
                job.status = "in_progress"
                if user_input:
                    job.context[f"user_feedback_step_{step_index+1}"] = user_input
                    self._add_log(job, f"Feedback: {user_input}")
            
            db.update_job(job)
            
            # Resume execution
            # If approved, loop starts at i+1. If retry, loop starts at i.
            asyncio.create_task(self._process_job_steps(job.id, db.get_workflow(job.workflow_id), {}))
            
        return job

executor = AzureWorkflowExecutor()
