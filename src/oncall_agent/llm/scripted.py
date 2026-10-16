"""A deterministic, rule-based decision policy.

This is the default provider: it needs no API key, no network access, and
no GPU, and it always produces the same output for the same input. That
makes it the right choice for tests and CI, and a reasonable stand-in for
a real model when demonstrating the agent loop end to end.

The rules encode a small, fixed runbook: check for a recent deploy first
(deploys cause most incidents), form an initial hypothesis, then check
pod health. If pod health doesn't corroborate that hypothesis at all (no
restarts, no OOM), the policy re-plans: it revises its hypothesis toward
a downstream dependency failure instead of diagnosing on a hunch it just
watched get contradicted. Either way it then concludes, attaching every
hypothesis it considered — ranked by confidence — to the diagnosis for
transparency.
"""

from __future__ import annotations

from ..models import Diagnosis, Hypothesis
from ..reasoning import current_hypothesis, rank_hypotheses
from .base import LLMAction, LLMProvider, LLMRequest, LLMResponse

DEPLOY_REGRESSION_WINDOW_MINUTES = 30

CATEGORY_DEPLOY_REGRESSION = "deploy_regression"
CATEGORY_RESOURCE_EXHAUSTION = "resource_exhaustion"
CATEGORY_DEPENDENCY_FAILURE = "dependency_failure"

# Categories formed from deploy history alone, and therefore worth
# re-checking once pod health comes in.
_REVISABLE_CATEGORIES = {CATEGORY_DEPLOY_REGRESSION, CATEGORY_RESOURCE_EXHAUSTION}


def _tool_result(request: LLMRequest, tool_name: str) -> dict | None:
    for record in request.tool_results:
        if record.tool == tool_name:
            return record.result
    return None


def _pod_health_corroborates(pod_result: dict) -> bool:
    """Whether pod status shows *any* sign of trouble at all."""
    return bool(pod_result.get("oom_killed")) or pod_result.get("restarts", 0) > 0


class ScriptedPolicyProvider(LLMProvider):
    """Fixed decision tree: recent deploy? -> pod health? -> diagnose.

    Re-plans once between the pod-health check and the diagnosis if pod
    health flatly contradicts the deploy-based hypothesis.
    """

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

        leading = current_hypothesis(request.hypotheses)
        if (
            len(request.hypotheses) == 1
            and leading is not None
            and leading.category in _REVISABLE_CATEGORIES
            and not _pod_health_corroborates(pod_result)
        ):
            return LLMResponse(
                action=LLMAction.FORM_HYPOTHESIS,
                rationale=(
                    "Pod health shows no restarts or OOM signal, which doesn't "
                    "corroborate the deploy-based hypothesis; revising."
                ),
                hypothesis=self._revise(request, leading, pod_result),
                is_revision=True,
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
                category=CATEGORY_DEPLOY_REGRESSION,
            )
        return Hypothesis(
            statement=(
                f"No recent deploy to {request.alert.service}; the cause is likely "
                "resource exhaustion or a dependency failure."
            ),
            confidence=0.4,
            evidence=["No deploy within the regression window."],
            category=CATEGORY_RESOURCE_EXHAUSTION,
        )

    def _revise(
        self, request: LLMRequest, leading: Hypothesis, pod_result: dict
    ) -> Hypothesis:
        return Hypothesis(
            statement=(
                f"Pod health for {request.alert.service} shows no restarts or OOM "
                f"signal, which doesn't corroborate the earlier hypothesis "
                f"('{leading.statement}'); the cause is more likely a downstream "
                "dependency failure."
            ),
            confidence=0.55,
            evidence=[
                "Deploy history alone did not explain the alert.",
                "Pod status shows 0 restarts and no OOM signal.",
            ],
            category=CATEGORY_DEPENDENCY_FAILURE,
        )

    def _diagnose(
        self, request: LLMRequest, deploy_result: dict, pod_result: dict
    ) -> Diagnosis:
        ranked = rank_hypotheses(request.hypotheses)
        current = current_hypothesis(request.hypotheses)

        if current is not None and current.category == CATEGORY_DEPENDENCY_FAILURE:
            return Diagnosis(
                root_cause=(
                    f"Neither deploy history nor pod health for {request.alert.service} "
                    "points to an internal cause; the evidence now favors a downstream "
                    "dependency failure."
                ),
                confidence=current.confidence,
                evidence=[*current.evidence, "Initial deploy-based hypothesis was revised."],
                proposed_fix=(
                    f"Escalate {request.alert.service} and check downstream "
                    "dependency health and latency."
                ),
                requires_approval=True,
                hypotheses_considered=ranked,
            )

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
                hypotheses_considered=ranked,
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
                hypotheses_considered=ranked,
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
            hypotheses_considered=ranked,
        )
