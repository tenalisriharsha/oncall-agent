"""The contract every tool the agent can call must satisfy.

Phase 2 will add real read-only clients (Prometheus, kubectl, a runbook
search, deploy history) against this same interface. Phase 1 ships only
the contract plus small fakes, so the agent loop and its tests have
something concrete to call without depending on a live cluster.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """A single capability the agent can invoke by name."""

    name: str
    description: str
    read_only: bool = True

    @abstractmethod
    def run(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool and return a JSON-serializable result."""
        raise NotImplementedError


class ToolRegistry:
    """A lookup from tool name to :class:`Tool` instance."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            known = ", ".join(sorted(self._tools))
            raise KeyError(f"Unknown tool '{name}'. Registered tools: {known}") from exc

    def names(self) -> list[str]:
        return sorted(self._tools)
