"""Workflow Planner Agent for creating and structuring multi-agent workflows."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List
from uuid import uuid4

from agent_framework._agents import ChatAgent
from agent_framework._clients import ChatClientProtocol
from agent_framework._tools import ai_function
from agent_framework.orchestrator.approvals import ApprovalType
from agent_framework.orchestrator.context import OrchestrationContext
from agent_framework.orchestrator.graph import StepDefinition, StepGraph
from agent_framework.schemas.workflow_plan import (
    WorkflowInput,
    WorkflowPlan,
    WorkflowStep,
)

logger = logging.getLogger(__name__)


class WorkflowPlannerAgent:
    """Agent that plans workflows based on user requirements.

    Creates both human-readable plans and executable StepGraphs. Analyzes
    user requirements to determine optimal agent selection, execution order,
    and approval gates.

    Example:
        >>> planner = WorkflowPlannerAgent(
        ...     chat_client=client,
        ...     available_agents={
        ...         "structured_data": "Query databases with SQL",
        ...         "rag": "Search documents and knowledge bases"
        ...     }
        ... )
        >>> workflow_input = WorkflowInput(
        ...     name="Sales Analysis",
        ...     description="Analyze Q4 sales data",
        ...     user_prompt="What were our top products last quarter?",
        ...     workflow_steps=["Query sales database", "Generate report"],
        ...     data_sources={"database": connector}
        ... )
        >>> plan = await planner.plan_workflow(workflow_input)
        >>> graph = planner.build_step_graph(plan, context)
    """

    def __init__(
        self,
        chat_client: ChatClientProtocol,
        available_agents: Dict[str, str] | None = None,
        *,
        name: str = "workflow_planner",
    ):
        """Initialize the Workflow Planner Agent.

        Args:
            chat_client: Chat client for LLM-powered planning
            available_agents: Dictionary mapping agent types to descriptions
                (e.g., {"structured_data": "Query databases", "rag": "Search documents"})
            name: Agent name
        """
        self.available_agents = available_agents or {
            "structured_data": "Query structured databases (SQL)",
            "rag": "Search unstructured documents via semantic search",
        }
        self.name = name

        # Create planning tools
        planning_tools = self._create_planning_tools()

        # Create ChatAgent with planning instructions
        self.agent = ChatAgent(
            chat_client=chat_client,
            name=name,
            instructions=self._build_instructions(),
            tools=planning_tools,
        )

    def _build_instructions(self) -> str:
        """Build instructions for the planning agent."""
        agents_list = "\n".join(
            [f"- {agent_type}: {desc}" for agent_type, desc in self.available_agents.items()]
        )

        return f"""
You are an expert workflow planner. Your role is to analyze user requirements
and create structured execution plans for multi-agent workflows.

## Available Agents

{agents_list}

## Your Responsibilities

1. Analyze user requirements (name, description, prompt, steps, data sources)
2. Identify which agents are needed from the available agents above
3. Determine the optimal execution order and dependencies
4. Identify approval gates (SQL queries, risky operations)
5. Create a structured plan with clear steps

## Planning Guidelines

- Create modular steps with clear boundaries
- Minimize unnecessary data passing between steps
- Place approval gates BEFORE risky operations (SQL writes, external API calls)
- Include fallback strategies for potential errors
- Specify expected inputs and outputs for each step
- Consider dependencies: some steps may need results from previous steps

## Output Format

Provide your plan as a JSON object with this structure:
{{
    "steps": [
        {{
            "step_id": "unique_id",
            "step_name": "Human-readable name",
            "agent_type": "structured_data|rag|custom",
            "description": "What this step does",
            "inputs": ["dependency_step_id"],  // empty if no dependencies
            "requires_approval": true|false,
            "estimated_outputs": "Description of expected output"
        }}
    ],
    "data_flow": {{
        "step_id": ["dependent_step_ids"]
    }},
    "reasoning": "Brief explanation of your planning decisions"
}}

