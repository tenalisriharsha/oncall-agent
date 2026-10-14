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
    """A candidate explanation for the alert, with supporting evidence."""

    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class Diagnosis(BaseModel):
    """The agent's final conclusion for an incident."""

    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    proposed_fix: str
    requires_approval: bool = True


class EventType(str, Enum):
    """Kinds of entries that can appear in the audit trail."""

    ALERT_RECEIVED = "alert_received"
    HYPOTHESIS_FORMED = "hypothesis_formed"
    TOOL_CALL = "tool_call"
    DIAGNOSIS_REACHED = "diagnosis_reached"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"


class AuditEvent(BaseModel):
    """One immutable, timestamped entry in an incident's audit trail.

    Every step the agent takes is written as one of these so an
    investigation can be reconstructed and reviewed after the fact.
    """

    incident_id: str
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)
