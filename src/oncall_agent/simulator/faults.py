"""Fault injection: canned, deterministic ground truth for each scenario.

A real chaos tool (chaos-kit and friends) injects faults into a live
cluster and lets you observe the fallout. That needs a cluster, is
non-deterministic, and is a poor fit for a test suite or CI that must
run with no network access. Since Phase 1 the agent loop has already
been exercised end to end against :mod:`oncall_agent.tools.fakes` —
tool doubles that return canned evidence shaped exactly like the real
Prometheus/kubectl clients' output. Fault injection here is the same
idea at one remove: each :class:`FaultType` maps to a :class:`FaultProfile`
of canned evidence, and :func:`inject_fault` wires that evidence into a
fresh :class:`~oncall_agent.tools.base.ToolRegistry` the agent loop reads
from exactly as it would read from a live cluster.

Six fault types are injected, one per runbook in ``runbooks/``. The
scripted policy (``llm/scripted.py``) only ever inspects two tools —
``get_recent_deploys`` and ``get_pod_status`` — so that is the full
surface a fault can affect today. Three of the six faults
(``DEPENDENCY_OUTAGE``, ``NETWORK_PARTITION``, ``CONFIG_DRIFT``) are
genuinely indistinguishable through that surface alone: a dependency
outage, a network partition, and a config drift incident all show no
recent deploy and a healthy-looking pod, so the scripted policy reaches
the same ``ESCALATE`` conclusion for all three. That is a real,
intentional limitation surfaced here on purpose — see ``PROGRESS.md``
for what it would take to give the policy a dedicated signal for each.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from ..tools.base import ToolRegistry
from ..tools.fakes import FakePodStatusTool, FakeRecentDeploysTool


class FaultType(str, Enum):
    """One injectable fault per runbook in ``runbooks/``."""

    BAD_DEPLOY = "bad_deploy"
    OOM_CRASH_LOOP = "oom_crash_loop"
    DEPENDENCY_OUTAGE = "dependency_outage"
    NETWORK_PARTITION = "network_partition"
    DISK_PRESSURE = "disk_pressure"
    CONFIG_DRIFT = "config_drift"


class FaultProfile(BaseModel):
    """The canned ground-truth evidence a fault makes the fake tools return."""

    minutes_since_last_deploy: int
    deploy_version: str
    deploy_previous_version: str
    pod_restarts: int
    oom_killed: bool


DEPLOY_REGRESSION_WINDOW_MINUTES = 30

FAULT_PROFILES: dict[FaultType, FaultProfile] = {
    FaultType.BAD_DEPLOY: FaultProfile(
        minutes_since_last_deploy=8,
        deploy_version="v3.1.0",
        deploy_previous_version="v3.0.9",
        pod_restarts=6,
        oom_killed=False,
    ),
    FaultType.OOM_CRASH_LOOP: FaultProfile(
        minutes_since_last_deploy=240,
        deploy_version="v3.0.5",
        deploy_previous_version="v3.0.4",
        pod_restarts=14,
        oom_killed=True,
    ),
    FaultType.DEPENDENCY_OUTAGE: FaultProfile(
        minutes_since_last_deploy=300,
        deploy_version="v3.0.5",
        deploy_previous_version="v3.0.4",
        pod_restarts=0,
        oom_killed=False,
    ),
    FaultType.NETWORK_PARTITION: FaultProfile(
        minutes_since_last_deploy=400,
        deploy_version="v2.9.8",
        deploy_previous_version="v2.9.7",
        pod_restarts=0,
        oom_killed=False,
    ),
    FaultType.DISK_PRESSURE: FaultProfile(
        minutes_since_last_deploy=500,
        deploy_version="v2.9.8",
        deploy_previous_version="v2.9.7",
        pod_restarts=3,
        oom_killed=False,
    ),
    FaultType.CONFIG_DRIFT: FaultProfile(
        minutes_since_last_deploy=600,
        deploy_version="v2.9.8",
        deploy_previous_version="v2.9.7",
        pod_restarts=0,
        oom_killed=False,
    ),
}


def inject_fault(fault_type: FaultType) -> ToolRegistry:
    """Build a :class:`ToolRegistry` whose tools return ``fault_type``'s evidence.

    This is the fault-injection step: it stands in for actually breaking
    a live cluster, by making the same two tools the agent loop already
    calls in every other phase return the evidence that fault *would*
    produce.
    """
    profile = FAULT_PROFILES[fault_type]
    tools = ToolRegistry()
    tools.register(
        FakeRecentDeploysTool(
            minutes_since_last_deploy=profile.minutes_since_last_deploy,
            version=profile.deploy_version,
            previous_version=profile.deploy_previous_version,
        )
    )
    tools.register(FakePodStatusTool(restarts=profile.pod_restarts, oom_killed=profile.oom_killed))
    return tools
