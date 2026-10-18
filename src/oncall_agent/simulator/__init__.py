"""The incident simulator: fault injection, scenario definitions, and a runner.

Phase 5 adds a layer *next to* the agent loop, not inside it: a scenario
fires an :class:`~oncall_agent.models.Alert` against fault-injected tool
evidence and lets :func:`oncall_agent.response.respond_to_incident`
investigate and act on it exactly as it would for a real incident. Nothing
in ``investigation.py``, ``response.py``, or the scripted policy needed to
change for this to exist.
"""

from __future__ import annotations

from .faults import FaultType, inject_fault
from .runner import ScenarioRun, run_all_scenarios, run_scenario
from .scenarios import SCENARIOS, Scenario, get_scenario

__all__ = [
    "FaultType",
    "inject_fault",
    "SCENARIOS",
    "Scenario",
    "get_scenario",
    "ScenarioRun",
    "run_scenario",
    "run_all_scenarios",
]
