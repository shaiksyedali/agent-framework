"""Lightweight planner that proposes orchestrator step graphs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

from agent_framework.data.connectors import SQLConnector
from agent_framework.data.vector_store import DocumentIngestionService
from agent_framework.orchestrator.approvals import ApprovalType
from agent_framework.orchestrator.context import OrchestrationContext
from agent_framework.orchestrator.graph import StepDefinition, StepGraph
from agent_framework.agents.sql import SQLAgent, SQLExample


class IntentType(str, Enum):
    """High-level intent classifications used for routing."""

    SQL = "sql"
    RAG = "rag"
    CUSTOM = "custom"


@dataclass
class IntentClassification:
    """Result of intent detection."""

    intent: IntentType
    confidence: float
    rationale: str


@dataclass
class DataSourceSelection:
    """Chosen execution target for a plan."""

    target: IntentType
    connector_key: str | None
    reason: str


@dataclass
class PlanStep:
    """Human-readable plan step description."""

    step_id: str
    name: str
    description: str
    approval_type: ApprovalType | None = None
    dependencies: list[str] = field(default_factory=list)


@dataclass
class PlanArtifact:
    """Structured plan payload to surface in UIs."""

    user_goal: str
    intent: IntentClassification
    data_source: DataSourceSelection
    steps: list[PlanStep]


class Planner:
    """Builds orchestrator graphs based on intent and available resources."""

    def __init__(
        self,
        *,
        default_confidence: float = 0.55,
        sql_llm: Callable[[str], Awaitable[str] | str] | None = None,
        sql_history: Sequence[SQLExample] | None = None,
        max_sql_attempts: int = 3,
        sql_validator: Callable[[list[dict[str, Any]]], bool] | None = None,
        include_raw_rows: bool = True,
        enable_calculator_fallback: bool = True,
    ) -> None:
        self._default_confidence = default_confidence
        self._sql_llm = sql_llm
        self._sql_history = list(sql_history or [])
        self._max_sql_attempts = max_sql_attempts
        self._sql_validator = sql_validator
        self._include_raw_rows = include_raw_rows
        self._enable_calculator_fallback = enable_calculator_fallback

    def classify_intent(
        self,
        user_goal: str,
        context: OrchestrationContext,
        *,
        has_custom_tools: bool = False,
    ) -> IntentClassification:
        """Classify a request using heuristics and available connectors."""

        normalized = user_goal.lower()
        has_sql_connector = any(isinstance(conn, SQLConnector) for conn in context.connectors.values())
        has_vector_search = any(
            isinstance(conn, DocumentIngestionService) for conn in context.connectors.values()
        )

        if has_sql_connector and self._looks_like_sql(normalized):
            return IntentClassification(
                intent=IntentType.SQL,
                confidence=0.82,
                rationale="Detected SQL-style phrasing and available connector",
            )

        if has_vector_search and self._looks_like_retrieval(normalized):
            return IntentClassification(
                intent=IntentType.RAG,
                confidence=0.72,
                rationale="Unstructured data query routed to retrieval",
            )

        if has_custom_tools:
            return IntentClassification(
                intent=IntentType.CUSTOM,
                confidence=0.61,
                rationale="Defaulting to custom tools because no structured data match was found",
            )

        if has_sql_connector:
            return IntentClassification(
                intent=IntentType.SQL,
                confidence=self._default_confidence,
                rationale="SQL connector present; falling back to tabular reasoning",
            )

        if has_vector_search:
            return IntentClassification(
                intent=IntentType.RAG,
                confidence=self._default_confidence,
                rationale="Vector search available; falling back to retrieval",
            )

        return IntentClassification(
            intent=IntentType.CUSTOM,
            confidence=self._default_confidence,
            rationale="No connectors matched; fallback to custom tool routing",
        )

    def select_data_source(
        self,
        classification: IntentClassification,
        context: OrchestrationContext,
        *,
        custom_tools: Mapping[str, Callable[..., Any]] | None = None,
    ) -> DataSourceSelection:
        """Pick a concrete connector or tool based on the classification."""

        if classification.intent == IntentType.SQL:
            sql_key = self._first_matching_key(context.connectors, SQLConnector)
            if sql_key:
                return DataSourceSelection(
                    target=IntentType.SQL,
                    connector_key=sql_key,
                    reason="SQL connector available",
                )

        if classification.intent == IntentType.RAG:
            rag_key = self._first_matching_key(context.connectors, DocumentIngestionService)
            if rag_key:
                return DataSourceSelection(
                    target=IntentType.RAG,
                    connector_key=rag_key,
                    reason="Vector search connector available",
                )

        if custom_tools:
            tool_key = next(iter(custom_tools.keys()))
            return DataSourceSelection(target=IntentType.CUSTOM, connector_key=tool_key, reason="Using custom tool")

        fallback_key = next(iter(context.connectors.keys()), None)
        return DataSourceSelection(
            target=classification.intent,
            connector_key=fallback_key,
            reason="Fallback routing based on available connectors",
        )

    def build_graph(
        self,
        user_goal: str,
        context: OrchestrationContext,
        *,
        custom_tools: Mapping[str, Callable[..., Any]] | None = None,
    ) -> tuple[StepGraph, PlanArtifact]:
        """Construct a :class:`StepGraph` and accompanying plan artifact."""

        classification = self.classify_intent(
            user_goal,
            context,
            has_custom_tools=bool(custom_tools),
        )
        selection = self.select_data_source(classification, context, custom_tools=custom_tools)

        plan_steps = [
            PlanStep(
                step_id="plan",
                name="Review plan",
                description="Share the proposed plan and wait for approval",
                approval_type=ApprovalType.PLAN,
                dependencies=[],
            )
        ]

        graph = StepGraph()

        def publish_plan(_: OrchestrationContext) -> PlanArtifact:
            return plan_artifact

        plan_artifact = PlanArtifact(
            user_goal=user_goal,
            intent=classification,
            data_source=selection,
            steps=plan_steps.copy(),
        )

        graph.add_step(
            StepDefinition(
                step_id="plan",
                name="Plan",
                action=publish_plan,
                approval_type=ApprovalType.PLAN,
                summary=f"Plan for '{self._truncate_goal(user_goal)}'",
                metadata={"plan_artifact": plan_artifact},
            )
        )

        if selection.target == IntentType.SQL:
            sql_step = self._build_sql_step(user_goal, selection, context)
            plan_steps.append(sql_step.plan_step)
            graph.add_step(sql_step.step_definition, dependencies=["plan"])
        elif selection.target == IntentType.RAG:
            rag_step = self._build_rag_step(user_goal, selection, context)
            plan_steps.append(rag_step.plan_step)
            graph.add_step(rag_step.step_definition, dependencies=["plan"])
        else:
            custom_step = self._build_custom_tool_step(user_goal, selection, custom_tools)
            plan_steps.append(custom_step.plan_step)
            graph.add_step(custom_step.step_definition, dependencies=["plan"])

        plan_artifact.steps = plan_steps
        return graph, plan_artifact

    def _build_sql_step(
        self,
        user_goal: str,
        selection: DataSourceSelection,
        context: OrchestrationContext,
    ) -> "_StepBundle":
        connector = self._expect_connector(context, selection.connector_key, SQLConnector)
        agent = SQLAgent(
            llm=self._sql_llm,
            few_shot_examples=self._sql_history,
        )

        async def execute_sql(_: OrchestrationContext):
            history = self._collect_sql_history(context)
            schema = connector.get_schema()
            return await agent.generate_and_execute(
                goal=user_goal,
                connector=connector,
                schema=schema,
                history=history,
                max_attempts=self._max_sql_attempts,
                validator=self._sql_validator,
                fetch_raw_after_aggregation=self._include_raw_rows,
                enable_calculator_fallback=self._enable_calculator_fallback,
            )

        summary = connector.approval_policy.summarize(self._truncate_goal(user_goal))
        step_def = StepDefinition(
            step_id="execute_sql",
            name="Execute SQL",
            action=execute_sql,
            approval_type=connector.approval_type,
            summary=summary,
            metadata={"goal": user_goal, "connector": selection.connector_key},
        )
        plan_step = PlanStep(
            step_id="execute_sql",
            name="Execute SQL",
            description=f"Generate and run SQL against connector '{selection.connector_key}'",
            approval_type=step_def.approval_type,
            dependencies=["plan"],
        )
        return _StepBundle(plan_step=plan_step, step_definition=step_def)

    def _build_rag_step(
        self,
        user_goal: str,
        selection: DataSourceSelection,
        context: OrchestrationContext,
    ) -> "_StepBundle":
        connector = self._expect_connector(context, selection.connector_key, DocumentIngestionService)

        def retrieve(_: OrchestrationContext):
            return [chunk.text for chunk in connector.search(user_goal)]

        step_def = StepDefinition(
            step_id="retrieve_context",
            name="Retrieve context",
            action=retrieve,
            approval_type=None,
            summary=f"Search vector index '{selection.connector_key}'",
            metadata={"query": user_goal, "connector": selection.connector_key},
        )
        plan_step = PlanStep(
            step_id="retrieve_context",
            name="Retrieve context",
            description=f"Retrieve relevant chunks from '{selection.connector_key}'",
            dependencies=["plan"],
        )
        return _StepBundle(plan_step=plan_step, step_definition=step_def)

    def _build_custom_tool_step(
        self,
        user_goal: str,
        selection: DataSourceSelection,
        custom_tools: Mapping[str, Callable[..., Any]] | None,
    ) -> "_StepBundle":
        if not custom_tools:
            raise ValueError("custom_tools must be provided for custom planning")
        tool = custom_tools.get(selection.connector_key)
        if tool is None:
            raise ValueError(f"No tool found for key '{selection.connector_key}'")

        def invoke_tool(_: OrchestrationContext):
            return tool(user_goal)

        step_def = StepDefinition(
            step_id="invoke_tool",
            name="Invoke custom tool",
            action=invoke_tool,
            approval_type=ApprovalType.CUSTOM,
            summary=f"Run tool '{selection.connector_key}'",
            metadata={"tool": selection.connector_key},
        )
        plan_step = PlanStep(
            step_id="invoke_tool",
            name="Invoke custom tool",
            description=f"Call custom tool '{selection.connector_key}'",
            approval_type=ApprovalType.CUSTOM,
            dependencies=["plan"],
        )
        return _StepBundle(plan_step=plan_step, step_definition=step_def)

    def _collect_sql_history(self, context: OrchestrationContext) -> list[SQLExample]:
        combined: list[SQLExample] = list(self._sql_history)
        context_history = context.workflow_metadata.get("sql_history", [])
        for example in context_history:
            if isinstance(example, SQLExample):
                combined.append(example)
            elif isinstance(example, dict) and "question" in example and "sql" in example:
                combined.append(
                    SQLExample(
                        question=str(example["question"]),
                        sql=str(example["sql"]),
                        answer=example.get("answer"),
                    )
                )
        return combined

    @staticmethod
    def _first_matching_key(mapping: Mapping[str, Any], expected_type: type) -> str | None:
        for key, value in mapping.items():
            if isinstance(value, expected_type):
                return key
        return None

    @staticmethod
    def _truncate_goal(goal: str, limit: int = 60) -> str:
        trimmed = re.sub(r"\s+", " ", goal).strip()
        return trimmed if len(trimmed) <= limit else f"{trimmed[: limit - 3]}..."

    @staticmethod
    def _looks_like_sql(text: str) -> bool:
        sql_keywords = ["select", "join", "from", "where", "table", "database", "query"]
        return any(keyword in text for keyword in sql_keywords)

    @staticmethod
    def _looks_like_retrieval(text: str) -> bool:
        retrieval_keywords = ["document", "file", "manual", "knowledge", "kb", "note"]
        return any(keyword in text for keyword in retrieval_keywords)

    @staticmethod
    def _expect_connector(
        context: OrchestrationContext,
        key: str | None,
        expected_type: type,
    ) -> Any:
        connector = context.get_connector(key) if key else None
        if connector is None:
            connector = Planner._first_matching_value(context.connectors, expected_type)
        if not isinstance(connector, expected_type):
            raise ValueError(f"Expected a {expected_type.__name__} in the orchestration context")
        return connector

    @staticmethod
    def _first_matching_value(mapping: Mapping[str, Any], expected_type: type) -> Any:
        for value in mapping.values():
            if isinstance(value, expected_type):
                return value
        return None


@dataclass
class _StepBundle:
    plan_step: PlanStep
    step_definition: StepDefinition


__all__ = [
    "DataSourceSelection",
    "IntentClassification",
    "IntentType",
    "PlanArtifact",
    "PlanStep",
    "Planner",
]
