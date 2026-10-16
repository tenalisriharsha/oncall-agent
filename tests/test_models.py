from datetime import timezone

import pytest
from pydantic import ValidationError

from oncall_agent.models import (
    Alert,
    AuditEvent,
    Diagnosis,
    EventType,
    Hypothesis,
    Severity,
    ToolCallRecord,
)


def test_alert_defaults_id_and_severity_and_timestamp():
    alert = Alert(title="High error rate", description="5xx spike", service="checkout")
    assert alert.id.startswith("alert-")
    assert alert.severity == Severity.MEDIUM
    assert alert.fired_at.tzinfo is not None
    assert alert.fired_at.tzinfo == timezone.utc


def test_alert_ids_are_unique():
    a1 = Alert(title="t", description="d", service="s")
    a2 = Alert(title="t", description="d", service="s")
    assert a1.id != a2.id


def test_hypothesis_confidence_bounds():
    Hypothesis(statement="ok", confidence=0.0)
    Hypothesis(statement="ok", confidence=1.0)
    with pytest.raises(ValidationError):
        Hypothesis(statement="bad", confidence=1.5)
    with pytest.raises(ValidationError):
        Hypothesis(statement="bad", confidence=-0.1)


def test_diagnosis_requires_approval_by_default():
    diagnosis = Diagnosis(
        root_cause="bad deploy",
        confidence=0.9,
        proposed_fix="roll back",
    )
    assert diagnosis.requires_approval is True


def test_hypothesis_category_defaults_to_none():
    hypothesis = Hypothesis(statement="ok", confidence=0.5)
    assert hypothesis.category is None


def test_hypothesis_category_can_be_set():
    hypothesis = Hypothesis(statement="ok", confidence=0.5, category="deploy_regression")
    assert hypothesis.category == "deploy_regression"


def test_diagnosis_hypotheses_considered_defaults_to_empty_list():
    diagnosis = Diagnosis(root_cause="bad deploy", confidence=0.9, proposed_fix="roll back")
    assert diagnosis.hypotheses_considered == []


def test_diagnosis_hypotheses_considered_round_trips():
    hypothesis = Hypothesis(statement="h", confidence=0.6, category="dependency_failure")
    diagnosis = Diagnosis(
        root_cause="bad deploy",
        confidence=0.9,
        proposed_fix="roll back",
        hypotheses_considered=[hypothesis],
    )
    restored = Diagnosis.model_validate_json(diagnosis.model_dump_json())
    assert restored.hypotheses_considered == [hypothesis]


def test_event_type_includes_hypothesis_revised():
    assert EventType.HYPOTHESIS_REVISED.value == "hypothesis_revised"


def test_tool_call_record_defaults():
    record = ToolCallRecord(tool="get_recent_deploys", arguments={"service": "checkout"})
    assert record.result is None
    assert record.is_mutating is False


def test_audit_event_round_trips_through_json():
    event = AuditEvent(
        incident_id="alert-1234",
        event_type=EventType.ALERT_RECEIVED,
        payload={"title": "High error rate"},
    )
    restored = AuditEvent.model_validate_json(event.model_dump_json())
    assert restored.incident_id == event.incident_id
    assert restored.event_type == EventType.ALERT_RECEIVED
    assert restored.payload == {"title": "High error rate"}
    assert restored.timestamp == event.timestamp
