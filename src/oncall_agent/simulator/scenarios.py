"""The six incident scenarios the simulator fires, one per runbook.

Each :class:`Scenario` pairs an :class:`~oncall_agent.models.Alert` with
the :class:`~oncall_agent.simulator.faults.FaultType` that caused it, plus
the runbook a human on-call engineer would reach for and a short note on
what to expect from the scripted policy today — some of these faults are
diagnosed precisely, and some are only diagnosed as a safe fallback (see
``faults.py`` for why).
"""

from __future__ import annotations

from pydantic import BaseModel

from ..models import Severity
from .faults import FaultType


class Scenario(BaseModel):
    """One incident the simulator can fire: an alert plus its true cause."""

    name: str
    fault_type: FaultType
    title: str
    description: str
    service: str
    severity: Severity
    runbook: str
    notes: str


SCENARIOS: list[Scenario] = [
    Scenario(
        name="bad-deploy",
        fault_type=FaultType.BAD_DEPLOY,
        title="High error rate on checkout-service",
        description="5xx rate on checkout-service exceeded 5% for 5 minutes, shortly after a deploy.",
        service="checkout-service",
        severity=Severity.HIGH,
        runbook="deploy-regression.md",
        notes="Deploy inside the regression window plus restarts: diagnosed precisely as a deploy regression, action ROLLBACK.",
    ),
    Scenario(
        name="oom-crash-loop",
        fault_type=FaultType.OOM_CRASH_LOOP,
        title="checkout-service pods crash-looping",
        description="checkout-service pods are restarting repeatedly and being OOMKilled.",
        service="checkout-service",
        severity=Severity.CRITICAL,
        runbook="oom-crash-loop.md",
        notes="No recent deploy, oom_killed=true: diagnosed precisely as resource exhaustion, action SCALE.",
    ),
    Scenario(
        name="dependency-outage",
        fault_type=FaultType.DEPENDENCY_OUTAGE,
        title="Elevated error rate on checkout-service",
        description="checkout-service error rate is elevated with no obvious internal cause.",
        service="checkout-service",
        severity=Severity.HIGH,
        runbook="dependency-outage.md",
        notes="No deploy, healthy pods: the scripted policy revises and escalates as a dependency failure, which matches the true cause here.",
    ),
    Scenario(
        name="network-partition",
        fault_type=FaultType.NETWORK_PARTITION,
        title="Requests from checkout-service to payments-service timing out",
        description="checkout-service reports timeouts calling payments-service; both services show healthy pods.",
        service="checkout-service",
        severity=Severity.HIGH,
        runbook="network-partition.md",
        notes=(
            "Same no-deploy/healthy-pod signal as a dependency outage, so the scripted "
            "policy escalates it as one too. The true cause is a network partition; the "
            "policy has no dedicated signal to tell the two apart yet."
        ),
    ),
    Scenario(
        name="disk-pressure",
        fault_type=FaultType.DISK_PRESSURE,
        title="checkout-service pods repeatedly rescheduled",
        description="checkout-service pods are being evicted and recreated on other nodes.",
        service="checkout-service",
        severity=Severity.HIGH,
        runbook="disk-pressure.md",
        notes=(
            "Restarts without an OOM signal don't match any category the scripted policy "
            "recognizes, so it falls through to a generic escalation. The true cause is "
            "node disk pressure, not a dependency failure."
        ),
    ),
    Scenario(
        name="config-drift",
        fault_type=FaultType.CONFIG_DRIFT,
        title="checkout-service behaving inconsistently across replicas",
        description="checkout-service replicas are returning different results for the same request.",
        service="checkout-service",
        severity=Severity.MEDIUM,
        runbook="config-drift.md",
        notes=(
            "No deploy, no pod health signal at all: the scripted policy escalates as a "
            "dependency failure. The true cause is configuration drift, which this tool "
            "surface can't see directly yet."
        ),
    ),
]

_BY_NAME: dict[str, Scenario] = {scenario.name: scenario for scenario in SCENARIOS}

SCENARIO_NAMES: list[str] = sorted(_BY_NAME)


def get_scenario(name: str) -> Scenario:
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        known = ", ".join(SCENARIO_NAMES)
        raise KeyError(f"Unknown scenario '{name}'. Known scenarios: {known}") from exc
