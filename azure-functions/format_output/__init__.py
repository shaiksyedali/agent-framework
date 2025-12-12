"""
Azure Function: format_output

Formats step output for display in the UI.
Supports table, text, json, and markdown formats.
"""

import azure.functions as func
import logging
import json
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def format_as_table(data: Any) -> Dict[str, Any]:
    """Format data as a table structure."""
    if isinstance(data, list) and len(data) > 0:
        # List of dicts -> table
        if isinstance(data[0], dict):
            headers = list(data[0].keys())
            rows = [[row.get(h, "") for h in headers] for row in data]
            return {
                "type": "table",
                "headers": headers,
                "rows": rows,
                "row_count": len(rows)
            }
        # List of primitives -> single column table
        else:
            return {
                "type": "table",
                "headers": ["Value"],
                "rows": [[str(item)] for item in data],
                "row_count": len(data)
            }
    elif isinstance(data, dict):
        # Dict -> key-value table
        return {
            "type": "table",
            "headers": ["Key", "Value"],
            "rows": [[k, str(v)] for k, v in data.items()],
            "row_count": len(data)
        }
    else:
        return {
            "type": "table",
            "headers": ["Value"],
            "rows": [[str(data)]],
            "row_count": 1
        }


def format_as_text(data: Any) -> Dict[str, Any]:
    """Format data as plain text."""
    if isinstance(data, str):
        text = data
    elif isinstance(data, dict):
        lines = []
        for k, v in data.items():
            lines.append(f"**{k}**: {v}")
        text = "\n".join(lines)
    elif isinstance(data, list):
        text = "\n".join([f"• {item}" for item in data])
    else:
        text = str(data)
    
    return {
        "type": "text",
        "content": text,
        "length": len(text)
    }


def format_as_json(data: Any) -> Dict[str, Any]:
    """Format data as formatted JSON."""
    try:
        formatted = json.dumps(data, indent=2, default=str)
    except:
        formatted = str(data)
    
    return {
        "type": "json",
        "content": formatted,
        "parsed": data
    }


def format_as_markdown(data: Any) -> Dict[str, Any]:
    """Format data as markdown for rich display."""
    if isinstance(data, str):
        md = data
    elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        # Table from list of dicts
        headers = list(data[0].keys())
        md_lines = []
        md_lines.append("| " + " | ".join(headers) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in data:
            md_lines.append("| " + " | ".join([str(row.get(h, "")) for h in headers]) + " |")
        md = "\n".join(md_lines)
    elif isinstance(data, dict):
        md_lines = []
        for k, v in data.items():
            md_lines.append(f"- **{k}**: {v}")
        md = "\n".join(md_lines)
    elif isinstance(data, list):
        md = "\n".join([f"- {item}" for item in data])
    else:
        md = str(data)
    
    return {
        "type": "markdown",
        "content": md
    }


def extract_metrics(data: Any) -> Dict[str, Any]:
    """Extract key metrics from data for dashboard display."""
    metrics = {}
    
    if isinstance(data, list):
        metrics["count"] = len(data)
        if len(data) > 0 and isinstance(data[0], dict):
            # Try to find numeric columns for aggregation
            for key in data[0].keys():
                values = [row.get(key) for row in data if isinstance(row.get(key), (int, float))]
                if values:
                    metrics[f"{key}_sum"] = sum(values)
                    metrics[f"{key}_avg"] = sum(values) / len(values)
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (int, float)):
                metrics[k] = v
    
    return metrics


async def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Format step output for display.
    
    Expected input:
    {
        "data": <any>,
        "format": "table" | "text" | "json" | "markdown"
    }
    """
    logger.info("format_output triggered")
    
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json"
        )
    
    data = body.get("data")
    output_format = body.get("format", "text").lower()
    include_metrics = body.get("include_metrics", False)
    
    # Handle missing data gracefully - return a helpful message instead of error
    if data is None:
        logger.warning(f"format_output called without data. Received keys: {list(body.keys())}")
        # Return a graceful response instead of error
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "type": "text",
                "content": "No data to format. The previous step may not have returned any output.",
                "warning": "Data field was not provided by the calling agent"
            }),
            status_code=200,  # Return 200 to not break the flow
            mimetype="application/json"
        )
    
    # Format based on requested type
    formatters = {
        "table": format_as_table,
        "text": format_as_text,
        "json": format_as_json,
        "markdown": format_as_markdown
    }
    
    formatter = formatters.get(output_format, format_as_text)
    result = formatter(data)
    
    # Add metrics if requested
    if include_metrics:
        result["metrics"] = extract_metrics(data)
    
    result["success"] = True
    
    return func.HttpResponse(
        json.dumps(result, default=str),
        status_code=200,
        mimetype="application/json"
    )
