from pathlib import Path

from oncall_agent.audit import AuditTrail
from oncall_agent.models import AuditEvent, EventType


def test_reading_missing_log_returns_empty_list(tmp_path: Path):
    trail = AuditTrail(tmp_path / "audit.jsonl")
    assert trail.read_all() == []


def test_log_appends_without_truncating_previous_entries(tmp_path: Path):
    trail = AuditTrail(tmp_path / "nested" / "audit.jsonl")
    trail.log(AuditEvent(incident_id="a1", event_type=EventType.ALERT_RECEIVED, payload={}))
    trail.log(AuditEvent(incident_id="a1", event_type=EventType.TOOL_CALL, payload={"tool": "x"}))

    events = trail.read_all()
    assert len(events) == 2
    assert events[0].event_type == EventType.ALERT_RECEIVED
    assert events[1].event_type == EventType.TOOL_CALL
    assert events[1].payload == {"tool": "x"}


def test_creates_parent_directories(tmp_path: Path):
    path = tmp_path / "deep" / "nested" / "dir" / "audit.jsonl"
    AuditTrail(path)
    assert path.parent.is_dir()


def test_for_incident_filters_by_id(tmp_path: Path):
    trail = AuditTrail(tmp_path / "audit.jsonl")
    trail.log(AuditEvent(incident_id="a1", event_type=EventType.ALERT_RECEIVED, payload={}))
    trail.log(AuditEvent(incident_id="a2", event_type=EventType.ALERT_RECEIVED, payload={}))
    trail.log(AuditEvent(incident_id="a1", event_type=EventType.DIAGNOSIS_REACHED, payload={}))

    a1_events = trail.for_incident("a1")
    assert len(a1_events) == 2
    assert all(e.incident_id == "a1" for e in a1_events)


def test_persists_across_instances(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    AuditTrail(path).log(AuditEvent(incident_id="a1", event_type=EventType.ALERT_RECEIVED, payload={}))
    reopened = AuditTrail(path)
    assert len(reopened.read_all()) == 1


def test_ignores_blank_lines(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.log(AuditEvent(incident_id="a1", event_type=EventType.ALERT_RECEIVED, payload={}))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n\n")
    assert len(trail.read_all()) == 1