Ensure that steps have logical dependencies and approval is requested for operations
that modify data or access external resources.
"""

    def _create_planning_tools(self) -> List:
        """Create tools for the planning agent."""
        tools = []

        @ai_function
        def list_available_agents() -> str:
            """List all available agents and their capabilities."""
            result = "Available Agents:\n"
            for agent_type, description in self.available_agents.items():
                result += f"- {agent_type}: {description}\n"
            return result

        @ai_function
        def get_agent_capabilities(agent_type: str) -> str:
            """Get detailed capabilities for a specific agent type.

            Args:
                agent_type: The type of agent (e.g., 'structured_data', 'rag')

            Returns:
                Description of agent capabilities
            """
            if agent_type in self.available_agents:
                base_desc = self.available_agents[agent_type]

                # Add detailed capabilities based on agent type
                if agent_type == "structured_data":
                    return (
                        f"{base_desc}\n\n"
                        "Capabilities:\n"
                        "- Generates SQL queries from natural language\n"
                        "- Supports SQLite, DuckDB, and PostgreSQL\n"
                        "- Automatic retry on errors (up to 3 attempts)\n"
                        "- Detects aggregations and fetches raw records\n"
                        "- Can consult RAG for schema documentation\n"
                        "- Enforces write protection and row limits\n"
                    )
                elif agent_type == "rag":
                    return (
                        f"{base_desc}\n\n"
                        "Capabilities:\n"
                        "- Semantic search over vector store\n"
                        "- Configurable number of results (default: 20)\n"
                        "- Returns results with citations and metadata\n"
                        "- Supports document chunk retrieval\n"
                    )
                return base_desc
            return f"Unknown agent type: {agent_type}"

        @ai_function
        def validate_data_source(source_type: str) -> str:
            """Check if a data source type is available.

            Args:
                source_type: Type of data source (e.g., 'database', 'documents', 'api')

            Returns:
                Validation result message
            """
            valid_sources = {
                "database": "structured_data",
                "documents": "rag",
                "vector_store": "rag",
            }

            if source_type in valid_sources:
                agent = valid_sources[source_type]
                return f"Data source '{source_type}' is supported by {agent} agent"
            return f"Data source '{source_type}' may require custom implementation"

        tools.extend([list_available_agents, get_agent_capabilities, validate_data_source])
        return tools

    async def plan_workflow(
        self,
        workflow_input: WorkflowInput,
    ) -> WorkflowPlan:
        """Generate workflow plan from user input.

        Args:
            workflow_input: User requirements and configuration

        Returns:
            WorkflowPlan with both human-readable plan and structured steps
        """
        logger.info(f"Planning workflow: {workflow_input.name}")

        # Build planning prompt
        analysis_prompt = self._build_analysis_prompt(workflow_input)

        # Get plan from ChatAgent
        response = await self.agent.run(analysis_prompt)

        # Parse response into structured plan
        plan = self._parse_plan_response(response.text, workflow_input)

        # Generate human-readable markdown
        plan.human_readable_plan = self._generate_markdown_plan(plan)

        logger.info(f"Generated plan with {len(plan.steps)} steps")

        return plan

    def _build_analysis_prompt(self, workflow_input: WorkflowInput) -> str:
        """Build analysis prompt for the planning agent.

        Args:
            workflow_input: User requirements

        Returns:
            Formatted prompt string
        """
        data_sources_list = ", ".join(workflow_input.data_sources.keys()) if workflow_input.data_sources else "None"

        return f"""
Analyze the following workflow requirements and create an execution plan:

**Workflow Name:** {workflow_input.name}

**Description:** {workflow_input.description}

**User Request:** {workflow_input.user_prompt}

**Suggested Steps (from user):**
{self._format_user_steps(workflow_input.workflow_steps)}

**Available Data Sources:** {data_sources_list}

