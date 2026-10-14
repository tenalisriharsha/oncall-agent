from oncall_agent.llm.base import LLMAction, LLMRequest
from oncall_agent.llm.scripted import ScriptedPolicyProvider
from oncall_agent.models import Alert, Hypothesis, ToolCallRecord


def make_alert(**overrides) -> Alert:
    defaults = dict(title="High error rate", description="5xx spike", service="checkout-service")
    defaults.update(overrides)
    return Alert(**defaults)


def test_first_decision_is_always_to_check_deploys():
    provider = ScriptedPolicyProvider()
    response = provider.decide(LLMRequest(alert=make_alert()))
    assert response.action == LLMAction.CALL_TOOL
    assert response.tool_name == "get_recent_deploys"
    assert response.tool_arguments == {"service": "checkout-service"}


def test_recent_deploy_forms_high_confidence_regression_hypothesis():
    provider = ScriptedPolicyProvider()
    deploy_record = ToolCallRecord(
        tool="get_recent_deploys",
        result={"minutes_since_last_deploy": 10, "version": "v2", "previous_version": "v1"},
    )
    response = provider.decide(LLMRequest(alert=make_alert(), tool_results=[deploy_record]))
    assert response.action == LLMAction.FORM_HYPOTHESIS
    assert response.hypothesis.confidence == 0.75
    assert "v2" in response.hypothesis.statement


def test_old_deploy_forms_low_confidence_hypothesis():
    provider = ScriptedPolicyProvider()
    deploy_record = ToolCallRecord(
        tool="get_recent_deploys",
        result={"minutes_since_last_deploy": 180, "version": "v2", "previous_version": "v1"},
    )
    response = provider.decide(LLMRequest(alert=make_alert(), tool_results=[deploy_record]))
    assert response.action == LLMAction.FORM_HYPOTHESIS
    assert response.hypothesis.confidence == 0.4


def test_after_hypothesis_checks_pod_status_next():
    provider = ScriptedPolicyProvider()
    deploy_record = ToolCallRecord(
        tool="get_recent_deploys",
        result={"minutes_since_last_deploy": 10, "version": "v2", "previous_version": "v1"},
    )
    response = provider.decide(
        LLMRequest(
            alert=make_alert(),
            tool_results=[deploy_record],
            hypotheses=[Hypothesis(statement="h", confidence=0.5)],
        )
    )
    assert response.action == LLMAction.CALL_TOOL
    assert response.tool_name == "get_pod_status"


def test_diagnoses_deploy_regression_with_rollback_fix():
    provider = ScriptedPolicyProvider()
    tool_results = [
        ToolCallRecord(
            tool="get_recent_deploys",
            result={"minutes_since_last_deploy": 10, "version": "v2", "previous_version": "v1"},
        ),
        ToolCallRecord(tool="get_pod_status", result={"restarts": 3, "oom_killed": False}),
    ]
    response = provider.decide(
        LLMRequest(
            alert=make_alert(),
            tool_results=tool_results,
            hypotheses=[Hypothesis(statement="h", confidence=0.75)],
        )
    )
    assert response.action == LLMAction.DIAGNOSE
    assert "v1" in response.diagnosis.proposed_fix
    assert response.diagnosis.requires_approval is True


def test_diagnoses_oom_without_recent_deploy():
    provider = ScriptedPolicyProvider()
    tool_results = [
        ToolCallRecord(
            tool="get_recent_deploys",
            result={"minutes_since_last_deploy": 300, "version": "v2", "previous_version": "v1"},
        ),
        ToolCallRecord(tool="get_pod_status", result={"restarts": 20, "oom_killed": True}),
    ]
    response = provider.decide(
        LLMRequest(
            alert=make_alert(),
            tool_results=tool_results,
            hypotheses=[Hypothesis(statement="h", confidence=0.4)],
        )
    )
    assert response.action == LLMAction.DIAGNOSE
    assert "memory" in response.diagnosis.proposed_fix.lower()


def test_diagnoses_unknown_cause_when_no_signal_found():
    provider = ScriptedPolicyProvider()
    tool_results = [
        ToolCallRecord(
            tool="get_recent_deploys",
            result={"minutes_since_last_deploy": 300, "version": "v2", "previous_version": "v1"},
        ),
        ToolCallRecord(tool="get_pod_status", result={"restarts": 0, "oom_killed": False}),
    ]
    response = provider.decide(
        LLMRequest(
            alert=make_alert(),
            tool_results=tool_results,
            hypotheses=[Hypothesis(statement="h", confidence=0.4)],
        )
    )
    assert response.action == LLMAction.DIAGNOSE
    assert response.diagnosis.confidence < 0.5


def test_is_deterministic_for_same_input():
    provider = ScriptedPolicyProvider()
    request = LLMRequest(alert=make_alert())
    first = provider.decide(request)
    second = provider.decide(request)
    assert first == second
