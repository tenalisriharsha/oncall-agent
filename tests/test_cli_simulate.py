from click.testing import CliRunner

from oncall_agent.cli import main


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
