"""Graph and step definitions for orchestrated workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from .approvals import ApprovalType
from .context import OrchestrationContext

StepAction = Callable[[OrchestrationContext], Awaitable[Any] | Any]


@dataclass
class StepDefinition:
    """Definition of a single orchestrated step."""

    step_id: str
    name: str
    action: StepAction
    approval_type: ApprovalType | None = None
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class StepGraph:
    """Directed acyclic graph of steps with dependency tracking."""

    def __init__(self) -> None:
        self._steps: dict[str, StepDefinition] = {}
        self._edges: dict[str, set[str]] = {}

    @property
    def steps(self) -> dict[str, StepDefinition]:
        return dict(self._steps)

    def add_step(self, step: StepDefinition, dependencies: Iterable[str] | None = None) -> None:
        if step.step_id in self._steps:
            raise ValueError(f"Step '{step.step_id}' already exists in graph")
        self._steps[step.step_id] = step
        deps_set = set(dependencies or [])
        missing = deps_set - set(self._steps.keys())
        if missing:
            raise ValueError(f"Dependencies {missing} must be added before the step")
        self._edges[step.step_id] = deps_set

    def ready_steps(self, completed: set[str]) -> list[StepDefinition]:
        ready: list[StepDefinition] = []
        for step_id, deps in self._edges.items():
            if step_id in completed:
                continue
            if deps.issubset(completed):
                ready.append(self._steps[step_id])
        return ready

    def validate_acyclic(self) -> None:
        temp: set[str] = set()
        perm: set[str] = set()

        def visit(node: str) -> None:
            if node in perm:
                return
            if node in temp:
                raise ValueError("Detected cycle in step graph")
            temp.add(node)
            for dep in self._edges.get(node, set()):
                visit(dep)
            perm.add(node)
            temp.remove(node)

        for node in self._edges:
            visit(node)

    def __len__(self) -> int:
        return len(self._steps)
