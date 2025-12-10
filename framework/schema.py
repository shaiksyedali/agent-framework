from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
import uuid

# --- Data Source Configuration ---
class DataSourceConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: Literal["database", "file", "mcp_server", "url"]
    connection_string: Optional[str] = None  # For DBs
    path: Optional[str] = None  # For files
    url: Optional[str] = None  # For MCP/Web
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

# --- MCP Server Configuration ---
class MCPServerConfig(BaseModel):
    name: str
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None  # For SSE/HTTP
    env: Optional[Dict[str, str]] = None

# --- Agent Configuration ---
class AgentConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    role: str  # e.g., "Researcher", "Coder"
    instructions: str
    model_provider: str = "openai"  # or "azure_openai", "anthropic"
    model_name: str = "gpt-4o"
    tools: Optional[List[str]] = Field(default_factory=list)  # List of tool names or MCP tool sets
    mcp_servers: Optional[List[MCPServerConfig]] = Field(default_factory=list) # MCP Servers
    data_sources: Optional[List[str]] = Field(default_factory=list)  # IDs of DataSourceConfig
    temperature: float = 0.7

# --- Team Configuration ---
class TeamConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    leader_agent_id: Optional[str] = None  # Optional leader
    member_agent_ids: List[str]
    instructions: Optional[str] = None
    model_provider: str = "openai"  # or "azure_openai", "anthropic"
    model_name: str = "gpt-4o"

# --- Workflow Step Configuration ---
class StepConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: Literal["agent_call", "team_call", "user_input", "tool_call"]
    agent_id: Optional[str] = None  # If type is agent_call
    team_id: Optional[str] = None   # If type is team_call
    input_template: str  # Template string to format with workflow inputs
    output_key: str  # Key to store the result in the workflow context
    config: Optional[Dict[str, Any]] = Field(default_factory=dict) # Extra config

class UserConfirmationStep(StepConfig):
    type: Literal["user_confirmation"] = "user_confirmation"
    message: str

