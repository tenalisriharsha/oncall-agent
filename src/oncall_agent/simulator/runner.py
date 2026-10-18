"""Fires a scenario's alert through the real agent loop end to end.

``run_scenario`` deliberately reuses :func:`oncall_agent.response.respond_to_incident`
unchanged: investigate, gate any proposed action on approval, act if
approved. The only thing the simulator adds is where the evidence and the
approval come from — fault-injected tools instead of a live cluster, and
an :class:`~oncall_agent.approval.AutoApprovalGate` instead of a human,
so a whole scenario suite can run unattended.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..actions import ActionRegistry
from ..approval import AutoApprovalGate
from ..audit import AuditTrail
from ..llm.base import LLMProvider
from ..llm.scripted import ScriptedPolicyProvider
from ..models import Alert, AuditEvent, IncidentResponse
from ..response import respond_to_incident
from .faults import inject_fault
from .scenarios import SCENARIOS, Scenario

DEFAULT_SIMULATOR_AUDIT_LOG_PATH = Path(".oncall-agent/simulator.jsonl")


class ScenarioRun(BaseModel):
    """What happened when a scenario was fired: the alert, the agent's
    full response, and the audit trail it left behind (useful input for a
    future scorecard: how many steps, how many revisions, did it act).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    scenario: Scenario
    alert: Alert
    response: IncidentResponse
    events: list[AuditEvent]


def run_scenario(
    scenario: Scenario,
    *,
    provider: LLMProvider | None = None,
    audit_log_path: str | Path | None = None,
) -> ScenarioRun:
    """Investigate and (auto-)act on one scenario's injected fault."""
    alert = Alert(
        title=scenario.title,
        description=scenario.description,
        service=scenario.service,
        severity=scenario.severity,
    )
    tools = inject_fault(scenario.fault_type)
    audit = AuditTrail(audit_log_path or DEFAULT_SIMULATOR_AUDIT_LOG_PATH)

    response = respond_to_incident(
        alert,
        provider or ScriptedPolicyProvider(),
        tools,
        audit,
        AutoApprovalGate(),
        action_registry=ActionRegistry.noop(),
    )
    events = audit.for_incident(alert.id)
    return ScenarioRun(scenario=scenario, alert=alert, response=response, events=events)


def run_all_scenarios(
    scenarios: list[Scenario] | None = None,
    *,
    provider: LLMProvider | None = None,
    audit_log_path: str | Path | None = None,
) -> list[ScenarioRun]:
    """Run every scenario (defaulting to all six) and collect the results."""
    return [
        run_scenario(scenario, provider=provider, audit_log_path=audit_log_path)
        for scenario in (scenarios or SCENARIOS)
    ]
