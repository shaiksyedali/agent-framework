"""Supervisor Agent for orchestrating multi-agent workflows dynamically."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agent_framework._agents import ChatAgent
from agent_framework._clients import ChatClientProtocol
from agent_framework._tools import ai_function
from agent_framework._types import AgentRunResponse
from agent_framework.orchestrator.context import OrchestrationContext
from agent_framework.schemas.workflow_plan import (
    SupervisorEvent,
    WorkflowInput,
)

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """Master orchestrator agent that dynamically constructs and executes workflows.

    The Supervisor Agent is the top-level coordinator that:
    - Analyzes incoming user requests
    - Determines which agents are needed
    - Creates workflow plans via the Planner
    - Executes workflows via the Executor
    - Generates final responses

    Example:
        >>> supervisor = SupervisorAgent(
        ...     chat_client=client,
        ...     planner_agent=planner,
        ...     executor_agent=executor,
        ...     structured_data_agent=sql_agent,
        ...     rag_agent=rag_agent,
        ...     response_generator=response_gen,
        ... )
        >>> async for event in supervisor.process_request(
        ...     user_request="What were our top products last quarter?",
        ... ):
        ...     print(f"{event.type}: {event.message}")
    """

    def __init__(
        self,
        chat_client: ChatClientProtocol,
        planner_agent,  # WorkflowPlannerAgent
        executor_agent,  # WorkflowExecutorAgent
        *,
        structured_data_agent=None,  # Optional[StructuredDataAgent]
        rag_agent=None,  # Optional[RAGRetrievalAgent]
        response_generator=None,  # Optional[ResponseGeneratorAgent]
        name: str = "supervisor",
    ):
        """Initialize the Supervisor Agent.

        Args:
            chat_client: Chat client for LLM-powered analysis
            planner_agent: Workflow planner for creating execution plans
            executor_agent: Workflow executor for running plans
            structured_data_agent: Optional agent for SQL queries
            rag_agent: Optional agent for document search
            response_generator: Optional agent for final response formatting
            name: Agent name
        """
        self.planner_agent = planner_agent
        self.executor_agent = executor_agent
        self.structured_data_agent = structured_data_agent
        self.rag_agent = rag_agent
        self.response_generator = response_generator
        self.name = name

        # Create supervisor ChatAgent for task analysis
        self.agent = ChatAgent(
            chat_client=chat_client,
            name=name,
            instructions=self._build_instructions(),
            tools=self._create_supervisor_tools(),
        )

    def _build_instructions(self) -> str:
        """Build instructions for the supervisor agent."""
        agents_list = []
        if self.structured_data_agent:
            agents_list.append("- structured_data_agent: Query databases (SQL)")
        if self.rag_agent:
            agents_list.append("- rag_agent: Search documents and knowledge bases")

        agents_desc = "\n".join(agents_list) if agents_list else "No specialized agents available"

        return f"""
You are the Supervisor Agent, responsible for orchestrating complex workflows.

## Your Responsibilities

1. Analyze incoming user requests to determine task type
2. Identify required agents and data sources
3. Coordinate with Planner to create workflow plans
4. Monitor workflow execution
5. Handle errors and coordinate recovery
6. Ensure final response generation

## Available Agents

{agents_desc}

## Decision Criteria

**Use structured_data_agent when:**
- Query requires database access or SQL
- User asks for analytics, aggregations, or metrics
- Task involves structured data analysis

**Use rag_agent when:**
- Query requires document search
- User asks about knowledge, documentation, or context
- Task involves unstructured text retrieval

**Use both agents when:**
- Query requires grounding with both data and documents
- Complex analysis needs multiple data sources
- Cross-referencing structured and unstructured data

**Use planner_agent for:**
- All complex multi-step workflows
- Any task requiring multiple agents
- Tasks with dependencies between steps

## Analysis Output

