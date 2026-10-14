"""The minimal loop that turns an alert into a diagnosis.

Each iteration asks the active :class:`LLMProvider` what to do next, given
everything gathered so far, and acts on that decision: call a tool, record
a hypothesis, or conclude. Every step is written to the audit trail before
moving on, so a stalled or runaway investigation is always inspectable.

Later phases extend this loop (real tool integrations, re-planning from
new evidence, an approval gate before anything mutating runs) without
changing its shape.
"""

from __future__ import annotations

from .audit import AuditTrail
from .llm.base import LLMAction, LLMProvider, LLMRequest
from .models import Alert, AuditEvent, Diagnosis, EventType, Hypothesis, ToolCallRecord
from .tools.base import ToolRegistry

DEFAULT_MAX_STEPS = 10


class InvestigationError(RuntimeError):
    """Raised when an investigation fails to converge on a diagnosis."""


def run_investigation(
    alert: Alert,
    provider: LLMProvider,
    tools: ToolRegistry,
    audit: AuditTrail,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> Diagnosis:
    """Drive the investigate -> hypothesize -> diagnose loop to completion."""
    audit.log(
        AuditEvent(
            incident_id=alert.id,
            event_type=EventType.ALERT_RECEIVED,
            payload=alert.model_dump(mode="json"),
        )
    )

    tool_results: list[ToolCallRecord] = []
    hypotheses: list[Hypothesis] = []

    for _ in range(max_steps):
        request = LLMRequest(
            alert=alert,
            tool_results=tool_results,
            hypotheses=hypotheses,
            available_tools=tools.names(),
        )
        response = provider.decide(request)

        if response.action == LLMAction.CALL_TOOL:
            tool = tools.get(response.tool_name)
            result = tool.run(**response.tool_arguments)
            record = ToolCallRecord(
                tool=tool.name,
                arguments=response.tool_arguments,
                result=result,
                is_mutating=not tool.read_only,
            )
            tool_results.append(record)
            audit.log(
                AuditEvent(
                    incident_id=alert.id,
                    event_type=EventType.TOOL_CALL,
                    payload=record.model_dump(mode="json"),
                )
            )
        elif response.action == LLMAction.FORM_HYPOTHESIS:
            assert response.hypothesis is not None
            hypotheses.append(response.hypothesis)
            audit.log(
                AuditEvent(
                    incident_id=alert.id,
                    event_type=EventType.HYPOTHESIS_FORMED,
                    payload=response.hypothesis.model_dump(mode="json"),
                )
            )
        elif response.action == LLMAction.DIAGNOSE:
            assert response.diagnosis is not None
            audit.log(
                AuditEvent(
                    incident_id=alert.id,
                    event_type=EventType.DIAGNOSIS_REACHED,
                    payload=response.diagnosis.model_dump(mode="json"),
                )
            )
            return response.diagnosis

    raise InvestigationError(
        f"Investigation of {alert.id} did not converge within {max_steps} steps."
    )
