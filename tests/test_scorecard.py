from pathlib import Path

from oncall_agent.models import ActionType
from oncall_agent.simulator import (
    SCENARIOS,
    build_scorecard,
    render_comparison_markdown,
    render_scorecard_markdown,
    run_all_scenarios,
    score_run,
)
from oncall_agent.simulator.scenarios import get_scenario


def test_score_run_matches_bad_deploy_exactly(tmp_path: Path):
    run = run_all_scenarios([get_scenario("bad-deploy")], audit_log_path=tmp_path / "sim.jsonl")[0]
    score = score_run(run)

    assert score.scenario == "bad-deploy"
    assert score.expected_category == "deploy_regression"
    assert score.actual_category == "deploy_regression"
    assert score.category_match is True
    assert score.expected_action == ActionType.ROLLBACK
    assert score.actual_action == ActionType.ROLLBACK
    assert score.action_match is True
    assert score.acted is True
    assert score.steps > 0


def test_score_run_flags_a_category_miss_but_a_safe_action(tmp_path: Path):
    run = run_all_scenarios([get_scenario("network-partition")], audit_log_path=tmp_path / "sim.jsonl")[0]
    score = score_run(run)

    assert score.expected_category == "network_partition"
    assert score.actual_category == "dependency_failure"
    assert score.category_match is False
    # The scripted policy mislabels the cause here, but still escalates
    # instead of taking a wrong destructive action.
    assert score.expected_action == ActionType.ESCALATE
    assert score.action_match is True


def test_score_run_counts_a_revision(tmp_path: Path):
    run = run_all_scenarios([get_scenario("config-drift")], audit_log_path=tmp_path / "sim.jsonl")[0]
    score = score_run(run)
    assert score.revisions == 1


def test_build_scorecard_covers_every_scenario(tmp_path: Path):
    runs = run_all_scenarios(audit_log_path=tmp_path / "sim.jsonl")
    scorecard = build_scorecard(runs, provider="scripted")

    assert len(scorecard.scores) == len(SCENARIOS)
    assert scorecard.provider == "scripted"


def test_scripted_policy_root_cause_accuracy_matches_the_documented_gap(tmp_path: Path):
    # Phase 5's notes: two scenarios are diagnosed precisely, dependency-outage
    # matches by the generic fallback, the remaining three don't. 3/6 exact.
    runs = run_all_scenarios(audit_log_path=tmp_path / "sim.jsonl")
    scorecard = build_scorecard(runs, provider="scripted")

    assert scorecard.root_cause_accuracy == 0.5
    # Every scenario's proposed action is still the safe one, even where
    # the root-cause category is wrong.
    assert scorecard.action_accuracy == 1.0


def test_scorecard_step_aggregates_are_positive(tmp_path: Path):
    runs = run_all_scenarios(audit_log_path=tmp_path / "sim.jsonl")
    scorecard = build_scorecard(runs)

    assert scorecard.total_steps > 0
    assert scorecard.average_steps > 0
    assert scorecard.total_revisions >= 3  # the three scenarios that revise


def test_render_scorecard_markdown_includes_every_scenario(tmp_path: Path):
    runs = run_all_scenarios(audit_log_path=tmp_path / "sim.jsonl")
    scorecard = build_scorecard(runs, provider="scripted")
    markdown = render_scorecard_markdown(scorecard)

    assert "scripted" in markdown
    for scenario in SCENARIOS:
        assert scenario.name in markdown
    assert "Root-cause accuracy" in markdown


def test_render_comparison_markdown_includes_every_provider(tmp_path: Path):
    runs = run_all_scenarios(audit_log_path=tmp_path / "sim.jsonl")
    scorecard_a = build_scorecard(runs, provider="scripted")
    scorecard_b = build_scorecard(runs, provider="ollama")
    markdown = render_comparison_markdown([scorecard_a, scorecard_b])

    assert "scripted" in markdown
    assert "ollama" in markdown
