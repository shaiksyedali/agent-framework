"""
FastAPI Backend for Azure Agentic Workflow UI.
Bridges frontend to Azure Foundry agents.
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File as FastAPIFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import (
    WorkflowConfig,
    AgentConfig,
    ExecuteRequest,
    ResumeRequest,
    ChatRequest,
    JobStatus,
    PlanRequest
)
from .db import db
from .azure_executor import executor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Azure Agentic Workflow API",
    description="Backend API for Azure Foundry multi-agent workflows",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== LIFECYCLE =====

@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    logger.info("Starting Azure Agentic Workflow API...")
    await executor.initialize()
    logger.info("✓ API ready")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    logger.info("Shutting down...")
    await executor.cleanup()


# ===== AGENTS =====

@app.get("/agents", response_model=List[AgentConfig])
async def list_agents():
    """
    List all available Azure Foundry agents.
    Returns pre-created agents with is_azure=True flag.
    """
    config_file = Path(__file__).parent.parent.parent.parent.parent.parent / "azure_agents_config.json"

    try:
        with open(config_file) as f:
            config = json.load(f)

        agents = []
        for key, agent_data in config["agents"].items():
            agents.append(AgentConfig(
                id=agent_data["id"],
                name=agent_data.get("name", key),
                role=key.replace("_", " ").title(),
                instructions=f"Azure Foundry {key.replace('_', ' ')}",
                model_name="gpt-4o",
                model_provider="azure",
                is_azure=True,
                is_editable=False,
                tools=[],
                data_sources=[]
            ))

        return agents

    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Azure agents configuration not found")


# ===== WORKFLOWS =====

@app.get("/workflows", response_model=List[WorkflowConfig])
async def list_workflows():
    """List all workflows"""
    return db.list_workflows()


@app.get("/workflows/{workflow_id}", response_model=WorkflowConfig)
async def get_workflow(workflow_id: str):
    """Get a specific workflow"""
    workflow = db.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@app.post("/workflows", response_model=WorkflowConfig)
async def create_workflow(workflow: WorkflowConfig):
    """
    Create or update a workflow.

    For Azure workflows:
    - Validates that agents exist in Azure
    - Converts data sources for tool selection
    - Stores workflow configuration
    """
    try:
        # Validate Azure agents (if any are marked as Azure)
        config_file = Path(__file__).parent.parent.parent.parent.parent.parent / "azure_agents_config.json"
        with open(config_file) as f:
            azure_config = json.load(f)

        azure_agent_ids = {agent_data["id"] for agent_data in azure_config["agents"].values()}

        for agent in workflow.agents:
            if agent.is_azure and agent.id not in azure_agent_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Azure agent {agent.id} not found in Azure configuration"
                )

        # Save workflow
        workflow_id = db.create_workflow(workflow)
        workflow.id = workflow_id

        logger.info(f"Created/updated workflow: {workflow.name} (ID: {workflow_id})")

        return workflow

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating workflow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow"""
    success = db.delete_workflow(workflow_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"message": "Workflow deleted"}


# ===== EXECUTION =====

@app.post("/execute", response_model=JobStatus)
async def execute_workflow(request: ExecuteRequest):
    """
    Execute a workflow.

    Creates a job and starts execution via Azure Foundry agents.
    Returns immediately with job_id for status polling.
    """
    try:
        # Validate workflow exists
        workflow = db.get_workflow(request.workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Start execution
        job_id = await executor.execute_workflow(request.workflow_id, request.input_data)

        # Get initial job status
        job = await executor.get_job_status(job_id)

        return job

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing workflow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str):
    """
    Get job execution status.

    Frontend polls this endpoint for real-time updates.
    Returns logs, outputs, and current execution state.
    """
    job = await executor.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/resume", response_model=JobStatus)
async def resume_job(request: ResumeRequest):
    """
    Resume a paused job (Human-in-the-Loop).

    Used when a job is waiting_for_user status.
    User can provide feedback or approval.
    """
    try:
        job = await executor.resume_job(request.job_id, request.user_input, request.approved)
        return job
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error resuming job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== PLANNING =====

