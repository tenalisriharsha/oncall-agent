import json

import requests
from click.testing import CliRunner

from oncall_agent.cli import main


class _FakeOllamaResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


_ALWAYS_DIAGNOSE_DECISION = json.dumps(
    {
        "action": "diagnose",
        "diagnosis": {
            "root_cause": "stubbed diagnosis",
            "confidence": 0.5,
            "proposed_fix": "escalate",
        },
    }
)


def test_simulate_list_shows_every_scenario(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    result = CliRunner().invoke(main, ["simulate", "list"])
    assert result.exit_code == 0
    for name in ("bad-deploy", "oom-crash-loop", "dependency-outage", "network-partition", "disk-pressure", "config-drift"):
        assert name in result.output


def test_simulate_run_bad_deploy(tmp_path):
    log_path = tmp_path / "sim.jsonl"
    result = CliRunner().invoke(
        main, ["simulate", "run", "bad-deploy", "--audit-log", str(log_path)]
    )
    assert result.exit_code == 0
    assert "Diagnosis" in result.output
    assert "rollback" in result.output.lower()
    assert log_path.exists()


def test_simulate_run_unknown_scenario_fails():
    result = CliRunner().invoke(main, ["simulate", "run", "does-not-exist"])
    assert result.exit_code != 0
    assert "Unknown scenario" in result.output


def test_simulate_run_all_prints_a_row_per_scenario(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    log_path = tmp_path / "sim.jsonl"
    result = CliRunner().invoke(
        main, ["simulate", "run-all", "--audit-log", str(log_path)]
    )
    assert result.exit_code == 0
    for name in ("bad-deploy", "oom-crash-loop", "dependency-outage"):
        assert name in result.output
    assert log_path.exists()


def test_simulate_scorecard_prints_accuracy_summary(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    result = CliRunner().invoke(main, ["simulate", "scorecard"])
    assert result.exit_code == 0
    assert "Root-cause accuracy" in result.output
    assert "Action accuracy" in result.output
    for name in ("bad-deploy", "oom-crash-loop", "network-partition"):
        assert name in result.output


def test_simulate_scorecard_writes_a_report(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    report_path = tmp_path / "scorecard.md"
    result = CliRunner().invoke(main, ["simulate", "scorecard", "--report", str(report_path)])
    assert result.exit_code == 0
    assert report_path.exists()
    assert "scorecard" in report_path.read_text().lower()


def test_simulate_scorecard_rejects_unknown_provider():
    result = CliRunner().invoke(main, ["simulate", "scorecard", "--provider", "bogus"])
    assert result.exit_code != 0


def test_simulate_compare_falls_back_to_scripted_only_when_ollama_unreachable(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("ONCALL_AGENT_OLLAMA_URL", "http://localhost:1")
    result = CliRunner().invoke(main, ["simulate", "compare"])
    assert result.exit_code == 0
    assert "scripted" in result.output
    assert "unavailable" in result.output.lower()


def test_simulate_compare_writes_a_report(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("ONCALL_AGENT_OLLAMA_URL", "http://localhost:1")
    report_path = tmp_path / "comparison.md"
    result = CliRunner().invoke(main, ["simulate", "compare", "--report", str(report_path)])
    assert result.exit_code == 0
    assert report_path.exists()
    assert "scripted" in report_path.read_text().lower()


def test_simulate_scorecard_with_ollama_provider_unreachable_exits_nonzero(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")

    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", raise_connection_error)
    result = CliRunner().invoke(main, ["simulate", "scorecard", "--provider", "ollama"])
    assert result.exit_code != 0
    assert "Could not reach Ollama" in result.output


def test_simulate_scorecard_with_a_reachable_ollama_provider(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: _FakeOllamaResponse({"response": _ALWAYS_DIAGNOSE_DECISION})
    )
    result = CliRunner().invoke(main, ["simulate", "scorecard", "--provider", "ollama"])
    assert result.exit_code == 0
    assert "ollama" in result.output.lower()


def test_simulate_compare_includes_ollama_when_reachable(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: _FakeOllamaResponse({"response": _ALWAYS_DIAGNOSE_DECISION})
    )
    result = CliRunner().invoke(main, ["simulate", "compare"])
    assert result.exit_code == 0
    assert "scripted" in result.output.lower()
    assert "ollama" in result.output.lower()
    assert "unavailable" not in result.output.lower()
