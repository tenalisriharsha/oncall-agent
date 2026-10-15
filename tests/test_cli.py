import subprocess

import requests
from click.testing import CliRunner

from oncall_agent import __version__
from oncall_agent.cli import main


def test_version_command_prints_version():
    result = CliRunner().invoke(main, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_config_command_shows_default_provider():
    result = CliRunner().invoke(main, ["config"])
    assert result.exit_code == 0
    assert "scripted" in result.output


def test_demo_deploy_regression_scenario(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    result = CliRunner().invoke(
        main, ["demo", "--scenario", "deploy-regression", "--audit-log", str(log_path)]
    )
    assert result.exit_code == 0
    assert "Diagnosis" in result.output
    assert log_path.exists()


def test_demo_oom_scenario(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    result = CliRunner().invoke(
        main, ["demo", "--scenario", "oom", "--audit-log", str(log_path)]
    )
    assert result.exit_code == 0
    assert "memory" in result.output.lower()


def test_demo_unknown_scenario(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    result = CliRunner().invoke(
        main, ["demo", "--scenario", "unknown", "--audit-log", str(log_path)]
    )
    assert result.exit_code == 0
    assert "escalate" in result.output.lower()


def test_audit_command_with_no_events_warns(tmp_path):
    log_path = tmp_path / "missing.jsonl"
    result = CliRunner().invoke(main, ["audit", "--audit-log", str(log_path)])
    assert result.exit_code == 0
    assert "No audit events found" in result.output


def test_audit_command_after_demo_shows_events(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    runner = CliRunner()
    runner.invoke(main, ["demo", "--scenario", "deploy-regression", "--audit-log", str(log_path)])
    result = runner.invoke(main, ["audit", "--audit-log", str(log_path)])
    assert result.exit_code == 0
    assert "diagnosis_reached" in result.output


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def test_tools_query_prometheus_success(monkeypatch):
    payload = {"status": "success", "data": {"resultType": "vector", "result": []}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200, payload))

    result = CliRunner().invoke(main, ["tools", "query-prometheus", "up", "--url", "http://prom:9090"])

    assert result.exit_code == 0
    assert "vector" in result.output


def test_tools_query_prometheus_failure(monkeypatch):
    def raise_error(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", raise_error)

    result = CliRunner().invoke(main, ["tools", "query-prometheus", "up"])

    assert result.exit_code == 1
    assert "Could not reach Prometheus" in result.output


def test_tools_pod_status_success(monkeypatch):
    pods = {
        "items": [
            {"status": {"containerStatuses": [{"restartCount": 4, "lastState": {}}]}},
        ]
    }

    def fake_run(cmd, **kwargs):
        import json

        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(pods), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CliRunner().invoke(main, ["tools", "pod-status", "checkout-service"])

    assert result.exit_code == 0
    assert '"restarts": 4' in result.output


def test_tools_pod_status_kubectl_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="connection refused")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CliRunner().invoke(main, ["tools", "pod-status", "checkout-service"])

    assert result.exit_code == 1
    assert "connection refused" in result.output


def test_tools_logs_success(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="boot ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CliRunner().invoke(main, ["tools", "logs", "checkout-service-abc123", "--tail", "50"])

    assert result.exit_code == 0
    assert "boot ok" in result.output


def test_tools_logs_kubectl_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="pod not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CliRunner().invoke(main, ["tools", "logs", "checkout-service-abc123"])

    assert result.exit_code == 1
    assert "pod not found" in result.output


def test_tools_record_and_read_deploy_history(tmp_path, monkeypatch):
    log_path = tmp_path / "deploys.jsonl"
    monkeypatch.setenv("ONCALL_AGENT_DEPLOY_HISTORY_PATH", str(log_path))
    runner = CliRunner()

    record_result = runner.invoke(
        main,
        ["tools", "record-deploy", "checkout-service", "v2.5.0", "--previous-version", "v2.4.1"],
    )
    assert record_result.exit_code == 0
    assert "Recorded deploy" in record_result.output

    history_result = runner.invoke(main, ["tools", "deploy-history", "checkout-service"])
    assert history_result.exit_code == 0
    assert "v2.5.0" in history_result.output


def test_tools_deploy_history_with_no_records(tmp_path, monkeypatch):
    monkeypatch.setenv("ONCALL_AGENT_DEPLOY_HISTORY_PATH", str(tmp_path / "deploys.jsonl"))

    result = CliRunner().invoke(main, ["tools", "deploy-history", "checkout-service"])

    assert result.exit_code == 0
    assert "null" in result.output


def test_tools_search_runbooks_finds_match(monkeypatch):
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
    monkeypatch.setenv("ONCALL_AGENT_RUNBOOK_DIR", f"{repo_root}/runbooks")

    result = CliRunner().invoke(main, ["tools", "search-runbooks", "deploy regression rollback"])

    assert result.exit_code == 0
    assert "deploy-regression" in result.output


def test_tools_search_runbooks_no_match(tmp_path, monkeypatch):
    monkeypatch.setenv("ONCALL_AGENT_RUNBOOK_DIR", str(tmp_path))

    result = CliRunner().invoke(main, ["tools", "search-runbooks", "deploy"])

    assert result.exit_code == 0
    assert "No runbook matches" in result.output