Provide your analysis as JSON:
{{
    "task_type": "data_query|document_search|hybrid|custom",
    "required_agents": ["structured_data", "rag"],
    "complexity": "simple|moderate|complex",
    "data_sources": ["databases", "documents", "apis"],
    "reasoning": "Brief explanation of your analysis"
}}
"""

    def _create_supervisor_tools(self) -> List:
        """Create tools for the supervisor agent."""
        tools = []

        @ai_function
        def list_available_agents() -> str:
            """List all available agents and their capabilities."""
            agents_info = []
            if self.structured_data_agent:
                agents_info.append(
                    "structured_data: Query structured databases (SQLite, DuckDB, PostgreSQL)\n"
                    "  - Generates SQL from natural language\n"
                    "  - Automatic retry on errors\n"
                    "  - Can consult RAG for schema documentation"
                )
            if self.rag_agent:
                agents_info.append(
                    "rag: Search documents and knowledge bases\n"
                    "  - Semantic search over vector store\n"
                    "  - Returns results with citations\n"
                    "  - Configurable result count (default: 20)"
                )
            return "\n\n".join(agents_info) if agents_info else "No specialized agents available"

        @ai_function
        def check_data_source_availability(source_type: str) -> bool:
            """Check if a specific data source type is available.

            Args:
                source_type: Type of data source ('database', 'documents', 'vector_store', 'api')

            Returns:
                True if data source is available, False otherwise
            """
            source_map = {
                "database": self.structured_data_agent is not None,
                "documents": self.rag_agent is not None,
                "vector_store": self.rag_agent is not None,
            }
            return source_map.get(source_type.lower(), False)

        tools.extend([list_available_agents, check_data_source_availability])
        return tools

    async def process_request(
        self,
        user_request: str,
        workflow_input: Optional[WorkflowInput] = None,
        context: Optional[OrchestrationContext] = None,
    ) -> AsyncIterator[SupervisorEvent]:
        """Process user request end-to-end.

        Process:
        1. Analyze request to determine workflow type
        2. Create workflow plan (or use provided workflow_input)
        3. Execute workflow step-by-step
        4. Generate final response
        5. Yield events throughout for observability

        Args:
            user_request: Natural language request from user
            workflow_input: Optional pre-defined workflow structure
            context: Optional orchestration context with connectors

        Yields:
            SupervisorEvent: Events tracking progress through the workflow
        """
        logger.info(f"Processing request: {user_request}")

        yield SupervisorEvent(
            type="started",
            message="Analyzing request...",
        )

        # Step 1: Analyze request
        try:
            analysis = await self._analyze_request(user_request)
            yield SupervisorEvent(
                type="analysis",
                message="Request analysis complete",
                data=analysis,
            )
        except Exception as e:
            logger.error(f"Request analysis failed: {e}")
            yield SupervisorEvent(
                type="error",
                message=f"Failed to analyze request: {e}",
            )
            return

        # Step 2: Create or validate workflow plan
        if workflow_input is None:
            workflow_input = self._create_workflow_input(user_request, analysis)

        yield SupervisorEvent(
            type="planning",
            message="Creating workflow plan...",
        )

        try:
            plan = await self.planner_agent.plan_workflow(workflow_input)

            yield SupervisorEvent(
                type="plan_created",
                message="Workflow plan created",
                data={
                    "plan": plan.human_readable_plan,
                    "num_steps": len(plan.steps),
                    "workflow_id": plan.workflow_id,
                },
            )
        except Exception as e:
            logger.error(f"Workflow planning failed: {e}")
            yield SupervisorEvent(
                type="error",
                message=f"Failed to create workflow plan: {e}",
            )
            return

        # Step 3: Get user approval for plan (optional, can be auto-approved)
        approval = await self._request_plan_approval(plan)
        if not approval:
            yield SupervisorEvent(
                type="aborted",
                message="Plan rejected by user",
            )
            return

        # Step 4: Execute workflow
        if context is None:
            context = self._build_orchestration_context(workflow_input)

        # Register agents in context for step actions to access
        context.transient_artifacts["agent_structured_data"] = self.structured_data_agent
        context.transient_artifacts["agent_rag"] = self.rag_agent

        yield SupervisorEvent(
            type="executing",
            message=f"Executing workflow with {len(plan.steps)} steps...",
        )

        workflow_outputs = []
        try:
            async for exec_event in self.executor_agent.execute_workflow(
                plan=plan,
                context=context,
                graph_builder=self.planner_agent.build_step_graph,
            ):
                # Forward execution events wrapped in supervisor event
                yield SupervisorEvent(
                    type="execution_event",
                    message=f"Step event: {exec_event.type}",
                    data={
                        "event_type": exec_event.type,
                        "step_id": exec_event.step_id,
                        "step_name": exec_event.step_name,
                        "output": exec_event.output,
                        "error": exec_event.error,
                    },
                )

                # Collect outputs for final response
                if exec_event.type == "step_completed":
                    workflow_outputs.append({
                        "step_name": exec_event.step_name,
                        "result": exec_event.output,
                    })

                # Check for abort
                if exec_event.type == "execution_aborted":
                    yield SupervisorEvent(
                        type="aborted",
                        message="Workflow execution aborted by user",
                    )
                    return

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            yield SupervisorEvent(
                type="error",
                message=f"Workflow execution failed: {e}",
            )
            return

        # Step 5: Generate final response
        yield SupervisorEvent(
            type="generating_response",
            message="Generating final response...",
        )

        try:
            if self.response_generator:
                final_response = await self.response_generator.generate_response(
                    workflow_outputs=workflow_outputs,
                    original_query=user_request,
                )
            else:
                final_response = self._default_response(workflow_outputs)

            yield SupervisorEvent(
                type="completed",
                message="Workflow completed successfully",
                data={
                    "response": final_response.text if hasattr(final_response, "text") else str(final_response),
                    "num_steps_completed": len(workflow_outputs),
                },
            )

        except Exception as e:
            logger.error(f"Response generation failed: {e}")
            # Still complete the workflow, just with a basic response
            final_response = self._default_response(workflow_outputs)
            yield SupervisorEvent(
                type="completed",
                message="Workflow completed (response generation had issues)",
                data={
                    "response": str(final_response),
                    "num_steps_completed": len(workflow_outputs),
                    "warning": f"Response generation error: {e}",
                },
            )

    async def _analyze_request(self, request: str) -> Dict[str, Any]:
        """Analyze user request to determine task type and required agents.

        Args:
            request: User request string

        Returns:
            Analysis dictionary with task_type, required_agents, complexity, etc.
        """
        analysis_prompt = f"""