@app.post("/plan", response_model=WorkflowConfig)
async def create_plan(request: PlanRequest):
    """
    Auto-generate workflow plan from user intent using Azure Planner Agent.

    Uses Azure Planner Agent (cloud) to analyze intent, infer required agents,
    and create structured workflow plans.
    """
    try:
        logger.info(f"AI Planning request: {request.user_request}")

        # Import planner service
        from .planner_service import PlannerService

        # Initialize planner
        planner = PlannerService()

        try:
            # Generate workflow plan (async call to Azure Planner Agent)
            workflow = await planner.create_workflow_plan(
                user_request=request.user_request,
                data_sources_hint=request.data_sources or []
            )

            logger.info(f"Generated plan: {workflow.name} with {len(workflow.agents)} agents")

            return workflow

        finally:
            # Clean up Azure clients
            await planner.close()

    except Exception as e:
        logger.error(f"Error creating plan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== CHAT =====

@app.post("/chat")
async def chat_with_job(request: ChatRequest):
    """
    Chat with completed job results.

    Automatically detects available data sources and uses appropriate agent:
    - Documents → RAG agent (consult_rag, get_document_summary)
    - Databases → SQL agent (execute_sql)
    - Both → RAG agent with SQL context
    """
    job = await executor.get_job_status(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet")

    try:
        # Get workflow context
        workflow_id = job.context.get("workflow_id", request.job_id)
        indexed_files = job.context.get("indexed_files", [])
        database_paths = job.context.get("database_paths", {})
        step_outputs = job.context.get("step_outputs", [])
        
        # Detect available data sources
        has_documents = len(indexed_files) > 0
        has_databases = len(database_paths) > 0
        
        # Build context message based on available data sources
        data_sources_info = []
        tools_hint = []
        file_names = []
        
        if has_documents:
            file_names = [f.get("name", str(f)) if isinstance(f, dict) else str(f) for f in indexed_files]
            data_sources_info.append(f"- Documents: {', '.join(file_names)}")
            tools_hint.append("consult_rag and get_document_summary for document queries")
        
        if has_databases:
            db_names = list(database_paths.keys()) if isinstance(database_paths, dict) else [str(p) for p in database_paths]
            data_sources_info.append(f"- Databases: {', '.join(db_names)}")
            tools_hint.append(f"execute_sql_query with database='{db_names[0] if db_names else 'default'}' for data queries")
        
        if not has_documents and not has_databases:
            data_sources_info.append("- No indexed data sources (using workflow step outputs)")
        
        # Create a temporary job context for tool execution
        chat_job = JobStatus(
            id=request.job_id,
            workflow_id=str(job.workflow_id),
            status="running",
            current_step_index=0,
            context={
                "workflow_id": workflow_id,
                "database_paths": database_paths,
                **job.context
            },
            logs=[],
            step_outputs={}
        )
        
        agents_config = executor.agents_config.get("agents", {})
        combined_responses = []
        sources_used = []
        
        # === Query ALL available data sources ===
        
        # 1. Query SQL database if available (often has structured people/location data)
        if has_databases:
            db_names = list(database_paths.keys()) if isinstance(database_paths, dict) else []
            sql_context = f"""You are querying a SQL database to answer a user question.

AVAILABLE DATABASE: {db_names[0] if db_names else 'local database'}
DATABASE TABLES: Use get_database_schema first to see available tables and columns.

USER QUESTION: {request.message}

CRITICAL WORKFLOW:
1. FIRST call get_database_schema(database="{db_names[0] if db_names else 'default'}") to see tables
2. Generate appropriate SQL query based on schema
3. Call execute_sql_query with the SQL query
4. Return the results or state "No matching data found in database"

Be thorough - search for partial matches (LIKE '%name%') when exact matches fail."""

            sql_agent_id = agents_config.get("sql_agent", {}).get("id")
            if sql_agent_id:
                logger.info(f"Chat: Querying SQL database for job {request.job_id}")
                try:
                    sql_response = await executor._run_foundry_agent(
                        job=chat_job,
                        agent_id=sql_agent_id,
                        prompt=sql_context
                    )
                    if sql_response and "not found" not in sql_response.lower() and "no data" not in sql_response.lower():
                        combined_responses.append(f"**From Database:**\n{sql_response}")
                        sources_used.append("SQL Database")
                except Exception as e:
                    logger.warning(f"SQL query failed: {e}")
        
        # 2. Query RAG documents if available
        if has_documents:
            rag_context = f"""You are searching indexed documents to answer a user question.

AVAILABLE DOCUMENTS: {', '.join(file_names)}
WORKFLOW ID: {workflow_id}

USER QUESTION: {request.message}

INSTRUCTIONS:
1. Use consult_rag(query="{request.message}", workflow_id="{workflow_id}") to search
2. Analyze returned documents for relevant information
3. Return findings or state "No matching information in documents"

Be thorough - try multiple search terms if needed."""

            rag_agent_id = agents_config.get("rag_agent", {}).get("id")
            if rag_agent_id:
                logger.info(f"Chat: Querying RAG documents for job {request.job_id}")
                try:
                    rag_response = await executor._run_foundry_agent(
                        job=chat_job,
                        agent_id=rag_agent_id,
                        prompt=rag_context
                    )
                    if rag_response and "not found" not in rag_response.lower() and "no information" not in rag_response.lower():
                        combined_responses.append(f"**From Documents:**\n{rag_response}")
                        sources_used.append("RAG Documents")
                except Exception as e:
                    logger.warning(f"RAG query failed: {e}")
        
        # 3. Synthesize a clean, user-friendly response
        if combined_responses:
            # Use response generator to synthesize a clean answer
            response_gen_id = agents_config.get("response_generator", {}).get("id")
            if response_gen_id and len(combined_responses) >= 1:
                raw_data = "\n\n".join(combined_responses)
                synthesis_prompt = f"""Synthesize a clear, user-friendly answer from the following data.

USER QUESTION: {request.message}

RAW DATA FROM SOURCES:
{raw_data}

INSTRUCTIONS:
- Provide a DIRECT answer in 1-3 sentences
- Do NOT mention "database" or "documents" - just give the answer naturally
- Do NOT include headers like "From Database:" or "From Documents:"
- If the data clearly answers the question, state the answer confidently
- If data is ambiguous or conflicting, note the key details
- Be concise and professional"""

                try:
                    logger.info(f"Chat: Synthesizing user-friendly response")
                    final_response = await executor._run_foundry_agent(
                        job=chat_job,
                        agent_id=response_gen_id,
                        prompt=synthesis_prompt
                    )
                except Exception as e:
                    logger.warning(f"Synthesis failed, using raw response: {e}")
                    final_response = combined_responses[0]  # Use first successful response
            else:
                final_response = combined_responses[0]  # Single source, use as-is
        else:
            # Fallback: use response generator with step outputs
            response_gen_id = agents_config.get("response_generator", {}).get("id")
            if response_gen_id:
                fallback_context = f"""No direct matches found in data sources.

Workflow step outputs:
{json.dumps(step_outputs[:3], indent=2) if step_outputs else 'No step outputs'}

USER QUESTION: {request.message}

Provide the best answer based on available context, or explain that the information was not found."""
                
                final_response = await executor._run_foundry_agent(
                    job=chat_job,
                    agent_id=response_gen_id,
                    prompt=fallback_context
                )
                sources_used.append("Workflow Context")
            else:
                final_response = "The requested information was not found in the indexed data sources or database."
        
        return {
            "response": final_response,
            "workflow_id": workflow_id,
            "sources": sources_used,
            "agent_used": "Multi-Source" if len(sources_used) > 1 else (sources_used[0] if sources_used else "None")
        }
        
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



# ===== FILE OPERATIONS =====

@app.get("/files")
async def list_files(path: str = "."):
    """
    List files in a directory.

    Used by file explorer in UI.
    """
    try:
        base_path = Path.cwd()
        target_path = (base_path / path).resolve()

        # Security: Ensure path is within project directory
        if not str(target_path).startswith(str(base_path)):
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        if not target_path.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        items = []
        for item in target_path.iterdir():
            items.append({
                "name": item.name,
                "path": str(item.relative_to(base_path)),
                "is_dir": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else 0
            })

        return items

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload")
async def upload_file(file: UploadFile, path: str = "."):
    """
    Upload a file.

    Used by file explorer to upload data sources.
    """
    try:
        base_path = Path.cwd()
        target_dir = (base_path / path).resolve()

        # Security check
        if not str(target_dir).startswith(str(base_path)):
            raise HTTPException(status_code=403, detail="Access denied")

        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / file.filename

        # Save file
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        logger.info(f"Uploaded file: {file_path}")

        return {
            "message": "File uploaded successfully",
            "path": str(file_path),  # Return absolute path for reliable resolution
            "relative_path": str(file_path.relative_to(base_path))
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== HEALTH CHECK =====

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Azure Agentic Workflow API"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