# --- Workflow Blueprint ---
class WorkflowConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    user_intent: str
    agents: Optional[List[AgentConfig]] = Field(default_factory=list)
    teams: Optional[List[TeamConfig]] = Field(default_factory=list) # Teams
    data_sources: Optional[List[DataSourceConfig]] = Field(default_factory=list)
    steps: Optional[List[Union[StepConfig, UserConfirmationStep]]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

# --- Execution History ---
class JobStatus(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    status: Literal["pending", "running", "completed", "failed", "waiting_for_user"]
    current_step_index: int = 0
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    logs: Optional[List[str]] = Field(default_factory=list)
    hil_mode: bool = False
    messages: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

# --- Rich Output Schemas ---
class Visualization(BaseModel):
    title: str
    type: Literal["bar", "pie", "line", "area"]
    data: List[Dict[str, Any]]
    x_key: Optional[str] = "name"
    y_key: Optional[str] = "value"

class StepOutput(BaseModel):
    thought_process: str = Field(..., description="Internal reasoning and plan for this step.")
    content: str = Field(..., description="The main narrative response in Markdown.")
    metrics: Dict[str, Union[int, float, str]] = Field(default_factory=dict, description="Key Performance Indicators (e.g., 'Rows Processed': 150, 'Confidence': 'High').")
    insights: List[str] = Field(default_factory=list, description="Bullet points of key technical findings.")
    visualizations: List[Visualization] = Field(default_factory=list, description="Structured data for charts.")
    next_step_suggestion: Optional[str] = Field(None, description="Suggestion for what to do next.")
    aggregate_rows: List[Dict[str, Any]] = Field(default_factory=list, description="Primary SQL result rows (aggregated).")
    raw_rows: List[Dict[str, Any]] = Field(default_factory=list, description="Raw underlying rows when the primary query is aggregated.")

    @model_validator(mode='before')
    @classmethod
    def sanitize_data(cls, data: Any) -> Any:
        if data is None:
            return {"content": ""}
        if isinstance(data, str):
            return {"content": data}
        if not isinstance(data, dict):
            return {"content": str(data)}
            
        # --- Pre-processing: Map alternative fields to StepOutput schema ---
        # Handle "Report-style" JSON (e.g. schema_version, outcome, steps)
        
        # 1. Map Content
        if "content" not in data or not data["content"]:
            if "outcome" in data and isinstance(data["outcome"], dict):
                # Extract from outcome object
                outcome = data["outcome"]
                data["content"] = outcome.get("content", outcome.get("result", str(outcome)))
            elif "description" in data and isinstance(data["description"], str):
                # Fallback to description
                data["content"] = data["description"]
        
        # 2. Map Thought Process
        if "thought_process" not in data or not data["thought_process"]:
            thoughts = []
            if "title" in data:
                thoughts.append(f"Objective: {data['title']}")
            if "description" in data:
                thoughts.append(f"Context: {data['description']}")
            if "steps" in data and isinstance(data["steps"], list):
                thoughts.append("Steps executed:")
                for s in data["steps"]:
                    if isinstance(s, dict):
                        thoughts.append(f"- {s.get('name', 'Step')}: {s.get('details', '')}")
                    else:
                        thoughts.append(f"- {str(s)}")
            
            if thoughts:
                data["thought_process"] = "\n".join(thoughts)
            if thoughts:
                data["thought_process"] = "\n".join(thoughts)
            else:
                data["thought_process"] = "Processed request successfully."

        # 3. Map Schema-wrapped JSON (e.g. {schema: {fields: {...}}, content: ""})
        if "schema" in data and isinstance(data["schema"], dict):
            schema_obj = data["schema"]
            fields = schema_obj.get("fields", {})
            
            # Extract Metrics
            if "metrics" in fields:
                if "metrics" not in data or not data["metrics"]:
                    data["metrics"] = fields["metrics"]
            
            # Extract Insights
            if "insights" in fields:
                if "insights" not in data or not data["insights"]:
                    data["insights"] = fields["insights"]
            
            # Generate Content from Insights if empty
            if ("content" not in data or not data["content"]) and "insights" in data and data["insights"]:
                # Create a summary from insights
                insights_list = data["insights"]
                if isinstance(insights_list, list):
                    data["content"] = "### Analysis Results\n\n" + "\n".join([f"- {str(i)}" for i in insights_list])

        # 0. Sanitize Metrics
        if "metrics" in data:
            metrics = data["metrics"]
            if metrics is None:
                data["metrics"] = {}
            elif isinstance(metrics, dict):
                for k, v in metrics.items():
                    if v is None:
                        metrics[k] = "N/A"
                    elif isinstance(v, list):
                        metrics[k] = ", ".join(map(str, v))
                    elif isinstance(v, dict):
                        metrics[k] = str(v)
            elif isinstance(metrics, list):
                 new_metrics = {}
                 for item in metrics:
                     if isinstance(item, dict) and len(item) == 1:
                         k, v = list(item.items())[0]
                         new_metrics[k] = str(v) if isinstance(v, (list, dict)) else v
                 data["metrics"] = new_metrics
            else:
                data["metrics"] = {"raw_metrics": str(metrics)}
        else:
            data["metrics"] = {}

        # 1. Sanitize Insights
        if "insights" in data:
            insights = data["insights"]
            if insights is None:
                data["insights"] = []
            elif isinstance(insights, str):
                data["insights"] = [insights]
            elif isinstance(insights, dict):
                data["insights"] = [f"{k}: {v}" for k, v in insights.items()]
            elif isinstance(insights, list):
                new_insights = []
                for item in insights:
                    if item is None:
                        continue
                    if isinstance(item, dict):
                        new_insights.append(", ".join([f"{k}: {v}" for k, v in item.items()]))
                    elif isinstance(item, str):
                        new_insights.append(item)
                    else:
                        new_insights.append(str(item))
                data["insights"] = new_insights
            else:
                data["insights"] = [str(insights)]
        else:
            data["insights"] = []

        # 2. Sanitize Content (JSON to Markdown)
        # We process content first so that visualizations can append to it safely
        content_data = data.get("content")
        
        if content_data is None:
            data["content"] = ""
        else:
            parsed = None
            # If content is already a list or dict, use it directly
            if isinstance(content_data, (list, dict)):
                parsed = content_data
            
            # If content is a string, try to parse it as JSON
            elif isinstance(content_data, str):
                stripped = content_data.strip()
                if (stripped.startswith("{") and stripped.endswith("}")) or \
                   (stripped.startswith("[") and stripped.endswith("]")):
                    try:
                        import json
                        parsed = json.loads(stripped)
                    except Exception:
                        pass # Keep original string if parsing fails
            
            md_output = ""
            if parsed is not None:
                if isinstance(parsed, list):
                    # Convert list of dicts to Markdown Table
                    if len(parsed) > 0 and isinstance(parsed[0], dict):
                        # Check for "table" / "data" structure
                        is_structured = False
                        for item in parsed:
                            if isinstance(item, dict) and ("table" in item or "tableTitle" in item) and ("data" in item or "rows" in item):
                                is_structured = True
                                title = item.get("table", item.get("tableTitle", "Table"))
                                rows = item.get("data", item.get("rows", []))
                                headers = item.get("headers", [])
                                
                                if isinstance(rows, list) and len(rows) > 0:
                                    md_output += f"### {title}\n\n"
                                    
                                    # Determine headers if not provided
                                    if not headers:
                                        if isinstance(rows[0], dict):
                                            headers = list(rows[0].keys())
                                        elif isinstance(rows[0], list):
                                            headers = [f"Col {i+1}" for i in range(len(rows[0]))]
                                    
                                    md_output += "| " + " | ".join([str(h) for h in headers]) + " |\n"
                                    md_output += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                                    
                                    for row in rows:
                                        if isinstance(row, dict):
                                            md_output += "| " + " | ".join([str(row.get(h, "")) for h in headers]) + " |\n"
                                        elif isinstance(row, list):
                                            md_output += "| " + " | ".join([str(cell) for cell in row]) + " |\n"
                                    md_output += "\n"
                        
                        if not is_structured:
                            # Generic Table from list of dicts
                            headers = list(parsed[0].keys())
                            md_output += "| " + " | ".join(headers) + " |\n"
                            md_output += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                            for row in parsed:
                                md_output += "| " + " | ".join([str(row.get(h, "")) for h in headers]) + " |\n"
                    
                    elif len(parsed) > 0 and isinstance(parsed[0], str):
                        # List of strings -> Bullet list
                        for item in parsed:
                            md_output += f"- {item}\n"
                
                elif isinstance(parsed, dict):
                        # Convert dict to Markdown
                        for k, v in parsed.items():
                            # Case 1: Value is a list of strings (Bullet List)
                            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], str):
                                md_output += f"\n- **{k}**:\n"
                                for item in v:
                                    md_output += f"  - {item}\n"
                                md_output += "\n"
                            
                            # Case 2: Value is a list of dicts (Table)
                            elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                                md_output += f"\n### {k}\n\n"
                                
                                # Check if it's a nested table structure (e.g. list of tables)
                                is_nested_table = False
                                for item in v:
                                    if isinstance(item, dict) and ("data" in item or "rows" in item):
                                        # It's a list of tables!
                                        title = item.get("title", item.get("name", "Table"))
                                        rows = item.get("data", item.get("rows", []))
                                        if isinstance(rows, list) and len(rows) > 0:
                                            md_output += f"#### {title}\n\n"
                                            
                                            # Try to get headers from 'columns' key if it exists in the item
                                            headers = item.get("columns", [])
                                            
                                            if not headers:
                                                if isinstance(rows[0], dict):
                                                    headers = list(rows[0].keys())
                                                elif isinstance(rows[0], list):
                                                    headers = [f"Col {i+1}" for i in range(len(rows[0]))]
                                            
                                            md_output += "| " + " | ".join([str(h) for h in headers]) + " |\n"
                                            md_output += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                                            
                                            for row in rows:
                                                if isinstance(row, dict):
                                                    md_output += "| " + " | ".join([str(row.get(h, "")) for h in headers]) + " |\n"
                                                elif isinstance(row, list):
                                                    md_output += "| " + " | ".join([str(cell) for cell in row]) + " |\n"
                                            md_output += "\n"
                                        is_nested_table = True
                                
                                if not is_nested_table:
                                    # Standard Table
                                    headers = list(v[0].keys())
                                    md_output += "| " + " | ".join(headers) + " |\n"
                                    md_output += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                                    for row in v:
                                        md_output += "| " + " | ".join([str(row.get(h, "")) for h in headers]) + " |\n"
                                    md_output += "\n"
                            
                            # Case 3: Standard Key-Value
                            else:
                                md_output += f"- **{k}**: {v}\n"
            
            if md_output:
                data["content"] = md_output
            elif isinstance(content_data, (list, dict)):
                 # If conversion failed but it was a list/dict, force string conversion to avoid validation error
                 data["content"] = str(content_data)
            elif not isinstance(data.get("content"), str):
                 # Ensure content is string if it wasn't updated
                 data["content"] = str(content_data)
            else:
                # Minor formatting aid: if content contains a markdown table without leading newline,
                # prepend one to help renderers like ReactMarkdown+GFM detect the table.
                if isinstance(content_data, str) and "|" in content_data and not content_data.lstrip().startswith("|"):
                    data["content"] = "\n" + str(content_data)

        # 3. Sanitize Visualizations
        if "visualizations" in data:
            vis_data = data["visualizations"]
            valid_visualizations = []
            notes = []
            
            # Normalize to list
            if vis_data is None:
                vis_list = []
            elif isinstance(vis_data, (dict, str)):
                vis_list = [vis_data]
            elif isinstance(vis_data, list):
                vis_list = vis_data
            else:
                vis_list = []

            for vis in vis_list:
                if vis is None:
                    continue
                    
                if isinstance(vis, dict):
                    # Check for table_structure specifically
                    if "table_structure" in vis and isinstance(vis["table_structure"], list):
                        table_data = vis["table_structure"]
                        if len(table_data) > 0 and isinstance(table_data[0], dict):
                            # Convert to Markdown Table and append to Content
                            md_table = "\n\n### Table Structure\n\n"
                            headers = list(table_data[0].keys())
                            md_table += "| " + " | ".join(headers) + " |\n"
                            md_table += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                            for row in table_data:
                                md_table += "| " + " | ".join([str(row.get(h, "")) for h in headers]) + " |\n"
                            
                            data["content"] += md_table
                            continue # Don't add to valid visualizations

                    # Check for nested lists in keys like 'details', 'items', 'data', 'list'
                    nested_keys = ["details", "items", "data", "list", "content", "tables"]
                    found_nested_table = False
                    for key in nested_keys:
                        if key in vis and isinstance(vis[key], list) and len(vis[key]) > 0:
                            nested_list = vis[key]
                            
                            # Case 1: List of dicts (direct table data)
                            if isinstance(nested_list[0], dict) and not any(isinstance(v, (dict, list)) for v in nested_list[0].values()):
                                md_table = f"\n\n### {vis.get('name', vis.get('title', 'Data Details'))}\n\n"
                                headers = list(nested_list[0].keys())
                                md_table += "| " + " | ".join(headers) + " |\n"
                                md_table += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                                for row in nested_list:
                                    md_table += "| " + " | ".join([str(row.get(h, "")) for h in headers]) + " |\n"
                                
                                data["content"] += md_table
                                found_nested_table = True
                            
                            # Case 2: List of objects that CONTAIN content/data
                            else:
                                for item in nested_list:
                                    if isinstance(item, dict):
                                        for subkey in ["content", "data", "rows"]:
                                            if subkey in item and isinstance(item[subkey], list) and len(item[subkey]) > 0:
                                                sub_list = item[subkey]
                                                if isinstance(sub_list[0], dict):
                                                    title = item.get("name", item.get("title", item.get("description", "Table")))
                                                    md_table = f"\n\n### {title}\n\n"
                                                    
                                                    headers = item.get("columns", [])
                                                    if not headers:
                                                        headers = list(sub_list[0].keys())
                                                    
                                                    md_table += "| " + " | ".join([str(h) for h in headers]) + " |\n"
                                                    md_table += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                                                    for row in sub_list:
                                                        md_table += "| " + " | ".join([str(row.get(h, "")) for h in headers]) + " |\n"
                                                    
                                                    data["content"] += md_table
                                                    found_nested_table = True
                    
                    if found_nested_table:
                        if vis.get("type") not in ["bar", "pie", "line", "area"]:
                            notes.append(f"Visualization Note: Extracted tabular data from {vis.get('type', 'structure')}")
                            continue

                    # Normalize chart type aliases
                    if isinstance(vis.get("type"), str):
                        if vis["type"] in ["bar_chart", "barChart"]:
                            vis["type"] = "bar"
                        if vis["type"] in ["line_chart", "lineChart"]:
                            vis["type"] = "line"
                        if vis["type"] in ["area_chart", "areaChart"]:
                            vis["type"] = "area"

                    # Handle nested chart payloads like {"variance_analysis_chart": {...}}
                    nested_chart = None
                    if not vis.get("type"):
                        for key in ["variance_analysis_chart", "chart_data", "chart", "payload"]:
                            if key in vis and isinstance(vis[key], dict):
                                nested_chart = vis[key]
                                break
                    if nested_chart:
                        vis = nested_chart
                        # Normalize type if present
                        if vis.get("type") in ["bar_chart", "barChart"]:
                            vis["type"] = "bar"
                        if vis.get("type") in ["line_chart", "lineChart"]:
                            vis["type"] = "line"
                        if vis.get("type") in ["area_chart", "areaChart"]:
                            vis["type"] = "area"

                    # Allow table visualizations to pass through for UI rendering
                    if vis.get("type") == "table":
                        cols = vis.get("columns") or vis.get("headers") or []
                        rows = vis.get("values") or vis.get("data") or vis.get("rows") or []
                        if cols and rows:
                            valid_visualizations.append(
                                {
                                    "type": "table",
                                    "title": vis.get("title", vis.get("name", "Table")),
                                    "columns": cols,
                                    "rows": rows,
                                }
                            )
                            continue
                        # Fallback to note if structure missing
                        notes.append(f"Table Visualization: {vis.get('description', 'No description')}")
                        continue

                    # Normalize bar/line data structures with labels + datasets
                    if vis.get("type") in ["bar", "line", "area", "pie"]:
                        # Try to standardize to {type, title, data:{labels, datasets}}
                        if "data" not in vis:
                            # Build data from possible keys
                            x_axis = vis.get("x_axis") or vis.get("labels") or []
                            series = vis.get("series") or []
                            datasets = []
                            if isinstance(series, dict):
                                for name, arr in series.items():
                                    datasets.append({"label": name, "data": arr})
                            elif isinstance(series, list):
                                for s in series:
                                    if isinstance(s, dict) and "data" in s:
                                        datasets.append({"label": s.get("name") or s.get("label"), "data": s.get("data")})
                            vis["data"] = {"labels": x_axis, "datasets": datasets}
                        valid_visualizations.append(vis)
                        continue

                    # Check for other invalid types
                    if vis.get("type") not in ["bar", "pie", "line", "area", "table"]:
                        # If a note-only viz sneaks through, attach it to insights instead of visualizations
                        notes.append(f"Visualization Note ({vis.get('type', 'unknown')}): {vis.get('description', str(vis))}")
                        continue

                    # If it looks valid, keep it
                    valid_visualizations.append(vis)

                elif isinstance(vis, str):
                    notes.append(f"Visualization Note: {vis}")
            
            data["visualizations"] = valid_visualizations
            
            if notes:
                if "insights" not in data:
                    data["insights"] = []
                if isinstance(data["insights"], list):
                    data["insights"].extend(notes)

                    # Also append to content to ensure visibility in UI
                    note_text = "\n\n### Visualization Notes\n" + "\n".join([f"- {n}" for n in notes])
                    if "content" not in data:
                        data["content"] = ""
                    data["content"] += note_text
        else:
            data["visualizations"] = []

        return data