Analyze the following user request and determine:
1. Task type (data_query, document_search, hybrid, custom)
2. Required agents (structured_data, rag, both)
3. Complexity (simple, moderate, complex)
4. Data sources needed (databases, documents, APIs)

User request: {request}

Provide analysis in JSON format as specified in your instructions.
"""

        response = await self.agent.run(analysis_prompt)

        # Parse response
        analysis = self._parse_analysis(response.text)

        return analysis

    def _parse_analysis(self, response_text: str) -> Dict[str, Any]:
        """Parse LLM analysis response.

        Args:
            response_text: Response from analysis agent

        Returns:
            Parsed analysis dictionary
        """
        try:
            # Try to extract JSON from response
            json_match = re.search(r"```(?:json)?\s*(.*?)```", response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text

            analysis = json.loads(json_str)

            # Ensure required fields
            if "task_type" not in analysis:
                analysis["task_type"] = "custom"
            if "required_agents" not in analysis:
                analysis["required_agents"] = []
            if "complexity" not in analysis:
                analysis["complexity"] = "moderate"

            return analysis

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse analysis: {e}, using fallback")
            return self._fallback_analysis()

    def _fallback_analysis(self) -> Dict[str, Any]:
        """Create fallback analysis when parsing fails."""
        agents = []
        if self.structured_data_agent:
            agents.append("structured_data")
        if self.rag_agent:
            agents.append("rag")

        return {
            "task_type": "custom",
            "required_agents": agents,
            "complexity": "moderate",
            "data_sources": [],
            "reasoning": "Fallback analysis (parsing failed)",
        }

    def _create_workflow_input(
        self,
        user_request: str,
        analysis: Dict[str, Any],
    ) -> WorkflowInput:
        """Create WorkflowInput from analysis.

        Args:
            user_request: Original user request
            analysis: Request analysis

        Returns:
            WorkflowInput for planner
        """
        # Generate workflow name from request (first 50 chars)
        workflow_name = user_request[:50] + ("..." if len(user_request) > 50 else "")

        # Create suggested steps based on required agents
        workflow_steps = []
        for agent in analysis.get("required_agents", []):
            if agent == "structured_data":
                workflow_steps.append("Query database for relevant data")
            elif agent == "rag":
                workflow_steps.append("Search documents for relevant information")

        if not workflow_steps:
            workflow_steps = ["Execute task"]

        return WorkflowInput(
            name=workflow_name,
            description=f"Workflow for: {user_request}",
            user_prompt=user_request,
            workflow_steps=workflow_steps,
            data_sources={},  # Will be populated from context if provided
        )

    def _build_orchestration_context(
        self,
        workflow_input: WorkflowInput,
    ) -> OrchestrationContext:
        """Build orchestration context from workflow input.

        Args:
            workflow_input: Workflow input with data sources

        Returns:
            OrchestrationContext for execution
        """
        context = OrchestrationContext(
            workflow_id=f"wf-{uuid4().hex[:8]}",
            connectors=workflow_input.data_sources,
            transient_artifacts={},
        )

        return context

    async def _request_plan_approval(self, plan) -> bool:
        """Request user approval for workflow plan.

        Args:
            plan: WorkflowPlan to approve

        Returns:
            True if approved, False otherwise

        Note:
            This is a placeholder for UI integration. Currently auto-approves.
        """
        # This would integrate with the UI/frontend for actual approval
        # For now, return True (auto-approve)
        logger.info(f"Auto-approving plan: {plan.name}")
        return True

    def _default_response(self, outputs: List[Dict[str, Any]]) -> AgentRunResponse:
        """Create default response when response generator not available.

        Args:
            outputs: Workflow step outputs

        Returns:
            Basic AgentRunResponse
        """
        from agent_framework._types import ChatMessage, Role, TextContent

        summary_parts = ["# Workflow Results\n"]

        for i, output in enumerate(outputs, 1):
            step_name = output.get("step_name", f"Step {i}")
            result = output.get("result")

            summary_parts.append(f"## {i}. {step_name}")

            if result:
                if isinstance(result, dict):
                    if "type" in result and result["type"] == "table":
                        summary_parts.append(f"- Results: {result.get('num_rows', 0)} rows")
                    elif "sql" in result:
                        summary_parts.append(f"- SQL: `{result['sql'][:100]}...`")
                        summary_parts.append(f"- Results: {result.get('num_results', 0)} rows")
                    else:
                        summary_parts.append(f"- Result: {str(result)[:100]}")
                else:
                    summary_parts.append(f"- Result: {str(result)[:100]}")

            summary_parts.append("")

        summary_text = "\n".join(summary_parts)

        return AgentRunResponse(
            messages=[ChatMessage(
                role=Role.ASSISTANT,
                contents=[TextContent(text=summary_text)]
            )]
        )
