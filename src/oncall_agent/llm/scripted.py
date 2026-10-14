"""A deterministic, rule-based decision policy.

This is the default provider: it needs no API key, no network access, and
no GPU, and it always produces the same output for the same input. That
makes it the right choice for tests and CI, and a reasonable stand-in for
a real model when demonstrating the agent loop end to end.

The rules encode a small, fixed runbook: check for a recent deploy first
(deploys cause most incidents), then check pod health, then conclude.
"""

from __future__ import annotations

from ..models import Diagnosis, Hypothesis
from .base import LLMAction, LLMProvider, LLMRequest, LLMResponse

DEPLOY_REGRESSION_WINDOW_MINUTES = 30


def _tool_result(request: LLMRequest, tool_name: str) -> dict | None:
    for record in request.tool_results:
        if record.tool == tool_name:
            return record.result
    return None


class ScriptedPolicyProvider(LLMProvider):
    """Fixed decision tree: recent deploy? -> pod health? -> diagnose."""

    name = "scripted"

    def decide(self, request: LLMRequest) -> LLMResponse:
        deploy_result = _tool_result(request, "get_recent_deploys")
        pod_result = _tool_result(request, "get_pod_status")

        if deploy_result is None:
            return LLMResponse(
                action=LLMAction.CALL_TOOL,
                rationale="Check for a recent deploy before anything else.",
                tool_name="get_recent_deploys",
                tool_arguments={"service": request.alert.service},
            )

        if not request.hypotheses:
            return LLMResponse(
                action=LLMAction.FORM_HYPOTHESIS,
                rationale="Weigh the deploy history before gathering more evidence.",
                hypothesis=self._hypothesize_from_deploy(request, deploy_result),
            )

        if pod_result is None:
            return LLMResponse(
                action=LLMAction.CALL_TOOL,
                rationale="Corroborate with current pod health before concluding.",
                tool_name="get_pod_status",
                tool_arguments={"service": request.alert.service},
            )

        return LLMResponse(
            action=LLMAction.DIAGNOSE,
            rationale="Deploy history and pod health both gathered; ready to conclude.",
            diagnosis=self._diagnose(request, deploy_result, pod_result),
        )

    def _hypothesize_from_deploy(self, request: LLMRequest, deploy_result: dict) -> Hypothesis:
        minutes = deploy_result.get("minutes_since_last_deploy")
        if minutes is not None and minutes <= DEPLOY_REGRESSION_WINDOW_MINUTES:
            version = deploy_result.get("version", "unknown")
            return Hypothesis(
                statement=(
                    f"A deploy of {request.alert.service} to version {version}, "
                    f"{minutes} minutes ago, introduced a regression."
                ),
                confidence=0.75,
                evidence=[f"Deploy {minutes} minutes before the alert fired."],
            )
        return Hypothesis(
            statement=(
                f"No recent deploy to {request.alert.service}; the cause is likely "
                "resource exhaustion or a dependency failure."
            ),
            confidence=0.4,
            evidence=["No deploy within the regression window."],
        )

    def _diagnose(
        self, request: LLMRequest, deploy_result: dict, pod_result: dict
    ) -> Diagnosis:
        minutes = deploy_result.get("minutes_since_last_deploy")
        if minutes is not None and minutes <= DEPLOY_REGRESSION_WINDOW_MINUTES:
            version = deploy_result.get("version", "unknown")
            previous_version = deploy_result.get("previous_version", "the prior release")
            return Diagnosis(
                root_cause=(
                    f"Regression introduced by deploying {request.alert.service} "
                    f"to version {version} {minutes} minutes before the alert."
                ),
                confidence=0.8,
                evidence=[
                    f"Deploy {minutes} minutes before the alert fired.",
                    f"{pod_result.get('restarts', 0)} pod restart(s) observed since.",
                ],
                proposed_fix=f"Roll back {request.alert.service} to {previous_version}.",
                requires_approval=True,
            )

        if pod_result.get("oom_killed"):
            return Diagnosis(
                root_cause=(
                    f"{request.alert.service} pods are being OOMKilled under current load."
                ),
                confidence=0.7,
                evidence=["No recent deploy.", "Pod status reports OOMKilled."],
                proposed_fix=(
                    f"Increase memory limits and scale up {request.alert.service} replicas."
                ),
                requires_approval=True,
            )

        return Diagnosis(
            root_cause=(
                f"No deploy or OOM signal found for {request.alert.service}; likely "
                "a downstream dependency failure."
            ),
            confidence=0.35,
            evidence=["No recent deploy.", "No OOM signal in pod status."],
            proposed_fix=f"Escalate {request.alert.service} to a human on-call engineer.",
            requires_approval=True,
        )
