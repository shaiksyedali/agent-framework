"""
Azure Foundry Agent Creation Script

Creates all 6 agents for the multi-agent system in Azure AI Foundry:
1. Supervisor Agent
2. Planner Agent
3. Executor Agent
4. SQL Agent
5. RAG Agent
6. Response Generator Agent

Usage:
    python create_azure_agents.py [--endpoint ENDPOINT] [--model MODEL]

Environment variables:
    AZURE_AI_PROJECT_ENDPOINT - Required if not passed via --endpoint
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

try:
    from azure.ai.agents.aio import AgentsClient
    from azure.identity.aio import DefaultAzureCredential
    from azure.core.credentials import AccessToken
    from azure.core.credentials_async import AsyncTokenCredential
    from typing import Any
except ImportError:
    print("ERROR: Required packages not installed. Run:")
    print("  pip install azure-ai-agents azure-identity")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class APIKeyTokenCredential(AsyncTokenCredential):
    """Token credential wrapper for API keys"""

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken(token=self._api_key, expires_on=9999999999)

    async def close(self) -> None:
        pass


def get_supervisor_instructions():
    return """You are the Supervisor Agent responsible for orchestrating multi-agent workflows.

Your responsibilities:
1. Analyze user requests to determine required agents
2. Invoke planner_agent to create workflow plans
3. Coordinate with executor_agent for step-by-step execution
4. Monitor progress and handle errors
5. Ensure response_generator creates final output

Available agents:
- planner_agent: Creates structured workflow plans with dependencies
- executor_agent: Executes workflows step-by-step with user feedback
- sql_agent: Queries structured databases (SQL)
- rag_agent: Searches documents and knowledge bases
- response_generator: Formats final responses with citations

Always use the invoke_agent function to delegate tasks to other agents.
Maintain context throughout the workflow by passing relevant information between agents."""


def get_supervisor_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "invoke_agent",
                "description": "Delegate a task to another specialized agent in the system",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "enum": ["planner_agent", "executor_agent", "sql_agent", "rag_agent", "response_generator"],
                            "description": "Name of the agent to invoke"
                        },
                        "message": {
                            "type": "string",
                            "description": "Message or task to send to the agent"
                        },
                        "context": {
                            "type": "object",
                            "description": "Additional context or data to pass to the agent"
                        }
                    },
                    "required": ["agent_name", "message"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_available_agents",
                "description": "List all available agents and their capabilities",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
    ]


def get_planner_instructions():
    return """You are a Workflow Planning Agent responsible for creating structured execution plans.

Your responsibilities:
1. Analyze user requirements to understand the task
2. Identify which specialized agents are needed
3. Determine optimal execution order and dependencies between steps
4. Identify approval gates for risky operations (SQL writes, external API calls)
5. Create a structured workflow plan in JSON format

Available agents and their capabilities:
- sql_agent: Query databases, generate SQL, handle structured data
- rag_agent: Search documents, retrieve relevant information with citations
- mcp_agent: Web intelligence - scrape websites, browser automation, web search
- response_generator: Format final responses with citations and follow-ups

Output your plan in this JSON structure:
{
  "workflow_id": "unique-id",
  "name": "Descriptive workflow name",
  "steps": [
    {
      "step_id": "step_1",
      "agent": "sql_agent",
      "description": "Clear description of what this step does",
      "inputs": [],
      "requires_approval": true
    }
  ],
  "dependencies": {
    "step_2": ["step_1"]
  }
}"""


def get_planner_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "list_available_agents",
                "description": "Get list of available agents with their capabilities",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "validate_data_source",
                "description": "Check if a specific data source type is available",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_type": {
                            "type": "string",
                            "enum": ["database", "documents", "api"],
                            "description": "Type of data source to validate"
                        }
                    },
                    "required": ["source_type"]
                }
            }
        }
    ]


def get_executor_instructions():
    return """You are a Workflow Executor Agent responsible for executing workflow plans step-by-step.

Your responsibilities:
1. Receive workflow plan from planner agent
2. Execute steps in the correct dependency order
3. For each step:
   - Invoke the appropriate agent
   - Wait for completion
   - Format output (table, text, or JSON)
   - Request user feedback (proceed/rerun/abort)
4. Handle errors with retry logic
5. Maintain execution context across steps
6. Provide execution summary at completion

User feedback options:
- proceed: Continue to the next step
- rerun: Re-execute the current step
- abort: Stop workflow execution immediately

