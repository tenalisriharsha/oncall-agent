from pathlib import Path

import requests

from oncall_agent.approval import AutoApprovalGate, CLIApprovalGate, SlackApprovalGate, SlackDecisionInbox
from oncall_agent.models import ActionType, ApprovalDecision, ApprovalStatus, Diagnosis


def make_diagnosis() -> Diagnosis:
    return Diagnosis(
        root_cause="bad deploy",
        confidence=0.8,
        proposed_fix="Roll back checkout-service to v1.",
        action=ActionType.ROLLBACK,
        action_arguments={"service": "checkout-service", "to_version": "v1"},
    )


def test_cli_gate_approves_on_yes():
    printed = []
    gate = CLIApprovalGate(approver="alice", input_fn=lambda _: "y", print_fn=printed.append)
    decision = gate.request_approval("alert-1", make_diagnosis())
    assert decision.status == ApprovalStatus.APPROVED
    assert decision.approver == "alice"
    assert any("checkout-service" in line for line in printed)


def test_cli_gate_rejects_on_anything_else():
    gate = CLIApprovalGate(input_fn=lambda _: "n", print_fn=lambda _: None)
    decision = gate.request_approval("alert-1", make_diagnosis())
    assert decision.status == ApprovalStatus.REJECTED
    assert decision.reason


def test_cli_gate_rejects_on_empty_input():
    gate = CLIApprovalGate(input_fn=lambda _: "", print_fn=lambda _: None)
    decision = gate.request_approval("alert-1", make_diagnosis())
    assert decision.status == ApprovalStatus.REJECTED


def test_auto_gate_always_approves():
    gate = AutoApprovalGate(approver="ci")
    decision = gate.request_approval("alert-1", make_diagnosis())
    assert decision.status == ApprovalStatus.APPROVED
    assert decision.approver == "ci"


def test_slack_decision_inbox_round_trips(tmp_path: Path):
    inbox = SlackDecisionInbox(tmp_path / "decisions.jsonl")
    assert inbox.decision_for("alert-1") is None

    decision = ApprovalDecision(incident_id="alert-1", status=ApprovalStatus.APPROVED, approver="bob")
    inbox.record(decision)

    found = inbox.decision_for("alert-1")
    assert found is not None
    assert found.approver == "bob"
    assert inbox.decision_for("alert-2") is None


def test_slack_decision_inbox_returns_latest_decision(tmp_path: Path):
    inbox = SlackDecisionInbox(tmp_path / "decisions.jsonl")
    inbox.record(ApprovalDecision(incident_id="alert-1", status=ApprovalStatus.REJECTED, approver="bob"))
    inbox.record(ApprovalDecision(incident_id="alert-1", status=ApprovalStatus.APPROVED, approver="carol"))

    found = inbox.decision_for("alert-1")
    assert found.approver == "carol"
    assert found.status == ApprovalStatus.APPROVED


def test_slack_gate_posts_request_and_returns_inbox_decision(tmp_path: Path):
    inbox = SlackDecisionInbox(tmp_path / "decisions.jsonl")
    inbox.record(ApprovalDecision(incident_id="alert-1", status=ApprovalStatus.APPROVED, approver="dana"))

    posted = []
    gate = SlackApprovalGate(inbox=inbox, poster=lambda url, msg: posted.append((url, msg)))
    decision = gate.request_approval("alert-1", make_diagnosis())

    assert decision.approver == "dana"
    assert len(posted) == 1
    assert "checkout-service" in posted[0][1]


def test_slack_gate_times_out_when_no_decision_arrives(tmp_path: Path):
    inbox = SlackDecisionInbox(tmp_path / "decisions.jsonl")
    clock = iter([0.0, 0.0, 10.0, 20.0])
    gate = SlackApprovalGate(
        inbox=inbox,
        poster=lambda url, msg: None,
        timeout=15.0,
        poll_interval=1.0,
        sleep_fn=lambda _: None,
        clock=lambda: next(clock),
    )
    decision = gate.request_approval("alert-1", make_diagnosis())
    assert decision.status == ApprovalStatus.REJECTED
    assert decision.approver == "timeout"


def test_slack_gate_default_poster_prints_when_no_webhook_configured(capsys):
    inbox = SlackDecisionInbox(Path("/tmp/does-not-matter.jsonl"))
    gate = SlackApprovalGate(inbox=inbox, webhook_url=None, timeout=0, poll_interval=0, sleep_fn=lambda _: None)
    gate.request_approval("alert-1", make_diagnosis())
    out = capsys.readouterr().out
    assert "no webhook configured" in out


def test_slack_gate_default_poster_posts_to_webhook_when_configured(tmp_path: Path, monkeypatch):
    inbox = SlackDecisionInbox(tmp_path / "decisions.jsonl")
    inbox.record(ApprovalDecision(incident_id="alert-1", status=ApprovalStatus.APPROVED, approver="dana"))

    posted = {}

    def fake_post(url, json=None, timeout=None):
        posted["url"] = url
        posted["json"] = json

    monkeypatch.setattr(requests, "post", fake_post)

    gate = SlackApprovalGate(inbox=inbox, webhook_url="https://hooks.slack.test/abc")
    decision = gate.request_approval("alert-1", make_diagnosis())

    assert decision.approver == "dana"
    assert posted["url"] == "https://hooks.slack.test/abc"
    assert "checkout-service" in posted["json"]["text"]


def test_slack_decision_inbox_skips_blank_lines(tmp_path: Path):
    path = tmp_path / "decisions.jsonl"
    decision = ApprovalDecision(incident_id="alert-1", status=ApprovalStatus.APPROVED, approver="bob")
    path.write_text(f"\n{decision.model_dump_json()}\n\n")

    inbox = SlackDecisionInbox(path)
    found = inbox.decision_for("alert-1")
    assert found is not None
    assert found.approver == "bob"
