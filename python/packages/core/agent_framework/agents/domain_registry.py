"""Registration utilities for domain-specific agents and their tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agent_framework.orchestrator.approvals import ApprovalPolicy, ApprovalType
from agent_framework.orchestrator.context import OrchestrationContext


@dataclass
class DomainAgentMatch:
    """Result returned by a domain agent detector."""

    confidence: float
    reason: str
    suggested_tool: str | None = None
    missing_dependencies: set[str] = field(default_factory=set)


@dataclass
class DomainToolRegistration:
    """Registration details for a domain tool callable."""

    name: str
    description: str
    handler: Callable[[str, OrchestrationContext], Awaitable[Any] | Any]
    approval_type: ApprovalType = ApprovalType.CUSTOM
    summary_prefix: str | None = None
    policy_tags: set[str] = field(default_factory=set)

    def summarize(self, goal: str) -> str:
        """Generate a concise approval summary for the tool."""

        normalized_goal = " ".join(goal.split())
        prefix = self.summary_prefix or f"Execute {self.name}"
        return f"{prefix}: {normalized_goal}" if normalized_goal else prefix


@dataclass
class DomainAgentRegistration:
    """Registered domain agent and its detection heuristics."""

    key: str
    name: str
    description: str
    detector: Callable[[str, OrchestrationContext], DomainAgentMatch | None]
    approval_policy: ApprovalPolicy = field(default_factory=ApprovalPolicy)
    data_dependencies: set[str] = field(default_factory=set)
    tools: dict[str, DomainToolRegistration] = field(default_factory=dict)

    def register_tool(self, tool: DomainToolRegistration) -> None:
        if tool.name in self.tools:
            raise ValueError(f"Tool '{tool.name}' is already registered for agent '{self.key}'")
        self.tools[tool.name] = tool


@dataclass
class DomainAgentSelection:
    """Resolved pairing of a domain agent and tool for execution."""

    agent: DomainAgentRegistration
    match: DomainAgentMatch
    tool: DomainToolRegistration | None

    @property
    def missing_dependencies(self) -> set[str]:
        return set(self.match.missing_dependencies)

    @property
    def available(self) -> bool:
        return not self.match.missing_dependencies


class DomainAgentRegistry:
    """Registry that tracks domain-specific agents and tools."""

    def __init__(self) -> None:
        self._agents: dict[str, DomainAgentRegistration] = {}

    def register_agent(self, agent: DomainAgentRegistration) -> None:
        if agent.key in self._agents:
            raise ValueError(f"Agent '{agent.key}' is already registered")
        self._agents[agent.key] = agent

    def register_tool(self, agent_key: str, tool: DomainToolRegistration) -> None:
        agent = self.get_agent(agent_key)
        if agent is None:
            raise KeyError(f"No agent registered under key '{agent_key}'")
        agent.register_tool(tool)

    def get_agent(self, key: str) -> DomainAgentRegistration | None:
        return self._agents.get(key)

    def match_agents(
        self, user_goal: str, context: OrchestrationContext
    ) -> list[DomainAgentSelection]:
        """Return agents that match the goal, sorted by confidence."""

        matches: list[DomainAgentSelection] = []
        for agent in self._agents.values():
            detection = agent.detector(user_goal, context)
            if detection is None:
                continue

            required = set(agent.data_dependencies)
            detection.missing_dependencies |= required - set(context.connectors.keys())
            tool = self._resolve_tool(agent, detection.suggested_tool)
            matches.append(DomainAgentSelection(agent=agent, match=detection, tool=tool))

        matches.sort(key=lambda selection: selection.match.confidence, reverse=True)
        return matches

    def _resolve_tool(
        self, agent: DomainAgentRegistration, tool_name: str | None
    ) -> DomainToolRegistration | None:
        if tool_name and tool_name in agent.tools:
            return agent.tools[tool_name]
        if agent.tools:
            return next(iter(agent.tools.values()))
        return None

