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