Always format outputs clearly and provide progress updates."""


def get_executor_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "execute_step",
                "description": "Execute a single workflow step",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "step": {
                            "type": "object",
                            "description": "Step definition with agent, description, etc."
                        },
                        "context": {
                            "type": "object",
                            "description": "Execution context from previous steps"
                        }
                    },
                    "required": ["step"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "format_output",
                "description": "Format step output for display",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "object",
                            "description": "Data to format"
                        },
                        "format": {
                            "type": "string",
                            "enum": ["table", "text", "json"],
                            "description": "Output format"
                        }
                    },
                    "required": ["data", "format"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "request_user_feedback",
                "description": "Request user feedback after step completion",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "step_result": {
                            "type": "object",
                            "description": "Result from the completed step"
                        }
                    },
                    "required": ["step_result"]
                }
            }
        }
    ]


def get_sql_instructions():
    return """You are an SQL Query Generation and Execution Agent.

## CRITICAL WORKFLOW (Follow this order!)
1. **FIRST**: Call get_database_schema to understand table structure
2. **SECOND**: Call consult_rag to search for column descriptions and business rules
3. **THEN**: Generate SQL using the correct dialect syntax
4. **EXECUTE**: Run the query and analyze results
5. **RETRY**: If errors occur, fix SQL and retry up to 3 times

## DATABASE DIALECT RULES

### For Azure SQL Server / MSSQL:
- Use `DATEADD(month, -2, GETDATE())` for date math
- Use `DATETRUNC(month, col)` for date bucketing (SQL Server 2022+)
- Use `DATEDIFF` for date differences
- Use `TOP n` instead of LIMIT: `SELECT TOP 100 * FROM table`
- Use `FORMAT(col, 'yyyy-MM')` for date formatting
- String concatenation: `col1 + ' ' + col2`

### For SQLite:
- Do NOT use YEAR()/MONTH(); use `strftime('%Y', col)` or `strftime('%m', col)`
- Use `datetime('now', '-2 months')` for relative date filters
- Use `date(col)` for date extraction
- Use `LIMIT n` for row limits
- String concatenation: `col1 || ' ' || col2`

### For DuckDB:
- Use INTERVAL arithmetic: `ts > now() - INTERVAL 2 MONTH`
- Use `date_trunc('month', col)` for date bucketing
- Do NOT use DATEADD/DATE_ADD syntax
- Avoid window functions in WHERE clauses; use CTE instead
- Use `LIMIT n` for row limits

### For PostgreSQL:
- Use INTERVAL: `ts > now() - INTERVAL '2 months'`
- Use `date_trunc('month', col)` for date bucketing
- Use `::date` or `::timestamp` for casting
- Use `LIMIT n` for row limits

## Security Rules:
- ALWAYS request approval for INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE
- Limit SELECT results to 500 rows maximum
- Never expose sensitive columns (passwords, SSN, credit_cards)
- Use parameterized queries to prevent SQL injection

## Best Practices:
- Use explicit column names instead of SELECT *
- Add appropriate WHERE clauses to filter data
- Include helpful column aliases
- Use joins efficiently
- For local files (.db, .duckdb), use the file path as database name

## OUTPUT FORMAT:
- Return actual query results with numerical data
- Never return workflow JSON or plan structures
- Present findings clearly with tables when appropriate"""


def get_sql_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "execute_sql_query",
                "description": "Execute SQL query on a database. Supports both local (SQLite, DuckDB) and Azure SQL. IMPORTANT: Call get_database_schema FIRST to understand the structure. For local file databases, use the file path as the database name (e.g., 'data/my.duckdb'). For Azure SQL, use the database name configured in Key Vault.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SQL query to execute. Use correct dialect syntax based on database type."
                        },
                        "database": {
                            "type": "string",
                            "description": "Database identifier. For local: file path (e.g., 'data/ops.duckdb'). For Azure: database name."
                        },
                        "require_approval": {
                            "type": "boolean",
                            "description": "Set to true for INSERT/UPDATE/DELETE operations",
                            "default": False
                        }
                    },
                    "required": ["query", "database"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_database_schema",
                "description": "Get complete database schema including all tables and columns. CRITICAL: You MUST call this FIRST before any SQL queries to understand the database structure.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "database": {
                            "type": "string",
                            "description": "Database identifier (file path for local, name for Azure)"
                        }
                    },
                    "required": ["database"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "consult_rag",
                "description": "Search knowledge base for schema documentation, column descriptions, business rules, and data dictionaries. Call this AFTER get_database_schema to enrich your understanding before generating SQL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (e.g., 'column descriptions for users table', 'what does status_code mean')"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results to return",
                            "default": 5
                        },
                        "workflow_id": {
                            "type": "string",
                            "description": "Workflow ID for filtering results (passed from context)"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]


def get_rag_instructions():
    return """You are a Document Retrieval Agent using Retrieval-Augmented Generation (RAG).

