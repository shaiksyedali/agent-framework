from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Dict, Any, List

from .schema import WorkflowConfig, JobStatus
from .registry import WorkflowRegistry
from .agents.planner import PlannerAgent
from .agents.orchestrator import Orchestrator
from agno.agent import Agent

app = FastAPI(title="Generic Agentic Framework API")

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import os
from agno.models.azure import AzureOpenAI
from agno.models.openai import OpenAIChat

# Helper to get default model
def get_default_model():
    if os.getenv("AZURE_OPENAI_API_KEY"):
        return AzureOpenAI(id=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"))
    return OpenAIChat(id="gpt-4o")

# Initialize components
registry = WorkflowRegistry()
orchestrator = Orchestrator(registry)
# Initialize Planner with correct provider
planner_provider = "azure_openai" if os.getenv("AZURE_OPENAI_API_KEY") else "openai"
planner_model = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
planner = PlannerAgent(model_provider=planner_provider, model_name=planner_model)

class PlanRequest(BaseModel):
    user_request: str

class ExecuteRequest(BaseModel):
    workflow_id: str
    input_data: Dict[str, Any]

class ResumeRequest(BaseModel):
    job_id: str
    user_input: str

@app.post("/plan", response_model=WorkflowConfig)
def create_plan(request: PlanRequest):
    """Generate a workflow plan from user request."""
    print(f"Received plan request: {request.user_request}")
    return planner.create_plan(request.user_request)

@app.post("/workflows", response_model=WorkflowConfig)
def save_workflow(workflow: WorkflowConfig):
    """Save a workflow blueprint."""
    return registry.save_workflow(workflow)

@app.get("/workflows", response_model=List[WorkflowConfig])
def list_workflows():
    """List all workflows."""
    return registry.list_workflows()

@app.get("/workflows/{workflow_id}", response_model=WorkflowConfig)
def get_workflow(workflow_id: str):
    """Get a specific workflow."""
    wf = registry.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf

@app.delete("/workflows/{workflow_id}")
def delete_workflow(workflow_id: str):
    success = registry.delete_workflow(workflow_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"status": "success"}

@app.post("/execute", response_model=JobStatus)
def execute_workflow(request: ExecuteRequest):
    """Start a workflow execution."""
    try:
        return orchestrator.start_workflow(request.workflow_id, request.input_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/resume", response_model=JobStatus)
def resume_workflow(request: ResumeRequest):
    """Resume a workflow that is waiting for user input."""
    try:
        return orchestrator.resume_workflow(request.job_id, request.user_input)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/jobs/{job_id}", response_model=JobStatus)
def get_job_status(job_id: str):
    """Get the status of a job."""
    job = registry.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

class ChatRequest(BaseModel):
    job_id: str
    message: str

@app.post("/chat")
def chat_with_job(request: ChatRequest):
    """Chat with the context of a completed job."""
    job = registry.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Load workflow to get data sources
    workflow = registry.get_workflow(job.workflow_id)
    tools = []
    knowledge = None
    
    if workflow:
        # Re-use builder logic to get tools (simplified)
        from agno.tools.sql import SQLTools
        from agno.knowledge.knowledge import Knowledge
        from agno.vectordb.chroma import ChromaDb

        for ds in workflow.data_sources:
            if ds.type == "database" and ds.connection_string:
                tools.append(SQLTools(db_url=ds.connection_string))
            elif ds.type == "file" and ds.path:
                if not knowledge:
                    import os
                    embedder = None
                    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_EMBED_DEPLOYMENT"):
                        from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder
                        embedder = AzureOpenAIEmbedder(
                            id=os.getenv("AZURE_EMBED_DEPLOYMENT"),
                            dimensions=int(os.getenv("AZURE_EMBED_DIM", 1536))
                        )

                    vector_db = ChromaDb(
                        collection=f"agent_{workflow.agents[0].id if workflow.agents else 'chat'}",
                        path="./chromadb_data",
                        persistent_client=True,
                        embedder=embedder,
                    )
                    reranker = None
                    try:
                        from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker
                        reranker = SentenceTransformerReranker(top_n=15)
                    except Exception:
                        # Soft fallback when sentence-transformers is not installed
                        reranker = None

                    try:
                        import inspect
                        kw = {
                            "vector_db": vector_db,
                            "max_results": 50,
                            "reranker": reranker,
                        }
                        supported = set(inspect.signature(Knowledge).parameters.keys())
                        kw = {k: v for k, v in kw.items() if k in supported}
                        knowledge = Knowledge(**kw)
                        if reranker and not getattr(knowledge, "reranker", None):
                            knowledge.reranker = reranker  # type: ignore[attr-defined]
                    except Exception:
                        knowledge = Knowledge(vector_db=vector_db, max_results=50)
                knowledge.add_content(path=ds.path, skip_if_exists=True)

    # Build chat history transcript
    history = job.messages or []
    history_text = "\n".join([f"{m.get('role','user')}: {m.get('content','')}" for m in history])
    user_turn = request.message

    agent = Agent(
        model=get_default_model(),
        instructions=[
            "You are a helpful assistant. Answer questions based on the provided context and available tools.",
            "Use SQL for database queries and Knowledge Base for document search.",
            "IMPORTANT: You are using SQLite. Do NOT use PostgreSQL functions like EXTRACT(YEAR from ...). Use strftime('%Y', column) instead.",
            "STRATEGY: 1. Inspect the database schema first using the available tools (e.g. list_tables, describe_table) to understand table names and columns.",
            "2. Generate SQLite-compatible queries based on the actual schema.",
            "3. If a query fails, analyze the error, correct the SQL (e.g. fix table names or syntax), and retry.",
            "4. **Self-Correction**: If a query returns empty results, do NOT give up. Check alternative columns or tables that might contain the requested information.",
            "5. **Knowledge-First**: Use the Knowledge Base to understand domain terms before querying.",
            "You have access to prior chat history for this job; use it to maintain context."
        ],
        tools=tools,
        knowledge=knowledge,
        markdown=True,
        retries=3,
        delay_between_retries=10,
        exponential_backoff=True,
    )
    
    response = agent.run(f"History:\n{history_text}\n\nUser: {user_turn}")

    # Persist chat history
    job.messages = history + [
        {"role": "user", "content": user_turn},
        {"role": "assistant", "content": response.content},
    ]
    registry.save_job(job)

    return {"response": response.content, "messages": job.messages}

@app.get("/files")
def list_files(path: str = "."):
    """List files in the given directory."""
    import os
    
    # Security check: Prevent traversing up too far if needed, but for local tool it's okay.
    # For now, just ensure it exists.
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Path not found")
        
    items = []
    try:
        for entry in os.scandir(path):
            items.append({
                "name": entry.name,
                "path": entry.path,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if not entry.is_dir() else 0
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
        
    return items

@app.post("/upload")
def upload_file(file: UploadFile, path: str = "."):
    """Upload a file to the specified path."""
    import os
    import shutil
    
    # Security check
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Path not found")
        
    file_path = os.path.join(path, file.filename)
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {e}")
        
    return {"status": "success", "path": file_path}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
