import json
from pathlib import Path

import requests

from oncall_agent.actions import ActionRegistry
from oncall_agent.approval import AutoApprovalGate, CLIApprovalGate
from oncall_agent.audit import AuditTrail
from oncall_agent.llm.ollama import OllamaProvider
from oncall_agent.llm.scripted import ScriptedPolicyProvider
from oncall_agent.models import ActionType, Alert, ApprovalStatus, EventType
from oncall_agent.response import respond_to_incident
from oncall_agent.tools.base import ToolRegistry
from oncall_agent.tools.fakes import FakePodStatusTool, FakeRecentDeploysTool


def make_registry(**overrides) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        FakeRecentDeploysTool(
            minutes_since_last_deploy=overrides.get("minutes_since_last_deploy", 10),
            version=overrides.get("version", "v2"),
            previous_version=overrides.get("previous_version", "v1"),
        )
    )
    registry.register(
        FakePodStatusTool(
            restarts=overrides.get("restarts", 3),
            oom_killed=overrides.get("oom_killed", False),
        )
    )
    return registry


def test_deploy_regression_is_approved_and_executed(tmp_path: Path):
    alert = Alert(title="High error rate", description="5xx spike", service="checkout-service")
    audit = AuditTrail(tmp_path / "audit.jsonl")

    response = respond_to_incident(
        alert,
        ScriptedPolicyProvider(),
        make_registry(),
        audit,
        AutoApprovalGate(),
        action_registry=ActionRegistry.noop(),
    )

    assert response.diagnosis.action == ActionType.ROLLBACK
    assert response.approval is not None
    assert response.approval.status == ApprovalStatus.APPROVED
    assert response.action_result is not None
    assert response.action_result.success is True

    event_types = [e.event_type for e in audit.for_incident(alert.id)]
    assert EventType.APPROVAL_REQUESTED in event_types
    assert EventType.APPROVAL_DECIDED in event_types
    assert EventType.ACTION_EXECUTED in event_types


def test_rejected_approval_skips_action_execution(tmp_path: Path):
    alert = Alert(title="High error rate", description="5xx spike", service="checkout-service")
    audit = AuditTrail(tmp_path / "audit.jsonl")
    gate = CLIApprovalGate(input_fn=lambda _: "n", print_fn=lambda _: None)

    response = respond_to_incident(
        alert, ScriptedPolicyProvider(), make_registry(), audit, gate, action_registry=ActionRegistry.noop()
    )

    assert response.approval.status == ApprovalStatus.REJECTED
    assert response.action_result is None
    event_types = [e.event_type for e in audit.for_incident(alert.id)]
    assert EventType.ACTION_EXECUTED not in event_types


def test_escalate_diagnosis_never_requests_approval(tmp_path: Path):
    alert = Alert(title="Elevated latency", description="p99 up 3x", service="checkout-service")
    audit = AuditTrail(tmp_path / "audit.jsonl")
    registry = make_registry(minutes_since_last_deploy=180, restarts=0, oom_killed=False)

    response = respond_to_incident(
        alert, ScriptedPolicyProvider(), registry, audit, AutoApprovalGate(), action_registry=ActionRegistry.noop()
    )

    assert response.diagnosis.action == ActionType.ESCALATE
    assert response.approval is None
    assert response.action_result is None
    event_types = [e.event_type for e in audit.for_incident(alert.id)]
    assert EventType.APPROVAL_REQUESTED not in event_types


def test_ollama_diagnosis_with_action_reaches_approval_gate(tmp_path: Path, monkeypatch):
    """Issue #6: once an Ollama diagnosis carries a non-null action, the
    approval gate must actually be reached, not short-circuited.
    """
    decision = {
        "action": "diagnose",
        "diagnosis": {
            "root_cause": "bad deploy",
            "confidence": 0.9,
            "evidence": ["deploy 10m ago"],
            "proposed_fix": "roll back checkout-service to v1.2.3",
            "requires_approval": True,
            "category": "deploy_regression",
            "action": "rollback",
            "action_arguments": {"service": "checkout-service", "version": "v1.2.3"},
        },
    }

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"response": json.dumps(decision)}

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())

    alert = Alert(title="High error rate", description="5xx spike", service="checkout-service")
    audit = AuditTrail(tmp_path / "audit.jsonl")

    response = respond_to_incident(
        alert,
        OllamaProvider(),
        make_registry(),
        audit,
        AutoApprovalGate(),
        action_registry=ActionRegistry.noop(),
    )

    assert response.diagnosis.action == ActionType.ROLLBACK
    assert response.approval is not None
    assert response.approval.status == ApprovalStatus.APPROVED
    event_types = [e.event_type for e in audit.for_incident(alert.id)]
    assert EventType.APPROVAL_REQUESTED in event_types


def test_approved_without_action_registry_stops_before_executing(tmp_path: Path):
    alert = Alert(title="High error rate", description="5xx spike", service="checkout-service")
    audit = AuditTrail(tmp_path / "audit.jsonl")

    response = respond_to_incident(alert, ScriptedPolicyProvider(), make_registry(), audit, AutoApprovalGate())

    assert response.approval.status == ApprovalStatus.APPROVED
    assert response.action_result is None
