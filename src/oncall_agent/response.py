"""Wraps the investigation loop with the human approval gate.

``run_investigation`` (``investigation.py``) stays exactly what it has
been since Phase 1: alert in, diagnosis out, no notion of approval or
action execution. :func:`respond_to_incident` is the layer on top that
a real on-call flow (and the CLI) actually wants: investigate, and if
the diagnosis proposes a mutating action, ask a human before any of it
runs, and act only once they say yes.
"""

from __future__ import annotations

from .actions import ActionRegistry, execute_action
from .approval import ApprovalGate
from .audit import AuditTrail
from .investigation import DEFAULT_MAX_STEPS, run_investigation
from .llm.base import LLMProvider
from .models import ActionType, Alert, ApprovalStatus, AuditEvent, EventType, IncidentResponse
from .tools.base import ToolRegistry


def respond_to_incident(
    alert: Alert,
    provider: LLMProvider,
    tools: ToolRegistry,
    audit: AuditTrail,
    approval_gate: ApprovalGate,
    action_registry: ActionRegistry | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> IncidentResponse:
    """Investigate ``alert``, then gate any proposed action on human approval.

    Returns as soon as there's nothing further to do: immediately after
    diagnosis if the fix isn't actionable (``action`` is ``None`` or
    ``ESCALATE``), after the approval decision if it was rejected or no
    ``action_registry`` was given, or after the action runs otherwise.
    """
    diagnosis = run_investigation(alert, provider, tools, audit, max_steps=max_steps)

    if diagnosis.action is None or diagnosis.action == ActionType.ESCALATE:
        return IncidentResponse(diagnosis=diagnosis)

    audit.log(
        AuditEvent(
            incident_id=alert.id,
            event_type=EventType.APPROVAL_REQUESTED,
            payload={
                "action": diagnosis.action.value,
                "action_arguments": diagnosis.action_arguments,
                "proposed_fix": diagnosis.proposed_fix,
            },
        )
    )
    decision = approval_gate.request_approval(alert.id, diagnosis)
    audit.log(
        AuditEvent(
            incident_id=alert.id,
            event_type=EventType.APPROVAL_DECIDED,
            payload=decision.model_dump(mode="json"),
        )
    )

    if decision.status != ApprovalStatus.APPROVED or action_registry is None:
        return IncidentResponse(diagnosis=diagnosis, approval=decision)

    action_result = execute_action(
        alert.id, diagnosis.action, diagnosis.action_arguments, decision, action_registry, audit
    )
    return IncidentResponse(diagnosis=diagnosis, approval=decision, action_result=action_result)
