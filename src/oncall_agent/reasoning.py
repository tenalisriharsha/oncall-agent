"""Multi-hypothesis ranking and comparison.

An investigation can form more than one :class:`Hypothesis` as evidence
comes in — an initial guess, then a revision once a tool result
contradicts it. These helpers give every caller (a policy deciding what
to do next, a diagnosis report, the CLI) one consistent way to look at
that list: which one is the standing belief right now, and how do all of
them compare.
"""

from __future__ import annotations

from .models import Hypothesis


def rank_hypotheses(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """Return hypotheses sorted by confidence, highest first.

    Ties keep their original (chronological) order. This ranking is for
    comparison and reporting; it is not necessarily the "current belief"
    — see :func:`current_hypothesis` for that.
    """
    return sorted(hypotheses, key=lambda h: h.confidence, reverse=True)


def current_hypothesis(hypotheses: list[Hypothesis]) -> Hypothesis | None:
    """Return the standing belief: the most recently formed hypothesis.

    A later hypothesis is assumed to supersede earlier ones (e.g. a
    revision prompted by contradicting evidence), regardless of whether
    its confidence is higher or lower than what came before.
    """
    return hypotheses[-1] if hypotheses else None
