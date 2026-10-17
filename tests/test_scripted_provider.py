from oncall_agent.llm.base import LLMAction, LLMRequest
from oncall_agent.llm.scripted import ScriptedPolicyProvider
from oncall_agent.models import ActionType, Alert, Hypothesis, ToolCallRecord


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
    assert response.diagnosis.action == ActionType.ROLLBACK
    assert response.diagnosis.action_arguments == {"service": "checkout-service", "to_version": "v1"}


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
    assert response.diagnosis.action == ActionType.SCALE
    assert response.diagnosis.action_arguments["service"] == "checkout-service"
    assert response.diagnosis.action_arguments["replicas"] > 0


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
    assert response.diagnosis.action == ActionType.ESCALATE


def test_is_deterministic_for_same_input():
    provider = ScriptedPolicyProvider()
    request = LLMRequest(alert=make_alert())
    first = provider.decide(request)
    second = provider.decide(request)
    assert first == second


def test_recent_deploy_hypothesis_is_tagged_deploy_regression():
    provider = ScriptedPolicyProvider()
    deploy_record = ToolCallRecord(
        tool="get_recent_deploys",
        result={"minutes_since_last_deploy": 10, "version": "v2", "previous_version": "v1"},
    )
    response = provider.decide(LLMRequest(alert=make_alert(), tool_results=[deploy_record]))
    assert response.hypothesis.category == "deploy_regression"


def test_old_deploy_hypothesis_is_tagged_resource_exhaustion():
    provider = ScriptedPolicyProvider()
    deploy_record = ToolCallRecord(
        tool="get_recent_deploys",
        result={"minutes_since_last_deploy": 180, "version": "v2", "previous_version": "v1"},
    )
    response = provider.decide(LLMRequest(alert=make_alert(), tool_results=[deploy_record]))
    assert response.hypothesis.category == "resource_exhaustion"


def test_pod_health_with_no_signal_triggers_a_revision():
    provider = ScriptedPolicyProvider()
    tool_results = [
        ToolCallRecord(
            tool="get_recent_deploys",
            result={"minutes_since_last_deploy": 180, "version": "v2", "previous_version": "v1"},
        ),
        ToolCallRecord(tool="get_pod_status", result={"restarts": 0, "oom_killed": False}),
    ]
    hypotheses = [
        Hypothesis(
            statement="resource exhaustion guess",
            confidence=0.4,
            category="resource_exhaustion",
        )
    ]
    response = provider.decide(
        LLMRequest(alert=make_alert(), tool_results=tool_results, hypotheses=hypotheses)
    )

    assert response.action == LLMAction.FORM_HYPOTHESIS
    assert response.is_revision is True
    assert response.hypothesis.category == "dependency_failure"


def test_pod_health_with_a_restart_does_not_trigger_a_revision():
    provider = ScriptedPolicyProvider()
    tool_results = [
        ToolCallRecord(
            tool="get_recent_deploys",
            result={"minutes_since_last_deploy": 10, "version": "v2", "previous_version": "v1"},
        ),
        ToolCallRecord(tool="get_pod_status", result={"restarts": 1, "oom_killed": False}),
    ]
    hypotheses = [
        Hypothesis(statement="deploy guess", confidence=0.75, category="deploy_regression")
    ]
    response = provider.decide(
        LLMRequest(alert=make_alert(), tool_results=tool_results, hypotheses=hypotheses)
    )

    assert response.action == LLMAction.DIAGNOSE


def test_a_second_hypothesis_is_never_revised_again():
    provider = ScriptedPolicyProvider()
    tool_results = [
        ToolCallRecord(
            tool="get_recent_deploys",
            result={"minutes_since_last_deploy": 180, "version": "v2", "previous_version": "v1"},
        ),
        ToolCallRecord(tool="get_pod_status", result={"restarts": 0, "oom_killed": False}),
    ]
    hypotheses = [
        Hypothesis(statement="first", confidence=0.4, category="resource_exhaustion"),
        Hypothesis(statement="revised", confidence=0.55, category="dependency_failure"),
    ]
    response = provider.decide(
        LLMRequest(alert=make_alert(), tool_results=tool_results, hypotheses=hypotheses)
    )

    assert response.action == LLMAction.DIAGNOSE


def test_diagnosis_after_revision_escalates_to_dependency_failure():
    provider = ScriptedPolicyProvider()
    tool_results = [
        ToolCallRecord(
            tool="get_recent_deploys",
            result={"minutes_since_last_deploy": 180, "version": "v2", "previous_version": "v1"},
        ),
        ToolCallRecord(tool="get_pod_status", result={"restarts": 0, "oom_killed": False}),
    ]
    hypotheses = [
        Hypothesis(statement="first", confidence=0.4, category="resource_exhaustion"),
        Hypothesis(statement="revised", confidence=0.55, category="dependency_failure"),
    ]
    response = provider.decide(
        LLMRequest(alert=make_alert(), tool_results=tool_results, hypotheses=hypotheses)
    )

    assert response.action == LLMAction.DIAGNOSE
    assert "dependency" in response.diagnosis.proposed_fix.lower()
    assert response.diagnosis.hypotheses_considered == [hypotheses[1], hypotheses[0]]
    assert response.diagnosis.action == ActionType.ESCALATE


def test_diagnosis_always_attaches_ranked_hypotheses_considered():
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
    assert response.diagnosis.hypotheses_considered == [Hypothesis(statement="h", confidence=0.75)]
