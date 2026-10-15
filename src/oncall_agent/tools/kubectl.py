"""A read-only ``kubectl`` client and the tools that wrap it.

Only ``get``, ``describe``, and ``logs`` subcommands are ever invoked —
nothing here can delete, scale, patch, or otherwise mutate a cluster.
:meth:`KubectlClient._run` enforces that at a single chokepoint so a bug
elsewhere in this module cannot accidentally escalate to a write.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable

from .base import Tool

READ_ONLY_SUBCOMMANDS = {"get", "describe", "logs"}


class KubectlError(RuntimeError):
    """Raised when a kubectl invocation fails or is refused."""


class KubectlClient:
    """Thin wrapper around the ``kubectl`` CLI, restricted to read-only verbs."""

    def __init__(
        self,
        kubectl_bin: str = "kubectl",
        namespace: str | None = None,
        context: str | None = None,
        timeout: float = 10.0,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.kubectl_bin = kubectl_bin
        self.namespace = namespace
        self.context = context
        self.timeout = timeout
        # Resolved at construction time, not bound as a default parameter,
        # so tests can monkeypatch subprocess.run before creating a client.
        self._runner = runner if runner is not None else subprocess.run

    def _run(self, args: list[str]) -> str:
        if not args or args[0] not in READ_ONLY_SUBCOMMANDS:
            raise KubectlError(
                f"Refusing to run non-read-only kubectl subcommand '{args[0] if args else ''}'. "
                f"Allowed: {', '.join(sorted(READ_ONLY_SUBCOMMANDS))}."
            )

        cmd = [self.kubectl_bin, *args]
        if self.namespace:
            cmd += ["-n", self.namespace]
        if self.context:
            cmd += ["--context", self.context]

        try:
            result = self._runner(cmd, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise KubectlError(f"Failed to run '{' '.join(cmd)}': {exc}") from exc

        if result.returncode != 0:
            raise KubectlError(
                f"'{' '.join(cmd)}' exited {result.returncode}: {result.stderr.strip()}"
            )
        return result.stdout

    def get_pods_json(self, selector: str | None = None) -> dict[str, Any]:
        args = ["get", "pods", "-o", "json"]
        if selector:
            args += ["-l", selector]
        try:
            return json.loads(self._run(args))
        except json.JSONDecodeError as exc:
            raise KubectlError(f"Could not parse kubectl output as JSON: {exc}") from exc

    def describe_pod(self, pod_name: str) -> str:
        return self._run(["describe", "pod", pod_name])

    def logs(self, pod_name: str, tail_lines: int = 200, previous: bool = False) -> str:
        args = ["logs", pod_name, "--tail", str(tail_lines)]
        if previous:
            args.append("-p")
        return self._run(args)


def _container_statuses(pods: dict[str, Any]) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for item in pods.get("items", []):
        statuses.extend(item.get("status", {}).get("containerStatuses", []))
    return statuses


class KubectlPodStatusTool(Tool):
    """Summarizes pod restarts and OOM state for a service via ``kubectl get pods``."""

    name = "get_pod_status"
    description = "Return pod restart/health status for a service via kubectl get pods."
    read_only = True

    def __init__(self, client: KubectlClient, selector_label: str = "app") -> None:
        self.client = client
        self.selector_label = selector_label

    def run(self, service: str, **kwargs: Any) -> dict[str, Any]:
        pods = self.client.get_pods_json(selector=f"{self.selector_label}={service}")
        statuses = _container_statuses(pods)
        restarts = sum(status.get("restartCount", 0) for status in statuses)
        oom_killed = any(
            status.get("lastState", {}).get("terminated", {}).get("reason") == "OOMKilled"
            for status in statuses
        )
        return {
            "service": service,
            "pod_count": len(pods.get("items", [])),
            "restarts": restarts,
            "oom_killed": oom_killed,
        }


class KubectlLogsTool(Tool):
    """Fetches recent logs for a single pod via ``kubectl logs``."""

    name = "get_pod_logs"
    description = "Return recent log lines for a pod via kubectl logs."
    read_only = True

    def __init__(self, client: KubectlClient) -> None:
        self.client = client

    def run(self, pod_name: str, tail_lines: int = 200, previous: bool = False, **kwargs: Any) -> dict[str, Any]:
        logs = self.client.logs(pod_name, tail_lines=tail_lines, previous=previous)
        return {"pod_name": pod_name, "tail_lines": tail_lines, "logs": logs}


class KubectlDescribeTool(Tool):
    """Fetches the full ``kubectl describe pod`` output for a single pod."""

    name = "describe_pod"
    description = "Return kubectl describe output for a pod (events, conditions, etc)."
    read_only = True

    def __init__(self, client: KubectlClient) -> None:
        self.client = client

    def run(self, pod_name: str, **kwargs: Any) -> dict[str, Any]:
        description = self.client.describe_pod(pod_name)
        return {"pod_name": pod_name, "description": description}