Create a detailed execution plan with specific steps, agent assignments,
dependencies, and approval requirements. Consider what data each step needs
and ensure dependencies are properly ordered.
"""

    def _format_user_steps(self, steps: List[str]) -> str:
        """Format user-provided steps as numbered list."""
        if not steps:
            return "None provided"
        return "\n".join([f"{i+1}. {step}" for i, step in enumerate(steps)])

    def _parse_plan_response(
        self,
        response_text: str,
        workflow_input: WorkflowInput,
    ) -> WorkflowPlan:
        """Parse LLM response into WorkflowPlan.

        Args:
            response_text: Response from planning agent
            workflow_input: Original input

        Returns:
            Structured WorkflowPlan
        """
        # Try to extract JSON from response
        try:
            # Look for JSON block in markdown code fence
            import re
            json_match = re.search(r"```(?:json)?\s*(.*?)```", response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_str = response_text

            plan_data = json.loads(json_str)

            # Parse steps
            steps = []
            for step_data in plan_data.get("steps", []):
                step = WorkflowStep(
                    step_id=step_data.get("step_id", f"step_{len(steps)+1}"),
                    step_name=step_data["step_name"],
                    agent_type=step_data["agent_type"],
                    description=step_data["description"],
                    inputs=step_data.get("inputs", []),
                    requires_approval=step_data.get("requires_approval", False),
                    estimated_outputs=step_data.get("estimated_outputs", ""),
                )
                steps.append(step)

            data_flow = plan_data.get("data_flow", {})

            plan = WorkflowPlan(
                workflow_id=f"wf-{uuid4().hex[:8]}",
                name=workflow_input.name,
                description=workflow_input.description,
                steps=steps,
                data_flow=data_flow,
                metadata={
                    "user_prompt": workflow_input.user_prompt,
                    "reasoning": plan_data.get("reasoning", ""),
                },
            )

            return plan

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse plan as JSON: {e}, creating fallback plan")
            return self._create_fallback_plan(workflow_input)

    def _create_fallback_plan(self, workflow_input: WorkflowInput) -> WorkflowPlan:
        """Create a simple fallback plan when parsing fails.

        Args:
            workflow_input: User requirements

        Returns:
            Simple WorkflowPlan
        """
        steps = []

        # Determine which agent to use based on data sources
        has_database = any("database" in str(k).lower() or "sql" in str(k).lower()
                          for k in workflow_input.data_sources.keys())
        has_documents = any("document" in str(k).lower() or "vector" in str(k).lower()
                           for k in workflow_input.data_sources.keys())

        step_id = 1
        if has_database:
            steps.append(WorkflowStep(
                step_id=f"step_{step_id}",
                step_name="Query Database",
                agent_type="structured_data",
                description="Execute SQL query to retrieve data",
                inputs=[],
                requires_approval=True,
                estimated_outputs="Query results as table",
            ))
            step_id += 1

        if has_documents:
            steps.append(WorkflowStep(
                step_id=f"step_{step_id}",
                step_name="Search Documents",
                agent_type="rag",
                description="Search relevant documents",
                inputs=[],
                requires_approval=False,
                estimated_outputs="Relevant document chunks with citations",
            ))
            step_id += 1

        # If no steps created, add a generic one
        if not steps:
            steps.append(WorkflowStep(
                step_id="step_1",
                step_name="Execute Task",
                agent_type="custom",
                description=workflow_input.user_prompt,
                inputs=[],
                requires_approval=False,
                estimated_outputs="Task results",
            ))

        return WorkflowPlan(
            workflow_id=f"wf-{uuid4().hex[:8]}",
            name=workflow_input.name,
            description=workflow_input.description,
            steps=steps,
            data_flow={},
            metadata={"user_prompt": workflow_input.user_prompt, "fallback": True},
        )

    def _generate_markdown_plan(self, plan: WorkflowPlan) -> str:
        """Generate human-readable markdown plan.

        Args:
            plan: Workflow plan to format

        Returns:
            Markdown-formatted plan
        """
        lines = [
            f"# Workflow Plan: {plan.name}",
            "",
            f"**Description:** {plan.description}",
            "",
            f"**Workflow ID:** `{plan.workflow_id}`",
            "",
            "## Execution Steps",
            "",
        ]

        for i, step in enumerate(plan.steps, 1):
            lines.append(f"### Step {i}: {step.step_name}")
            lines.append("")
            lines.append(f"- **ID:** `{step.step_id}`")
            lines.append(f"- **Agent:** {step.agent_type}")
            lines.append(f"- **Description:** {step.description}")

            if step.inputs:
                lines.append(f"- **Dependencies:** {', '.join(f'`{dep}`' for dep in step.inputs)}")

            lines.append(f"- **Requires Approval:** {'Yes' if step.requires_approval else 'No'}")

            if step.estimated_outputs:
                lines.append(f"- **Expected Output:** {step.estimated_outputs}")

            lines.append("")

        # Add metadata if available
        if plan.metadata.get("reasoning"):
            lines.append("## Planning Rationale")
            lines.append("")
            lines.append(plan.metadata["reasoning"])
            lines.append("")

        return "\n".join(lines)

    def build_step_graph(
        self,
        plan: WorkflowPlan,
        context: OrchestrationContext,
    ) -> StepGraph:
        """Convert WorkflowPlan to executable StepGraph.

        Args:
            plan: Workflow plan to execute
            context: Orchestration context with agents and connectors

        Returns:
            Executable StepGraph
        """
        graph = StepGraph()

        for step in plan.steps:
            # Determine approval type
            approval_type = self._determine_approval_type(step)

            # Create step action
            step_action = self._create_step_action(step)

            # Create step definition
            step_def = StepDefinition(
                step_id=step.step_id,
                name=step.step_name,
                action=step_action,
                approval_type=approval_type,
                summary=step.description,
                metadata={"agent_type": step.agent_type},
            )

            # Add to graph with dependencies
            dependencies = step.inputs if step.inputs else None
            graph.add_step(step_def, dependencies=dependencies)

        # Validate graph is acyclic
        graph.validate_acyclic()

        logger.info(f"Built StepGraph with {len(graph)} steps")

        return graph

    def _determine_approval_type(self, step: WorkflowStep) -> ApprovalType | None:
        """Determine approval type for a step.

        Args:
            step: Workflow step

        Returns:
            ApprovalType or None
        """
        if not step.requires_approval:
            return None

        # Map agent types to approval types
        if "sql" in step.agent_type.lower() or "structured_data" in step.agent_type.lower():
            return ApprovalType.SQL
        elif "mcp" in step.agent_type.lower() or "api" in step.agent_type.lower():
            return ApprovalType.MCP
        else:
            return ApprovalType.CUSTOM

    def _create_step_action(
        self,
        step: WorkflowStep,
    ) -> Callable[[OrchestrationContext], Awaitable[Any]]:
        """Create action function for step.

        Args:
            step: Workflow step

        Returns:
            Async function that executes the step
        """
        async def step_action(context: OrchestrationContext) -> Any:
            """Execute workflow step within context."""
            logger.info(f"Executing step: {step.step_name} ({step.step_id})")

            # Get agent from context (agents should be registered in context.transient_artifacts)
            agent = context.transient_artifacts.get(f"agent_{step.agent_type}")

            if not agent:
                logger.warning(f"Agent {step.agent_type} not found in context")
                return {"error": f"Agent {step.agent_type} not available"}

            # Gather inputs from previous steps
            inputs = []
            for dep_id in step.inputs:
                dep_result = context.transient_artifacts.get(dep_id)
                if dep_result:
                    inputs.append(dep_result)

            # Build query/prompt for agent
            query = step.description
            if inputs:
                query += f"\n\nPrevious results:\n{self._format_inputs(inputs)}"

            # Execute agent
            try:
                result = await agent.run(query)
                logger.info(f"Step {step.step_id} completed successfully")
                return result
            except Exception as e:
                logger.error(f"Step {step.step_id} failed: {e}")
                return {"error": str(e)}

        return step_action

    def _format_inputs(self, inputs: List[Any]) -> str:
        """Format inputs from previous steps.

        Args:
            inputs: List of results from previous steps

        Returns:
            Formatted string
        """
        formatted = []
        for i, inp in enumerate(inputs, 1):
            if hasattr(inp, "text"):
                formatted.append(f"Input {i}: {inp.text[:200]}")
            else:
                formatted.append(f"Input {i}: {str(inp)[:200]}")
        return "\n".join(formatted)
