import subprocess
from pathlib import Path

import pytest

from oncall_agent.actions import (
    ActionRegistry,
    ApprovalError,
    KubectlActionError,
    KubectlMutationClient,
    NoopActionExecutor,
    RestartActionExecutor,
    RollbackActionExecutor,
    ScaleActionExecutor,
    execute_action,
)
from oncall_agent.audit import AuditTrail
from oncall_agent.models import ActionType, ApprovalDecision, ApprovalStatus, EventType


def test_kubectl_mutation_client_refuses_non_mutating_subcommand():
    client = KubectlMutationClient(runner=lambda *a, **k: None)
    with pytest.raises(KubectlActionError, match="Refusing"):
        client._run(["get", "pods"])


def test_kubectl_mutation_client_restart_runs_rollout_restart():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="restarted", stderr="")

    client = KubectlMutationClient(namespace="prod", runner=fake_run)
    output = client.restart("checkout-service")

    assert output == "restarted"
    assert calls[0] == ["kubectl", "rollout", "restart", "deployment/checkout-service", "-n", "prod"]


def test_kubectl_mutation_client_rollback_runs_rollout_undo():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="rolled back", stderr="")

    client = KubectlMutationClient(runner=fake_run)
    assert client.rollback("checkout-service") == "rolled back"


def test_kubectl_mutation_client_scale_runs_kubectl_scale():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="scaled", stderr="")

    client = KubectlMutationClient(runner=fake_run)
    client.scale("checkout-service", 6)
    assert calls[0] == ["kubectl", "scale", "deployment/checkout-service", "--replicas=6"]


def test_kubectl_mutation_client_raises_on_nonzero_exit():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="deployment not found")

    client = KubectlMutationClient(runner=fake_run)
    with pytest.raises(KubectlActionError, match="deployment not found"):
        client.restart("checkout-service")


def test_kubectl_mutation_client_raises_on_runner_failure():
    def fake_run(cmd, **kwargs):
        raise OSError("kubectl not found")

    client = KubectlMutationClient(runner=fake_run)
    with pytest.raises(KubectlActionError, match="Failed to run"):
        client.restart("checkout-service")


def test_kubectl_mutation_client_includes_context_flag():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    client = KubectlMutationClient(context="prod-cluster", runner=fake_run)
    client.restart("checkout-service")
    assert "--context" in calls[0]
    assert "prod-cluster" in calls[0]


def test_restart_executor_execute_returns_output():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="restarted", stderr="")

    executor = RestartActionExecutor(KubectlMutationClient(runner=fake_run))
    result = executor.execute(service="checkout-service")
    assert result == {"service": "checkout-service", "output": "restarted"}


def test_rollback_executor_execute_returns_output():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="rolled back", stderr="")

    executor = RollbackActionExecutor(KubectlMutationClient(runner=fake_run))
    result = executor.execute(service="checkout-service", to_version="v1")
    assert result == {"service": "checkout-service", "to_version": "v1", "output": "rolled back"}


def test_scale_executor_execute_returns_output():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="scaled", stderr="")

    executor = ScaleActionExecutor(KubectlMutationClient(runner=fake_run))
    result = executor.execute(service="checkout-service", replicas=6)
    assert result == {"service": "checkout-service", "replicas": 6, "output": "scaled"}


def test_noop_executor_records_dry_run():
    executor = NoopActionExecutor(ActionType.SCALE)
    result = executor.execute(service="checkout-service", replicas=6)
    assert result == {
        "dry_run": True,
        "action": "scale",
        "arguments": {"service": "checkout-service", "replicas": 6},
    }


def test_action_registry_noop_has_all_mutating_types():
    registry = ActionRegistry.noop()
    for action_type in (ActionType.RESTART, ActionType.ROLLBACK, ActionType.SCALE):
        assert registry.get(action_type).action_type == action_type


def test_action_registry_get_unknown_raises_key_error():
    registry = ActionRegistry()
    with pytest.raises(KeyError, match="No executor registered"):
        registry.get(ActionType.RESTART)


def test_action_registry_kubectl_backed_executors_share_client():
    client = KubectlMutationClient(runner=lambda *a, **k: subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    registry = ActionRegistry.kubectl(client)
    assert registry.get(ActionType.RESTART).client is client
    assert registry.get(ActionType.ROLLBACK).client is client
    assert registry.get(ActionType.SCALE).client is client


def test_execute_action_refuses_without_approval(tmp_path: Path):
    audit = AuditTrail(tmp_path / "audit.jsonl")
    decision = ApprovalDecision(incident_id="alert-1", status=ApprovalStatus.REJECTED, approver="bob")
    with pytest.raises(ApprovalError, match="not approved"):
        execute_action("alert-1", ActionType.SCALE, {"service": "x", "replicas": 6}, decision, ActionRegistry.noop(), audit)


def test_execute_action_runs_executor_and_logs_success(tmp_path: Path):
    audit = AuditTrail(tmp_path / "audit.jsonl")
    decision = ApprovalDecision(incident_id="alert-1", status=ApprovalStatus.APPROVED, approver="bob")

    result = execute_action(
        "alert-1",
        ActionType.SCALE,
        {"service": "checkout-service", "replicas": 6},
        decision,
        ActionRegistry.noop(),
        audit,
    )

    assert result.success is True
    assert result.action == ActionType.SCALE

    events = audit.for_incident("alert-1")
    assert events[-1].event_type == EventType.ACTION_EXECUTED
    assert events[-1].payload["success"] is True


def test_execute_action_logs_failure_without_raising(tmp_path: Path):
    audit = AuditTrail(tmp_path / "audit.jsonl")
    decision = ApprovalDecision(incident_id="alert-1", status=ApprovalStatus.APPROVED, approver="bob")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    client = KubectlMutationClient(runner=fake_run)
    registry = ActionRegistry.kubectl(client)

    result = execute_action(
        "alert-1", ActionType.RESTART, {"service": "checkout-service"}, decision, registry, audit
    )

    assert result.success is False
    assert "boom" in result.output
    events = audit.for_incident("alert-1")
    assert events[-1].payload["success"] is False
