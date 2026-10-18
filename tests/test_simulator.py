from pathlib import Path

import pytest

from oncall_agent.models import ActionType, EventType
from oncall_agent.simulator import SCENARIOS, FaultType, inject_fault, run_all_scenarios, run_scenario
from oncall_agent.simulator.faults import FAULT_PROFILES
from oncall_agent.simulator.scenarios import get_scenario


def test_every_fault_type_has_a_profile():
    for fault_type in FaultType:
        assert fault_type in FAULT_PROFILES


def test_every_scenario_has_a_distinct_fault_type():
    fault_types = [scenario.fault_type for scenario in SCENARIOS]
    assert len(fault_types) == len(set(fault_types)) == len(FaultType)


def test_inject_fault_wires_fakes_matching_the_profile():
    tools = inject_fault(FaultType.OOM_CRASH_LOOP)
    deploy_result = tools.get("get_recent_deploys").run(service="checkout-service")
    pod_result = tools.get("get_pod_status").run(service="checkout-service")

    assert deploy_result["minutes_since_last_deploy"] == 240
    assert pod_result["oom_killed"] is True


def test_get_scenario_looks_up_by_name():
    scenario = get_scenario("bad-deploy")
    assert scenario.fault_type == FaultType.BAD_DEPLOY


def test_get_scenario_rejects_unknown_name():
    with pytest.raises(KeyError):
        get_scenario("does-not-exist")


def test_run_scenario_bad_deploy_rolls_back(tmp_path: Path):
    scenario = get_scenario("bad-deploy")
    run = run_scenario(scenario, audit_log_path=tmp_path / "sim.jsonl")

    assert run.response.diagnosis.action == ActionType.ROLLBACK
    assert run.response.approval is not None
    assert run.response.action_result is not None
    assert run.response.action_result.success is True
    assert run.alert.service == scenario.service


def test_run_scenario_oom_scales_up(tmp_path: Path):
    scenario = get_scenario("oom-crash-loop")
    run = run_scenario(scenario, audit_log_path=tmp_path / "sim.jsonl")

    assert run.response.diagnosis.action == ActionType.SCALE
    assert run.response.action_result.success is True


def test_run_scenario_dependency_outage_escalates_without_approval(tmp_path: Path):
    scenario = get_scenario("dependency-outage")
    run = run_scenario(scenario, audit_log_path=tmp_path / "sim.jsonl")

    assert run.response.diagnosis.action == ActionType.ESCALATE
    assert run.response.approval is None
    assert run.response.action_result is None


def test_run_scenario_writes_a_full_audit_trail(tmp_path: Path):
    scenario = get_scenario("bad-deploy")
    log_path = tmp_path / "sim.jsonl"
    run = run_scenario(scenario, audit_log_path=log_path)

    event_types = [e.event_type for e in run.events]
    assert EventType.ALERT_RECEIVED in event_types
    assert EventType.DIAGNOSIS_REACHED in event_types
    assert EventType.ACTION_EXECUTED in event_types
    assert log_path.exists()


def test_run_all_scenarios_covers_every_scenario(tmp_path: Path):
    runs = run_all_scenarios(audit_log_path=tmp_path / "sim.jsonl")
    assert [run.scenario.name for run in runs] == [s.name for s in SCENARIOS]
    for run in runs:
        assert run.response.diagnosis is not None


def test_scenarios_with_no_pod_health_signal_all_escalate(tmp_path: Path):
    # dependency-outage, network-partition, and config-drift are
    # mechanically indistinguishable through the two tools the scripted
    # policy reads today, so they all escalate the same way.
    ambiguous = ["dependency-outage", "network-partition", "config-drift"]
    for name in ambiguous:
        run = run_scenario(get_scenario(name), audit_log_path=tmp_path / "sim.jsonl")
        assert run.response.diagnosis.action == ActionType.ESCALATE