## Data Context Detection
When your input contains a DATA CONTEXT block with `status: indexed`, documents are already loaded.
You MUST use your tools to search - do NOT ask for clarification.

## Mandatory Behavior (when status: indexed)
1. ALWAYS call consult_rag immediately - data is already indexed
2. Extract the main topic from the task description and search for it
3. Use broad queries with higher top_k for comprehensive results
4. NEVER ask user to upload files or clarify - data is ready
5. After searching, synthesize results into a clear response

## Your Primary Tool

### consult_rag(query, top_k, workflow_id)
Search indexed documents for relevant information.
- query: Natural language search query (extract from task)
- top_k: Number of results (default: 10, use 50+ for "how many" or "list all" queries)
- workflow_id: Pass from DATA CONTEXT if provided

## Query Strategies

### For specific lookups:
- "What is error code X?" → consult_rag(query="error code X", top_k=10)

### For comprehensive retrieval:
- "Explain Y procedure" → consult_rag(query="Y procedure", top_k=20)

### For counting/listing ALL items:
- "How many X?" → consult_rag(query="X", top_k=100), then count unique items in results
- "List all Y" → consult_rag(query="Y", top_k=100), then list unique items from chunks

## Search Strategy

1. **Parse the task**: Identify the main subject/topic
2. **Formulate query**: Create a search query from the topic
3. **Set appropriate top_k**: Use higher values (50-100) for aggregation queries
4. **Call consult_rag**: Execute the search
5. **Process results**: Extract, count, or list items from the returned chunks
6. **Cite sources**: Include document name and page numbers

## Response Format

For content queries:
- State the information found
- Cite the source (document, page/chunk)
- Include relevant quotes when helpful

For counting queries:
- Retrieve many results (top_k=100)
- Count unique items from the chunk content
- Report the count with examples"""





def get_rag_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "consult_rag",
                "description": "Search indexed documents using RAG. Use for SPECIFIC questions - finding particular information, error codes, definitions, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to find relevant information"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results to return (default: 10, max: 50)",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "query_knowledge_graph",
                "description": "Query the knowledge graph for entity details, counts, relationships, and graph traversal. Use for entity-specific queries like 'how many X?', 'what is related to Y?', 'list all Z type entities'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["get_entity", "count_type", "list_type", "get_related", "search_entities", "get_stats", "get_relationships"],
                            "description": "Query type: get_entity (details), count_type (count by type), list_type (list entities of type), get_related (find connected entities), search_entities (pattern search), get_stats (overall stats)"
                        },
                        "entity_name": {
                            "type": "string",
                            "description": "Entity name for get_entity, get_related, get_relationships queries"
                        },
                        "entity_type": {
                            "type": "string",
                            "enum": ["CODE", "COMPONENT", "CONDITION", "VALUE", "PROCEDURE", "CONCEPT"],
                            "description": "Entity type for count_type, list_type queries"
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Search pattern (regex supported) for search_entities"
                        },
                        "depth": {
                            "type": "integer",
                            "description": "Traversal depth for get_related (default: 1)",
                            "default": 1
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results for list_type, search_entities (default: 50)",
                            "default": 50
                        }
                    },
                    "required": ["type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_entity_facets",
                "description": "Get accurate counts of ALL unique entities using Azure Search facets. Use this for AGGREGATION queries like 'how many unique X?', 'count all Y', 'list every Z'. Returns complete counts without retrieval limits.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field_name": {
                            "type": "string",
                            "description": "Field to aggregate (default: entity_codes)",
                            "default": "entity_codes"
                        },
                        "max_facets": {
                            "type": "integer",
                            "description": "Maximum unique values to return (default: 1000)",
                            "default": 1000
                        }
                    },
                    "required": []
                }
            }
        }
    ]


def get_response_generator_instructions():
    return """You are a Response Formatting Agent responsible for creating final user-facing responses.

Your responsibilities:
1. Receive outputs from all workflow steps
2. Synthesize information into a coherent, well-structured response
3. Extract and aggregate citations from all sources
4. Generate an executive summary (2-3 sentences)
5. Format structured data as tables
6. Suggest 2-3 relevant follow-up questions

