from pathlib import Path

import pytest

from oncall_agent.audit import AuditTrail
from oncall_agent.investigation import InvestigationError, run_investigation
from oncall_agent.llm.base import LLMAction, LLMProvider, LLMRequest, LLMResponse
from oncall_agent.llm.scripted import ScriptedPolicyProvider
from oncall_agent.models import Alert, EventType
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


def test_deploy_regression_scenario_reaches_diagnosis(tmp_path: Path):
    alert = Alert(title="High error rate", description="5xx spike", service="checkout-service")
    audit = AuditTrail(tmp_path / "audit.jsonl")

    diagnosis = run_investigation(alert, ScriptedPolicyProvider(), make_registry(), audit)

    assert "regression" in diagnosis.root_cause.lower()
    assert diagnosis.requires_approval is True

    events = audit.for_incident(alert.id)
    event_types = [e.event_type for e in events]
    assert event_types[0] == EventType.ALERT_RECEIVED
    assert EventType.TOOL_CALL in event_types
    assert EventType.HYPOTHESIS_FORMED in event_types
    assert event_types[-1] == EventType.DIAGNOSIS_REACHED


def test_oom_scenario_reaches_diagnosis(tmp_path: Path):
    alert = Alert(title="Crash loop", description="pods restarting", service="checkout-service")
    audit = AuditTrail(tmp_path / "audit.jsonl")
    registry = make_registry(minutes_since_last_deploy=300, restarts=20, oom_killed=True)

    diagnosis = run_investigation(alert, ScriptedPolicyProvider(), registry, audit)

    assert "oomkilled" in diagnosis.root_cause.lower()
    assert "memory" in diagnosis.proposed_fix.lower()


def test_audit_trail_records_every_tool_call(tmp_path: Path):
    alert = Alert(title="t", description="d", service="checkout-service")
    audit = AuditTrail(tmp_path / "audit.jsonl")

    run_investigation(alert, ScriptedPolicyProvider(), make_registry(), audit)

    tool_calls = [e for e in audit.for_incident(alert.id) if e.event_type == EventType.TOOL_CALL]
    tools_called = {e.payload["tool"] for e in tool_calls}
    assert tools_called == {"get_recent_deploys", "get_pod_status"}


class _StuckProvider(LLMProvider):
    name = "stuck"

    def decide(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            action=LLMAction.CALL_TOOL,
            tool_name="get_recent_deploys",
            tool_arguments={"service": request.alert.service},
        )


def test_raises_investigation_error_when_it_does_not_converge(tmp_path: Path):
    alert = Alert(title="t", description="d", service="checkout-service")
    audit = AuditTrail(tmp_path / "audit.jsonl")

    with pytest.raises(InvestigationError):
        run_investigation(alert, _StuckProvider(), make_registry(), audit, max_steps=3)
