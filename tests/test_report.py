import json
from pathlib import Path

import pytest

from oncall_agent.models import ActionType, Alert, Diagnosis, Hypothesis
from oncall_agent.report import diagnosis_report_dict, export_report, render_markdown


def make_alert() -> Alert:
    return Alert(title="High error rate", description="5xx spike", service="checkout-service")


def make_diagnosis() -> Diagnosis:
    return Diagnosis(
        root_cause="Regression introduced by a bad deploy.",
        confidence=0.8,
        evidence=["Deploy 10 minutes before the alert."],
        proposed_fix="Roll back checkout-service to v1.",
        hypotheses_considered=[
            Hypothesis(statement="deploy regression", confidence=0.75, category="deploy_regression"),
        ],
    )


def test_diagnosis_report_dict_contains_alert_and_diagnosis():
    report = diagnosis_report_dict(make_alert(), make_diagnosis())
    assert report["alert"]["service"] == "checkout-service"
    assert report["diagnosis"]["root_cause"] == "Regression introduced by a bad deploy."


def test_render_markdown_includes_core_fields():
    markdown = render_markdown(make_alert(), make_diagnosis())
    assert "# Incident report" in markdown
    assert "Roll back checkout-service to v1." in markdown
    assert "Deploy 10 minutes before the alert." in markdown
    assert "deploy regression" in markdown


def test_render_markdown_includes_action_when_present():
    diagnosis = Diagnosis(
        root_cause="bad deploy",
        confidence=0.8,
        proposed_fix="roll back",
        action=ActionType.ROLLBACK,
        action_arguments={"service": "checkout-service", "to_version": "v1"},
    )
    markdown = render_markdown(make_alert(), diagnosis)
    assert "**Action:** rollback" in markdown


def test_render_markdown_shows_none_action_placeholder():
    diagnosis = Diagnosis(root_cause="unknown", confidence=0.3, proposed_fix="escalate")
    markdown = render_markdown(make_alert(), diagnosis)
    assert "**Action:** (none)" in markdown


def test_render_markdown_without_hypotheses_omits_that_section():
    diagnosis = Diagnosis(root_cause="unknown", confidence=0.3, proposed_fix="escalate")
    markdown = render_markdown(make_alert(), diagnosis)
    assert "Hypotheses considered" not in markdown


def test_render_markdown_with_no_evidence_shows_placeholder():
    diagnosis = Diagnosis(root_cause="unknown", confidence=0.3, proposed_fix="escalate")
    markdown = render_markdown(make_alert(), diagnosis)
    assert "(none recorded)" in markdown


def test_export_report_writes_markdown_by_default(tmp_path: Path):
    path = export_report(make_alert(), make_diagnosis(), tmp_path / "report.md")
    assert path.exists()
    assert "Incident report" in path.read_text()


def test_export_report_writes_json(tmp_path: Path):
    path = export_report(make_alert(), make_diagnosis(), tmp_path / "report.json", fmt="json")
    data = json.loads(path.read_text())
    assert data["diagnosis"]["proposed_fix"] == "Roll back checkout-service to v1."


def test_export_report_creates_parent_directories(tmp_path: Path):
    path = export_report(make_alert(), make_diagnosis(), tmp_path / "nested" / "report.md")
    assert path.exists()


def test_export_report_rejects_unknown_format(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown report format"):
        export_report(make_alert(), make_diagnosis(), tmp_path / "report.txt", fmt="yaml")
