"""Action executors for approved fixes.

Nothing here is ever called directly from the investigation loop — only
:func:`execute_action` is, and it refuses to run anything unless it is
handed an :class:`~oncall_agent.models.ApprovalDecision` that is already
``APPROVED``. That is the one chokepoint between a diagnosis and a
mutating change to a cluster.

:class:`KubectlMutationClient` is intentionally a separate class from
:class:`oncall_agent.tools.kubectl.KubectlClient`: the read-only client's
whole guarantee is that nothing it does can mutate a cluster, and adding
write verbs to it would quietly break that guarantee for every caller
that already trusts it. This client restricts itself to its own,
narrower chokepoint (``rollout``/``scale`` only).
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import Any, Callable

from .models import ActionResult, ActionType, ApprovalDecision, ApprovalStatus, AuditEvent, EventType
from .audit import AuditTrail

MUTATING_SUBCOMMANDS = {"rollout", "scale"}


class ApprovalError(RuntimeError):
    """Raised when an action is executed without a prior APPROVED decision."""


class KubectlActionError(RuntimeError):
    """Raised when a mutating kubectl invocation fails or is refused."""


class KubectlMutationClient:
    """Thin wrapper around the ``kubectl`` CLI, restricted to ``rollout``/``scale``."""

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
        self._runner = runner if runner is not None else subprocess.run

    def _run(self, args: list[str]) -> str:
        if not args or args[0] not in MUTATING_SUBCOMMANDS:
            raise KubectlActionError(
                f"Refusing to run kubectl subcommand '{args[0] if args else ''}' here. "
                f"Allowed: {', '.join(sorted(MUTATING_SUBCOMMANDS))}."
            )

        cmd = [self.kubectl_bin, *args]
        if self.namespace:
            cmd += ["-n", self.namespace]
        if self.context:
            cmd += ["--context", self.context]

        try:
            result = self._runner(cmd, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise KubectlActionError(f"Failed to run '{' '.join(cmd)}': {exc}") from exc

        if result.returncode != 0:
            raise KubectlActionError(
                f"'{' '.join(cmd)}' exited {result.returncode}: {result.stderr.strip()}"
            )
        return result.stdout

    def restart(self, service: str) -> str:
        return self._run(["rollout", "restart", f"deployment/{service}"])

    def rollback(self, service: str) -> str:
        return self._run(["rollout", "undo", f"deployment/{service}"])

    def scale(self, service: str, replicas: int) -> str:
        return self._run(["scale", f"deployment/{service}", f"--replicas={replicas}"])


class ActionExecutor(ABC):
    """One concrete way to carry out a single :class:`ActionType`."""

    name: str
    action_type: ActionType

    @abstractmethod
    def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Perform the action and return a JSON-serializable summary."""
        raise NotImplementedError


class RestartActionExecutor(ActionExecutor):
    """Restarts a deployment's pods via ``kubectl rollout restart``."""

    name = "restart"
    action_type = ActionType.RESTART

    def __init__(self, client: KubectlMutationClient) -> None:
        self.client = client

    def execute(self, service: str, **kwargs: Any) -> dict[str, Any]:
        output = self.client.restart(service)
        return {"service": service, "output": output}


class RollbackActionExecutor(ActionExecutor):
    """Rolls a deployment back via ``kubectl rollout undo``."""

    name = "rollback"
    action_type = ActionType.ROLLBACK

    def __init__(self, client: KubectlMutationClient) -> None:
        self.client = client

    def execute(self, service: str, to_version: str | None = None, **kwargs: Any) -> dict[str, Any]:
        output = self.client.rollback(service)
        return {"service": service, "to_version": to_version, "output": output}


class ScaleActionExecutor(ActionExecutor):
    """Scales a deployment's replica count via ``kubectl scale``."""

    name = "scale"
    action_type = ActionType.SCALE

    def __init__(self, client: KubectlMutationClient) -> None:
        self.client = client

    def execute(self, service: str, replicas: int, **kwargs: Any) -> dict[str, Any]:
        output = self.client.scale(service, replicas)
        return {"service": service, "replicas": replicas, "output": output}


class NoopActionExecutor(ActionExecutor):
    """Records what it would have done, without touching a real cluster.

    Used by ``oncall-agent demo``, which investigates canned/fake
    evidence and so has no real deployment to act on.
    """

    name = "noop"

    def __init__(self, action_type: ActionType) -> None:
        self.action_type = action_type

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"dry_run": True, "action": self.action_type.value, "arguments": kwargs}


class ActionRegistry:
    """A lookup from :class:`ActionType` to the executor that handles it."""

    def __init__(self) -> None:
        self._executors: dict[ActionType, ActionExecutor] = {}

    def register(self, executor: ActionExecutor) -> None:
        self._executors[executor.action_type] = executor

    def get(self, action_type: ActionType) -> ActionExecutor:
        try:
            return self._executors[action_type]
        except KeyError as exc:
            known = ", ".join(sorted(a.value for a in self._executors))
            raise KeyError(f"No executor registered for action '{action_type.value}'. Registered: {known}") from exc

    @classmethod
    def noop(cls) -> "ActionRegistry":
        """A registry of dry-run executors for every mutating action type."""
        registry = cls()
        for action_type in (ActionType.RESTART, ActionType.ROLLBACK, ActionType.SCALE):
            registry.register(NoopActionExecutor(action_type))
        return registry

    @classmethod
    def kubectl(cls, client: KubectlMutationClient) -> "ActionRegistry":
        """A registry of real kubectl-backed executors sharing one client."""
        registry = cls()
        registry.register(RestartActionExecutor(client))
        registry.register(RollbackActionExecutor(client))
        registry.register(ScaleActionExecutor(client))
        return registry


def execute_action(
    incident_id: str,
    action_type: ActionType,
    action_arguments: dict[str, Any],
    decision: ApprovalDecision,
    registry: ActionRegistry,
    audit: AuditTrail,
) -> ActionResult:
    """Run the executor for ``action_type``, but only if ``decision`` approved it.

    Always logs an ``ACTION_EXECUTED`` audit event, success or failure,
    so the trail shows what was attempted even when it blew up.
    """
    if decision.status != ApprovalStatus.APPROVED:
        raise ApprovalError(
            f"Action for incident {incident_id} was not approved "
            f"(status={decision.status.value}): {decision.reason or 'no reason given'}."
        )

    executor = registry.get(action_type)
    try:
        output = executor.execute(**action_arguments)
        result = ActionResult(
            incident_id=incident_id,
            action=action_type,
            arguments=action_arguments,
            success=True,
            output=str(output),
        )
    except Exception as exc:  # noqa: BLE001 - always recorded, never silently swallowed
        result = ActionResult(
            incident_id=incident_id,
            action=action_type,
            arguments=action_arguments,
            success=False,
            output=str(exc),
        )

    audit.log(
        AuditEvent(
            incident_id=incident_id,
            event_type=EventType.ACTION_EXECUTED,
            payload=result.model_dump(mode="json"),
        )
    )
    return result