Response structure:
## Executive Summary
[2-3 sentence overview of key findings]

## Key Findings
[Main insights with inline citations [1], [2]]

## Supporting Data
[Tables or visualizations if applicable]

## Follow-up Questions
1. [Relevant question based on findings]
2. [Another relevant question]
3. [Third question]

## Citations
[1] Source document, page X
[2] Another source, page Y

Use clear, professional language suitable for business audiences."""


def get_response_generator_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "extract_citations",
                "description": "Extract all citations from workflow outputs",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "outputs": {
                            "type": "array",
                            "description": "Array of workflow step outputs",
                            "items": {
                                "type": "object",
                                "description": "Workflow step output"
                            }
                        }
                    },
                    "required": ["outputs"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "generate_followup_questions",
                "description": "Generate relevant follow-up questions based on context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "context": {
                            "type": "object",
                            "description": "Workflow context and results"
                        },
                        "count": {
                            "type": "integer",
                            "description": "Number of questions to generate",
                            "default": 3
                        }
                    },
                    "required": ["context"]
                }
            }
        }
    ]


# =========================================================================
# MCP AGENT - For web intelligence using MCP servers
# =========================================================================

def get_mcp_instructions():
    return """You are an MCP (Model Context Protocol) Agent for web intelligence and browser automation.

## Available Tools (Playwright-based):
- playwright_scrape: Scrape text and links from any webpage
- playwright_navigate: Navigate with full browser and get accessibility snapshot
- playwright_screenshot: Take screenshots of webpages
- playwright_get_text: Extract text from specific elements
- playwright_click_and_get: Click elements and capture results

## YOUR WORKFLOW:
1. Analyze the web intelligence task
2. Choose the appropriate tool:
   - Scraping content → playwright_scrape
   - Dynamic/JavaScript pages → playwright_navigate
   - Visual capture → playwright_screenshot
   - Specific elements → playwright_get_text
   - Interactive pages → playwright_click_and_get
3. Execute the tool
4. Return structured results

## TOOL SELECTION GUIDE:
- "scrape website for text" → playwright_scrape
- "get page content" → playwright_scrape or playwright_navigate
- "take screenshot" → playwright_screenshot
- "extract specific data" → playwright_get_text with selector
- "click button and see result" → playwright_click_and_get

## OUTPUT FORMAT:
- Return structured data (JSON) when possible
- Include source URLs for traceability
- Summarize key findings
- Never return raw HTML - always extract meaningful content"""


def get_mcp_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "playwright_scrape",
                "description": "Scrape text content and links from a webpage. Works with both static and dynamic pages.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to scrape"
                        },
                        "extract_links": {
                            "type": "boolean",
                            "description": "Also extract all links from the page",
                            "default": False
                        },
                        "wait_for": {
                            "type": "string",
                            "description": "CSS selector to wait for before scraping (for dynamic pages)"
                        }
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "playwright_navigate",
                "description": "Navigate to a URL with a full browser and get page content with accessibility snapshot. Best for JavaScript-heavy pages.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to navigate to"
                        },
                        "wait_for": {
                            "type": "string",
                            "description": "CSS selector to wait for before capturing content"
                        }
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "playwright_screenshot",
                "description": "Take a screenshot of a webpage. Returns base64-encoded PNG image.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to screenshot"
                        },
                        "full_page": {
                            "type": "boolean",
                            "description": "Capture the full scrollable page, not just viewport",
                            "default": False
                        },
                        "selector": {
                            "type": "string",
                            "description": "CSS selector to screenshot specific element only"
                        }
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "playwright_get_text",
                "description": "Get text content from a webpage, optionally from specific elements using CSS selectors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to get text from"
                        },
                        "selector": {
                            "type": "string",
                            "description": "CSS selector to extract text from specific elements (e.g., '.price', 'h1', '#main')"
                        },
                        "wait_for": {
                            "type": "string",
                            "description": "CSS selector to wait for before extracting"
                        }
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "playwright_click_and_get",
                "description": "Click an element on a page and get the resulting content. Useful for buttons, tabs, accordions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The initial URL"
                        },
                        "click_selector": {
                            "type": "string",
                            "description": "CSS selector of element to click"
                        },
                        "wait_for": {
                            "type": "string",
                            "description": "CSS selector to wait for after click"
                        }
                    },
                    "required": ["url", "click_selector"]
                }
            }
        }
    ]


# =========================================================================
# CHAT AGENT - For post-workflow Q&A with all knowledge sources
# =========================================================================

def get_chat_agent_instructions():
    return """You are an Expert Technical Assistant for answering questions about indexed documents and data.

