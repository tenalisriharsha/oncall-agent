"""Fake read-only tools with canned, deterministic responses.

These exist so the agent loop, the scripted policy, and the CLI demo have
something to call before Phase 2 wires up real Prometheus/kubectl
clients. They implement the exact same :class:`Tool` interface those
real clients will, so nothing above this layer needs to change later.
"""

from __future__ import annotations

from typing import Any

from .base import Tool


class FakeRecentDeploysTool(Tool):
    """Stands in for a deploy-history lookup (e.g. against a CD system)."""

    name = "get_recent_deploys"
    description = "Return recent deploy history for a service (fake/demo data)."

    def __init__(
        self,
        minutes_since_last_deploy: int = 12,
        version: str = "v2.4.1",
        previous_version: str = "v2.4.0",
    ) -> None:
        self.minutes_since_last_deploy = minutes_since_last_deploy
        self.version = version
        self.previous_version = previous_version

    def run(self, service: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "service": service,
            "minutes_since_last_deploy": self.minutes_since_last_deploy,
            "version": self.version,
            "previous_version": self.previous_version,
        }


class FakePodStatusTool(Tool):
    """Stands in for a ``kubectl get pods`` / describe lookup."""

    name = "get_pod_status"
    description = "Return pod restart/health status for a service (fake/demo data)."

    def __init__(self, restarts: int = 5, oom_killed: bool = False) -> None:
        self.restarts = restarts
        self.oom_killed = oom_killed

    def run(self, service: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "service": service,
            "restarts": self.restarts,
            "oom_killed": self.oom_killed,
        }
