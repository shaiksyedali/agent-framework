"""Shared orchestration context consumed by agents and steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid


@dataclass
class OrchestrationContext:
    """Unified view of workflow state used by agents and orchestrators."""

    workflow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_metadata: dict[str, Any] = field(default_factory=dict)
    persona: dict[str, Any] | None = None
    connectors: dict[str, Any] = field(default_factory=dict)
    transient_artifacts: dict[str, Any] = field(default_factory=dict)

    def with_artifact(self, key: str, value: Any) -> "OrchestrationContext":
        """Return a new context with an additional transient artifact."""

        updated_artifacts = dict(self.transient_artifacts)
        updated_artifacts[key] = value
        return OrchestrationContext(
            workflow_id=self.workflow_id,
            workflow_metadata=dict(self.workflow_metadata),
            persona=self.persona,
            connectors=dict(self.connectors),
            transient_artifacts=updated_artifacts,
        )
