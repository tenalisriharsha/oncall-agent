"""Core domain models shared by every layer of the agent.

These are the nouns the rest of the system passes around: the alert that
kicks off an investigation, the tool calls made while investigating, the
hypotheses formed along the way, and the final diagnosis handed back to a
human.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Severity(str, Enum):
    """How urgently an alert needs attention."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Alert(BaseModel):
    """An incoming page: the trigger for an investigation."""

    id: str = Field(default_factory=lambda: f"alert-{uuid.uuid4().hex[:8]}")
    title: str
    description: str
    service: str
    severity: Severity = Severity.MEDIUM
    labels: dict[str, str] = Field(default_factory=dict)
    fired_at: datetime = Field(default_factory=_utcnow)


class ToolCallRecord(BaseModel):
    """A single read-only (or, once approved, state-changing) tool
    invocation made during an investigation, and what came back.
    """

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    is_mutating: bool = False
    requested_at: datetime = Field(default_factory=_utcnow)


class Hypothesis(BaseModel):
    """A candidate explanation for the alert, with supporting evidence.

    ``category`` is an optional machine-readable tag (e.g.
    ``"deploy_regression"``) a reasoning policy can attach so later steps
    can recognize and compare hypotheses without re-parsing ``statement``
    text. It is ``None`` for hypotheses that don't come from a policy that
    tags them.
    """

    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    category: str | None = None


class ActionType(str, Enum):
    """The fixed menu of state-changing actions the agent can propose.

    ``ESCALATE`` is the odd one out: it never mutates anything (it just
    hands the incident to a human), so it is the one action type that
    never needs to go through an :class:`~oncall_agent.approval.ApprovalGate`.
    """

    RESTART = "restart"
    ROLLBACK = "rollback"
    SCALE = "scale"
    ESCALATE = "escalate"


class Diagnosis(BaseModel):
    """The agent's final conclusion for an incident."""

    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    proposed_fix: str
    requires_approval: bool = True
    # The category of the hypothesis this diagnosis actually concluded from,
    # mirroring Hypothesis.category so a scorecard can compare root-cause
    # accuracy without re-parsing `root_cause` text. `None` for diagnoses a
    # policy didn't tag (e.g. a raw LLMProvider response that skips it).
    category: str | None = None
    hypotheses_considered: list[Hypothesis] = Field(default_factory=list)
    # The machine-actionable shape of `proposed_fix`, if one exists. `None`
    # means the fix has no automated executor (e.g. a vague escalation) and
    # must remain a human-only follow-up.
    action: ActionType | None = None
    action_arguments: dict[str, Any] = Field(default_factory=dict)


class ApprovalStatus(str, Enum):
    """The outcome of asking a human whether a proposed action may run."""

    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalDecision(BaseModel):
    """A human's answer to an approval request for one incident's action."""

    incident_id: str
    status: ApprovalStatus
    approver: str
    reason: str = ""
    decided_at: datetime = Field(default_factory=_utcnow)


class ActionResult(BaseModel):
    """What happened when an approved action was actually executed."""

    incident_id: str
    action: ActionType
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool
    output: str = ""
    executed_at: datetime = Field(default_factory=_utcnow)


class IncidentResponse(BaseModel):
    """The full outcome of responding to one incident: diagnose, maybe
    get approval, maybe act.

    ``approval``/``action_result`` are ``None`` when the diagnosis never
    reached that stage (e.g. no actionable fix, or approval was never
    granted).
    """

    diagnosis: Diagnosis
    approval: ApprovalDecision | None = None
    action_result: ActionResult | None = None


class EventType(str, Enum):
    """Kinds of entries that can appear in the audit trail."""

    ALERT_RECEIVED = "alert_received"
    HYPOTHESIS_FORMED = "hypothesis_formed"
    HYPOTHESIS_REVISED = "hypothesis_revised"
    TOOL_CALL = "tool_call"
    DIAGNOSIS_REACHED = "diagnosis_reached"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    ACTION_EXECUTED = "action_executed"


class AuditEvent(BaseModel):
    """One immutable, timestamped entry in an incident's audit trail.

    Every step the agent takes is written as one of these so an
    investigation can be reconstructed and reviewed after the fact.
    """

    incident_id: str
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)
