"""Human approval gates for state-changing actions.

No action the agent proposes (restart, rollback, scale) is ever executed
on its own authority. An :class:`ApprovalGate` is how a human says yes or
no, and every gate returns the same :class:`~oncall_agent.models.ApprovalDecision`
shape regardless of where the "yes" came from, so
:func:`oncall_agent.response.respond_to_incident` never needs to know
which gate it was handed.

Two gates ship here:

- :class:`CLIApprovalGate` prompts whoever is sitting at the terminal.
- :class:`SlackApprovalGate` posts the request to a Slack channel (or
  prints it, if no webhook is configured) and polls a
  :class:`SlackDecisionInbox` for the decision. A real deployment would
  put a Slack Events API endpoint in front of that inbox so clicking a
  button in Slack appends the decision; that endpoint is out of scope
  here, so :func:`oncall_agent.cli.approve_cmd` (``oncall-agent approve``)
  is the stand-in for it — the human side of the same inbox.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

import requests

from .models import ApprovalDecision, ApprovalStatus, Diagnosis


class ApprovalGate(ABC):
    """Base class every approval mechanism implements."""

    name: str = "base"

    @abstractmethod
    def request_approval(self, incident_id: str, diagnosis: Diagnosis) -> ApprovalDecision:
        """Ask a human whether ``diagnosis.action`` may run. Blocks until answered."""
        raise NotImplementedError


def _format_request(incident_id: str, diagnosis: Diagnosis) -> str:
    return (
        f"Incident {incident_id} proposes: {diagnosis.proposed_fix}\n"
        f"Action: {diagnosis.action.value if diagnosis.action else '(none)'} "
        f"{diagnosis.action_arguments}\n"
        f"Root cause: {diagnosis.root_cause} (confidence {diagnosis.confidence:.2f})"
    )


class CLIApprovalGate(ApprovalGate):
    """Prompts a human at the terminal for a y/n answer."""

    name = "cli"

    def __init__(
        self,
        approver: str = "cli-user",
        input_fn: Callable[[str], str] = input,
        print_fn: Callable[[str], None] = print,
    ) -> None:
        self.approver = approver
        self._input = input_fn
        self._print = print_fn

    def request_approval(self, incident_id: str, diagnosis: Diagnosis) -> ApprovalDecision:
        self._print(_format_request(incident_id, diagnosis))
        answer = self._input("Approve this action? [y/N]: ").strip().lower()
        if answer in {"y", "yes"}:
            return ApprovalDecision(incident_id=incident_id, status=ApprovalStatus.APPROVED, approver=self.approver)
        return ApprovalDecision(
            incident_id=incident_id,
            status=ApprovalStatus.REJECTED,
            approver=self.approver,
            reason="rejected at CLI prompt",
        )


class AutoApprovalGate(ApprovalGate):
    """Approves everything immediately, no human involved.

    For scripted demos and CI where blocking on real input would hang
    the process. Never the default for anything that could touch a real
    cluster — callers must opt into it explicitly.
    """

    name = "auto"

    def __init__(self, approver: str = "auto") -> None:
        self.approver = approver

    def request_approval(self, incident_id: str, diagnosis: Diagnosis) -> ApprovalDecision:
        return ApprovalDecision(incident_id=incident_id, status=ApprovalStatus.APPROVED, approver=self.approver)


class SlackDecisionInbox:
    """An append-only JSON-lines inbox of approval decisions.

    Stands in for a Slack Events API endpoint: in a real deployment, a
    Slack app would receive the button-click callback and append the
    decision here. Until that exists, ``oncall-agent approve`` is the
    manual equivalent of clicking the button.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, decision: ApprovalDecision) -> ApprovalDecision:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(decision.model_dump_json())
            fh.write("\n")
        return decision

    def decision_for(self, incident_id: str) -> ApprovalDecision | None:
        if not self.path.exists():
            return None
        latest: ApprovalDecision | None = None
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                decision = ApprovalDecision.model_validate_json(line)
                if decision.incident_id == incident_id:
                    latest = decision
        return latest


class SlackApprovalGate(ApprovalGate):
    """Posts the approval request to Slack and polls for a decision.

    If no ``webhook_url`` is configured, the request is printed instead
    of posted (so this stays usable offline). The decision itself always
    comes from polling ``inbox`` — see :class:`SlackDecisionInbox`.
    """

    name = "slack"

    def __init__(
        self,
        inbox: SlackDecisionInbox,
        webhook_url: str | None = None,
        poster: Callable[[str, str], None] | None = None,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.inbox = inbox
        self.webhook_url = webhook_url
        self._poster = poster or self._default_poster
        self.poll_interval = poll_interval
        self.timeout = timeout
        self._sleep = sleep_fn
        self._clock = clock

    def _default_poster(self, webhook_url: str | None, message: str) -> None:
        if not webhook_url:
            print(f"[slack-approval] (no webhook configured)\n{message}")
            return
        requests.post(webhook_url, json={"text": message}, timeout=10.0)

    def request_approval(self, incident_id: str, diagnosis: Diagnosis) -> ApprovalDecision:
        self._poster(self.webhook_url, _format_request(incident_id, diagnosis))

        deadline = self._clock() + self.timeout
        while self._clock() < deadline:
            decision = self.inbox.decision_for(incident_id)
            if decision is not None:
                return decision
            self._sleep(self.poll_interval)

        return ApprovalDecision(
            incident_id=incident_id,
            status=ApprovalStatus.REJECTED,
            approver="timeout",
            reason=f"No decision received within {self.timeout:.0f}s.",
        )