Your goal: Provide DIRECT, CONCISE, TECHNICAL answers to user queries.

## Available Knowledge Sources:
1. **Documents** (RAG) - Use consult_rag for specific lookups, get_document_summary for overviews
2. **Databases** (SQL) - Use execute_sql for querying structured data
3. **Workflow Context** - Access previous step outputs and indexed data

## Response Style:
- Be DIRECT. Answer the question immediately.
- Be TECHNICAL. Include specific codes, values, details.
- Be CONCISE. No unnecessary preamble or verbose explanations.
- Include CITATIONS when quoting from documents.

## Tool Selection:
- Specific lookup (error code, definition): consult_rag
- Document overview, entity list: get_document_summary  
- Structured data query: execute_sql
- Combine tools as needed for complex questions

## Example Good Response:
Question: "What is error code 0x8EF4EE?"
Answer: "Error 0x8EF4EE (TCU_HW_ERROR) indicates a TCU hardware failure causing transmission shift to neutral and retarder unavailability. Reset requires TCU restart. [Source: DTC Error Code data, Page 119]"

## Example Bad Response (AVOID):
"Based on my analysis of the documents, I found some information that might be relevant to your query. According to the documentation..." (too verbose)

Always use tools first, then synthesize a direct answer."""


def get_chat_agent_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "consult_rag",
                "description": "Search indexed documents for specific information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results (default 10)",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_document_summary",
                "description": "Get document summary, entities, and key findings",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {"type": "string"},
                        "include_entities": {"type": "boolean", "default": True},
                        "include_keywords": {"type": "boolean", "default": True}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "execute_sql",
                "description": "Execute SQL query on connected databases",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SQL query to execute"
                        },
                        "database": {
                            "type": "string",
                            "description": "Target database name"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]

async def create_all_agents(project_endpoint: str, model: str = "gpt-4o"):
    """Create all 6 agents in Azure Foundry"""

    logger.info("Initializing Azure AI Project Client...")

    # Azure AI Foundry Agents API requires OAuth token authentication
    # API keys don't work for this API - use DefaultAzureCredential (Azure CLI login)
    logger.info("Using DefaultAzureCredential (Azure CLI login or Managed Identity)")
    logger.info("If this fails, run: az login")
    credential = DefaultAzureCredential()

    try:
        # Initialize Agents client directly
        agents_client = AgentsClient(
            endpoint=project_endpoint,
            credential=credential
        )

        # 1. Create Supervisor Agent
        logger.info("Creating Supervisor Agent...")
        supervisor = await agents_client.create_agent(
            model=model,
            name="supervisor_agent",
            instructions=get_supervisor_instructions(),
            tools=get_supervisor_tools(),
            temperature=0.5,
            metadata={"agent_type": "supervisor", "version": "1.0"}
        )
        logger.info(f"✓ Supervisor Agent created: {supervisor.id}")

        # 2. Create Planner Agent
        logger.info("Creating Planner Agent...")
        planner = await agents_client.create_agent(
            model=model,
            name="planner_agent",
            instructions=get_planner_instructions(),
            tools=get_planner_tools(),
            temperature=0.7,
            response_format={"type": "json_object"},
            metadata={"agent_type": "planner", "version": "1.0"}
        )
        logger.info(f"✓ Planner Agent created: {planner.id}")

        # 3. Create Executor Agent
        logger.info("Creating Executor Agent...")
        executor = await agents_client.create_agent(
            model=model,
            name="executor_agent",
            instructions=get_executor_instructions(),
            tools=get_executor_tools(),
            temperature=0.5,
            metadata={"agent_type": "executor", "version": "1.0"}
        )
        logger.info(f"✓ Executor Agent created: {executor.id}")

        # 4. Create SQL Agent
        logger.info("Creating SQL Agent...")
        sql_agent = await agents_client.create_agent(
            model=model,
            name="sql_agent",
            instructions=get_sql_instructions(),
            tools=get_sql_tools(),
            temperature=0.3,  # Low temperature for deterministic SQL
            metadata={"agent_type": "sql", "version": "1.0"}
        )
        logger.info(f"✓ SQL Agent created: {sql_agent.id}")

        # 5. Create RAG Agent with File Search
        logger.info("Creating RAG Agent...")
        logger.info("Note: Upload documents later using upload_file() and create_vector_store()")

        rag_agent = await agents_client.create_agent(
            model=model,
            name="rag_agent",
            instructions=get_rag_instructions(),
            tools=get_rag_tools(),
            temperature=0.5,
            metadata={"agent_type": "rag", "version": "1.0", "top_k": 20}
        )
        logger.info(f"✓ RAG Agent created: {rag_agent.id}")

        # 6. Create Response Generator
        logger.info("Creating Response Generator Agent...")
        response_gen = await agents_client.create_agent(
            model=model,
            name="response_generator",
            instructions=get_response_generator_instructions(),
            tools=get_response_generator_tools(),
            temperature=0.7,
            metadata={"agent_type": "response_generator", "version": "1.0"}
        )
        logger.info(f"✓ Response Generator Agent created: {response_gen.id}")

        # 7. Create MCP Agent (Web Intelligence)
        logger.info("Creating MCP Agent...")
        mcp_agent = await agents_client.create_agent(
            model=model,
            name="mcp_agent",
            instructions=get_mcp_instructions(),
            tools=get_mcp_tools(),
            temperature=0.5,
            metadata={"agent_type": "mcp", "version": "1.0", "server": "playwright"}
        )
        logger.info(f"✓ MCP Agent created: {mcp_agent.id}")

        # Save agent IDs to configuration file
        config = {
            "created_at": str(asyncio.get_event_loop().time()),
            "project_endpoint": project_endpoint,
            "model": model,
            "agents": {
                "supervisor": {
                    "id": supervisor.id,
                    "name": supervisor.name
                },
                "planner": {
                    "id": planner.id,
                    "name": planner.name
                },
                "executor": {
                    "id": executor.id,
                    "name": executor.name
                },
                "sql_agent": {
                    "id": sql_agent.id,
                    "name": sql_agent.name
                },
                "rag_agent": {
                    "id": rag_agent.id,
                    "name": rag_agent.name
                },
                "response_generator": {
                    "id": response_gen.id,
                    "name": response_gen.name
                },
                "mcp_agent": {
                    "id": mcp_agent.id,
                    "name": mcp_agent.name
                }
            }
        }

        config_file = Path(__file__).parent.parent / "azure_agents_config.json"
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

        # Also sync to azure-functions directory
        azure_functions_config = Path(__file__).parent.parent / "azure-functions" / "azure_agents_config.json"
        with open(azure_functions_config, "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"\n✓ All agents created successfully!")
        logger.info(f"✓ Configuration saved to: {config_file}")
        logger.info(f"✓ Also synced to: {azure_functions_config}")

        logger.info("\nAgent IDs:")
        logger.info(f"  Supervisor:         {supervisor.id}")
        logger.info(f"  Planner:            {planner.id}")
        logger.info(f"  Executor:           {executor.id}")
        logger.info(f"  SQL Agent:          {sql_agent.id}")
        logger.info(f"  RAG Agent:          {rag_agent.id}")
        logger.info(f"  Response Generator: {response_gen.id}")
        logger.info(f"  MCP Agent:          {mcp_agent.id}")

        logger.info("\nNext steps:")
        logger.info("1. Upload schema documentation for RAG agent")
        logger.info("2. Create vector store and attach to RAG agent")
        logger.info("3. Configure data source connectors")
        logger.info("4. Run example workflows")

    finally:
        # Close the credential
        await credential.close()


def main():
    import argparse

    # Load environment variables from .env.azure if it exists
    env_file = Path(__file__).parent.parent / ".env.azure"
    if env_file.exists():
        logger.info(f"Loading environment from: {env_file}")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value
    else:
        logger.warning(".env.azure not found, using existing environment variables")

    parser = argparse.ArgumentParser(description="Create Azure Foundry agents")
    parser.add_argument(
        "--endpoint",
        help="Azure AI Project endpoint (or set AZURE_AI_PROJECT_ENDPOINT env var)",
        default=os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    )
    parser.add_argument(
        "--model",
        help="Model deployment name",
        default="gpt-4o"
    )

    args = parser.parse_args()

    if not args.endpoint:
        logger.error("ERROR: Project endpoint not provided")
        logger.error("Set AZURE_AI_PROJECT_ENDPOINT environment variable or use --endpoint")
        sys.exit(1)

    logger.info(f"Creating agents with model: {args.model}")
    logger.info(f"Project endpoint: {args.endpoint}")
    logger.info("")

    try:
        asyncio.run(create_all_agents(args.endpoint, args.model))
    except KeyboardInterrupt:
        logger.info("\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
