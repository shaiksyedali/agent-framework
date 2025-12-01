"""Simple in-memory secret management utilities.

This module provides a lightweight :class:`SecretStore` that keeps sensitive
values out of application state snapshots and log lines while still allowing
callers to retrieve the clear-text credential when required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from pydantic import SecretStr

from agent_framework._logging import get_logger


logger = get_logger(__name__)


@dataclass
class SecretStore:
    """In-memory registry for sensitive values.

    Secrets are stored as :class:`pydantic.SecretStr` instances so that any
    accidental stringification produces a redacted representation. The store
    is not intended to be a production-grade key vault, but it centralizes
    handling of DB and MCP credentials so they can be scrubbed from UI state
    and logs.
    """

    _secrets: Dict[str, SecretStr] = field(default_factory=dict)

    def set_secret(self, name: str, value: str) -> None:
        """Persist a secret under the given name."""

        self._secrets[name] = SecretStr(value)
        logger.debug("Stored secret %s", name)

    def get_secret(self, name: str) -> Optional[str]:
        """Return the clear-text secret value if present."""

        secret = self._secrets.get(name)
        return secret.get_secret_value() if secret else None

    def describe(self, name: str) -> str:
        """Return a redacted representation suitable for logs/UI."""

        secret = self._secrets.get(name)
        return str(secret) if secret else "<missing>"

    @classmethod
    def global_store(cls) -> "SecretStore":
        """Access a process-wide shared secret store."""

        if not hasattr(cls, "_global_instance"):
            cls._global_instance = cls()  # type: ignore[attr-defined]
        return cls._global_instance  # type: ignore[attr-defined]


__all__ = ["SecretStore"]
