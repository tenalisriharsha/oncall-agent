"""Phase 6: score a scenario suite's results against ground truth.

Phase 5's runner already produces one :class:`~oncall_agent.simulator.runner.ScenarioRun`
per scenario, carrying the full :class:`~oncall_agent.models.IncidentResponse` and
the audit trail it left behind. This module is the comparison layer on top:
pair each run's `Diagnosis.category`/`Diagnosis.action` against its
`Scenario`'s `expected_category`/`expected_action`, reduce the audit trail
to a step count, and aggregate across a suite into a :class:`Scorecard` a
human (or a provider-vs-provider comparison) can read at a glance.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..models import ActionType, EventType
from .runner import ScenarioRun

# Steps taken during an investigation: every tool call plus every hypothesis
# formed or revised. Approval/action events aren't counted — they happen
# after the investigation has already concluded.
STEP_EVENT_TYPES = frozenset(
    {EventType.HYPOTHESIS_FORMED, EventType.HYPOTHESIS_REVISED, EventType.TOOL_CALL}
)


class ScenarioScore(BaseModel):
    """One scenario's outcome compared against its ground truth."""

    scenario: str
    fault_type: str
    expected_category: str
    actual_category: str | None
    category_match: bool
    expected_action: ActionType
    actual_action: ActionType | None
    action_match: bool
    confidence: float
    steps: int
    revisions: int
    acted: bool


def score_run(run: ScenarioRun) -> ScenarioScore:
    """Compare one scenario run's diagnosis against its ground truth."""
    diagnosis = run.response.diagnosis
    steps = sum(1 for event in run.events if event.event_type in STEP_EVENT_TYPES)
    revisions = sum(1 for event in run.events if event.event_type is EventType.HYPOTHESIS_REVISED)
    return ScenarioScore(
        scenario=run.scenario.name,
        fault_type=run.scenario.fault_type.value,
        expected_category=run.scenario.expected_category,
        actual_category=diagnosis.category,
        category_match=diagnosis.category == run.scenario.expected_category,
        expected_action=run.scenario.expected_action,
        actual_action=diagnosis.action,
        action_match=diagnosis.action == run.scenario.expected_action,
        confidence=diagnosis.confidence,
        steps=steps,
        revisions=revisions,
        acted=run.response.action_result is not None,
    )


def _ratio(flags: list[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


class Scorecard(BaseModel):
    """Aggregate scoring for one provider's run across a scenario suite."""

    provider: str
    scores: list[ScenarioScore]

    @property
    def root_cause_accuracy(self) -> float:
        return _ratio([s.category_match for s in self.scores])

    @property
    def action_accuracy(self) -> float:
        return _ratio([s.action_match for s in self.scores])

    @property
    def total_steps(self) -> int:
        return sum(s.steps for s in self.scores)

    @property
    def average_steps(self) -> float:
        return self.total_steps / len(self.scores) if self.scores else 0.0

    @property
    def total_revisions(self) -> int:
        return sum(s.revisions for s in self.scores)


def build_scorecard(runs: list[ScenarioRun], *, provider: str = "scripted") -> Scorecard:
    """Score every run in ``runs`` and aggregate the results."""
    return Scorecard(provider=provider, scores=[score_run(run) for run in runs])


def render_markdown(scorecard: Scorecard) -> str:
    """Render one scorecard as a standalone Markdown document."""
    correct_cause = sum(s.category_match for s in scorecard.scores)
    correct_action = sum(s.action_match for s in scorecard.scores)
    total = len(scorecard.scores)
    lines = [
        f"# Incident simulator scorecard — provider: {scorecard.provider}",
        "",
        f"**Root-cause accuracy:** {scorecard.root_cause_accuracy:.0%} ({correct_cause}/{total})",
        f"**Action accuracy:** {scorecard.action_accuracy:.0%} ({correct_action}/{total})",
        f"**Total steps:** {scorecard.total_steps}  "
        f"**Average steps/scenario:** {scorecard.average_steps:.1f}  "
        f"**Total revisions:** {scorecard.total_revisions}",
        "",
        "| scenario | fault | expected cause | actual cause | expected action | actual action | steps | revisions |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for score in scorecard.scores:
        cause_mark = "match" if score.category_match else "MISS"
        action_mark = "match" if score.action_match else "MISS"
        actual_action = score.actual_action.value if score.actual_action else "(none)"
        lines.append(
            f"| {score.scenario} | {score.fault_type} | {score.expected_category} | "
            f"{score.actual_category or '(none)'} ({cause_mark}) | {score.expected_action.value} | "
            f"{actual_action} ({action_mark}) | {score.steps} | {score.revisions} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_comparison_markdown(scorecards: list[Scorecard]) -> str:
    """Render a side-by-side comparison of multiple providers' scorecards."""
    lines = [
        "# Provider comparison",
        "",
        "| provider | root-cause accuracy | action accuracy | total steps | avg steps/scenario |",
        "|---|---|---|---|---|",
    ]
    for scorecard in scorecards:
        lines.append(
            f"| {scorecard.provider} | {scorecard.root_cause_accuracy:.0%} | "
            f"{scorecard.action_accuracy:.0%} | {scorecard.total_steps} | "
            f"{scorecard.average_steps:.1f} |"
        )
    lines.append("")
    return "\n".join(lines)
