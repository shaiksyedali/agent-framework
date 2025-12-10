"""
Planner Service for Azure Foundry Workflows.
Calls Azure Planner Agent (cloud) to create workflow plans.
REFACTORED: Uses Azure AI Foundry AgentsClient (not OpenAI Assistants API).
"""

import json
import logging
import os
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional

from azure.identity.aio import DefaultAzureCredential
from azure.ai.agents.aio import AgentsClient

from .models import WorkflowConfig, AgentConfig, DataSourceConfig, StepConfig

logger = logging.getLogger(__name__)

class PlannerService:
    """Service for generating Azure Foundry workflows using Azure Planner Agent."""

    def __init__(self, azure_agents_config_path: str = None):
        if azure_agents_config_path is None:
            # Default path
            azure_agents_config_path = Path(__file__).parent.parent.parent.parent.parent.parent / "azure_agents_config.json"

        with open(azure_agents_config_path) as f:
            self.azure_config = json.load(f)

        # Get Azure AI Foundry project endpoint
        self.project_endpoint = os.getenv(
            "AZURE_AI_PROJECT_ENDPOINT",
            self.azure_config.get("project_endpoint")
        )

        # Get Planner Agent ID - Handle 'planner' vs 'planner_agent' key
        agents_map = self.azure_config.get("agents", {})
        if "planner" in agents_map:
            self.planner_agent_id = agents_map["planner"]["id"]
        elif "planner_agent" in agents_map:
            self.planner_agent_id = agents_map["planner_agent"]["id"]
        else:
            raise ValueError("Planner agent not found in configuration (checked 'planner' and 'planner_agent').")
        
        logger.info(f"Planner Service initialized with Azure Planner Agent: {self.planner_agent_id}")
        logger.info(f"Using AI Foundry endpoint: {self.project_endpoint}")
        
        # Initialize Client (will be done lazily)
        self.client = None
        self._credential = None

    async def _init_client(self):
        """Initialize AI Foundry AgentsClient lazily"""
        if self.client is not None:
            return
            
        try:
            if not self.project_endpoint:
                raise ValueError("AZURE_AI_PROJECT_ENDPOINT not set")
            
            # Use DefaultAzureCredential for AI Foundry
            self._credential = DefaultAzureCredential()
            self.client = AgentsClient(
                endpoint=self.project_endpoint,
                credential=self._credential
            )
            logger.info("AI Foundry AgentsClient initialized")
        except Exception as e:
            logger.error(f"Failed to init AI Foundry client in Planner: {e}")
            self.client = None

    async def cleanup(self):
        """Cleanup resources"""
        if self._credential:
            await self._credential.close()


    async def _run_planner_agent(self, prompt: str) -> str:
        """Run the Planner Agent via Azure AI Foundry AgentsClient"""
        # Initialize client lazily
        await self._init_client()
        
        if not self.client:
            raise ValueError("AI Foundry AgentsClient not initialized")

        try:
            # Create Thread using AI Foundry SDK
            thread = await self.client.threads.create()
            
            # Add Message
            await self.client.messages.create(
                thread_id=thread.id,
                role="user",
                content=prompt
            )
            
            # Create and process Run (AI Foundry SDK has a different API)
            run = await self.client.runs.create(
                thread_id=thread.id,
                agent_id=self.planner_agent_id
            )
            
            # Poll for completion
            while True:
                await asyncio.sleep(1)
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
                    return ""
                
                elif run.status == "requires_action":
                    # Handle tool calls
                    tool_outputs = []
                    if run.required_action and run.required_action.submit_tool_outputs:
                         for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                             if tool_call.function.name == "list_available_agents":
                                 agents_list = [v.get("name") for k,v in self.azure_config["agents"].items()]
                                 tool_outputs.append({
                                     "tool_call_id": tool_call.id,
                                     "output": json.dumps(agents_list)
                                 })
                             else:
                                 tool_outputs.append({
                                     "tool_call_id": tool_call.id,
                                     "output": "Tool execution not supported in planning phase."
                                 })
                         
                         await self.client.runs.submit_tool_outputs(
                            thread_id=thread.id,
                            run_id=run.id,
                            tool_outputs=tool_outputs
                        )

                elif run.status in ["failed", "cancelled", "expired"]:
                    error_msg = run.last_error if hasattr(run, 'last_error') else "Unknown error"
                    raise ValueError(f"Planner run failed: {error_msg}")

        except Exception as e:
            logger.error(f"Planner Agent Run Error: {e}")
            raise

    async def create_workflow_plan(
        self,
        user_request: str,
        data_sources_hint: Optional[List[Dict[str, Any]]] = None
    ) -> WorkflowConfig:
        """
        Generate a workflow plan using Azure Planner Agent.
        """
        logger.info(f"Creating workflow plan for: {user_request}")

        # Convert data sources hint to structured format
        data_sources = []
        if data_sources_hint:
             for ds_dict in data_sources_hint:
                data_sources.append({
                    "name": ds_dict.get("name", "Unnamed Source"),
                    "type": ds_dict.get("type", "unknown")
                })

        # Format prompt
        prompt = f"""Create a detailed workflow plan for the following request:

User Intent: {user_request}

Available Data Sources:
{json.dumps(data_sources, indent=2)}

Available Agents: supervisor_agent, planner_agent, executor_agent, sql_agent, rag_agent, response_generator

Please analyze the request and data sources, then return a complete workflow plan in JSON format.
The plan must be valid JSON matching this schema:
{{
  "workflow_id": "unique-id",
  "name": "Descriptive Name",
  "description": "Short description",
  "steps": [
      {{
          "step_id": "step_1",
          "step_name": "Step Name",
          "agent": "sql_agent",
          "description": "High-level description of what this step does",
          "instructions": "DETAILED, VERBOSE instructions (prompt) for the agent. Include specific questions to ask or tables to query.",
          "requires_approval": true
      }}
  ]
}}

CRITICAL: Return ONLY the JSON. Ensure 'instructions' are very detailed and useful for the agent."""

        try:
            logger.info(f"Calling Azure Planner Agent...")
            
            content = await self._run_planner_agent(prompt)
            
            if not content:
                 raise ValueError("Empty response from Planner Agent")

            logger.info(f"Planner response (first 200 chars): {content[:200]}")

            # Parse JSON
            plan_json = None
            try:
                plan_json = json.loads(content)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
                if json_match:
                    plan_json = json.loads(json_match.group(1))
                else:
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        plan_json = json.loads(json_match.group(0))

            if not plan_json:
                logger.error("Failed to parse plan from response")
                plan_json = self._create_fallback_plan(user_request, data_sources)

            # Convert to WorkflowConfig
            workflow = self._convert_plan_to_workflow(plan_json, user_request, data_sources_hint)

            logger.info(f"Workflow plan created: {workflow.name}")
            return workflow

        except Exception as e:
            logger.error(f"Error calling Azure Planner Agent: {e}", exc_info=True)
            fallback_plan = self._create_fallback_plan(user_request, data_sources)
            return self._convert_plan_to_workflow(fallback_plan, user_request, data_sources_hint)

    def _convert_plan_to_workflow(
        self,
        plan_json: Dict[str, Any],
        user_request: str,
        data_sources_hint: Optional[List[Dict[str, Any]]]
    ) -> WorkflowConfig:
        
        # Build AgentConfig objects
        # We need to include ALL agents mentioned in the plan
        azure_agents = []
        known_agents = self.azure_config.get("agents", {})
        
        # Helper to find agent config by key or name
        def get_agent_config(key_or_name):
             if key_or_name in known_agents:
                 return known_agents[key_or_name]
             # Search by name
             for k, v in known_agents.items():
                 if v.get("name") == key_or_name:
                     return v
             return None

        # Track added agents to avoid duplicates
        added_agent_ids = set()

        # Always add supervisor if available
        sup_conf = get_agent_config("supervisor") or get_agent_config("supervisor_agent")
        if sup_conf:
             azure_agents.append(AgentConfig(
                id=sup_conf["id"],
                name=sup_conf.get("name", "Supervisor"),
                role="Supervisor",
                instructions="Supervisor",
                model_name="gpt-4o",
                model_provider="azure",
                is_azure=True,
                is_editable=False
            ))
             added_agent_ids.add(sup_conf["id"])

        # Convert data sources
        data_sources = []
        if data_sources_hint:
            for ds_dict in data_sources_hint:
                data_sources.append(DataSourceConfig(**ds_dict))

        # Convert steps
        steps_config = []
        for i, step in enumerate(plan_json.get("steps", []), 1):
            agent_key = step.get("agent")
            agent_id = None
            
            ag_conf = get_agent_config(agent_key)
            if ag_conf:
                agent_id = ag_conf["id"]
                # Add this agent to the workflow's agent list if not present
                if agent_id not in added_agent_ids:
                    azure_agents.append(AgentConfig(
                        id=agent_id,
                        name=ag_conf.get("name", agent_key),
                        role=agent_key,
                        instructions=step.get("instructions", "Execute this step."),
                        model_name="gpt-4o",
                        model_provider="azure",
                        is_azure=True,
                        is_editable=False
                    ))
                    added_agent_ids.add(agent_id)
            
            steps_config.append(StepConfig(
                id=step.get("step_id", f"step_{i}"),
                name=step.get("step_name", f"Step {i}"),
                type="agent_call",
                agent_id=agent_id or agent_key, # Fallback to name if not found
                input_template=step.get("instructions", "{input}"), # Use parsed instructions as template
                output_key="result",
                description=step.get("description", ""),
                requires_approval=step.get("requires_approval", True) # Default to True for HIL
            ))

        return WorkflowConfig(
            name=plan_json.get("name", "AI-Generated Workflow"),
            description=plan_json.get("description", user_request[:200]),
            user_intent=user_request,
            agents=azure_agents,
            data_sources=data_sources,
            steps=steps_config,
            is_azure_workflow=True
        )

    def _create_fallback_plan(self, user_request: str, data_sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Simple fallback
        return {
            "workflow_id": "fallback",
            "name": "Fallback Plan",
            "steps": [
                {
                    "step_id": "step_1",
                    "step_name": "Response",
                    "agent": "response_generator",
                    "description": "Generate response",
                    "requires_approval": False
                }
            ]
        }
    
    async def close(self):
        if hasattr(self, 'client') and self.client:
            await self.client.close()
