from oncall_agent.models import Hypothesis
from oncall_agent.reasoning import current_hypothesis, rank_hypotheses


def test_rank_hypotheses_sorts_by_confidence_descending():
    low = Hypothesis(statement="low", confidence=0.3)
    high = Hypothesis(statement="high", confidence=0.9)
    mid = Hypothesis(statement="mid", confidence=0.5)

    ranked = rank_hypotheses([low, high, mid])

    assert ranked == [high, mid, low]


def test_rank_hypotheses_keeps_chronological_order_on_ties():
    first = Hypothesis(statement="first", confidence=0.5)
    second = Hypothesis(statement="second", confidence=0.5)

    ranked = rank_hypotheses([first, second])

    assert ranked == [first, second]


def test_rank_hypotheses_empty_list():
    assert rank_hypotheses([]) == []


def test_current_hypothesis_is_the_most_recent_not_the_highest_confidence():
    first = Hypothesis(statement="first", confidence=0.9)
    revised = Hypothesis(statement="revised", confidence=0.4)

    assert current_hypothesis([first, revised]) == revised


def test_current_hypothesis_of_empty_list_is_none():
    assert current_hypothesis([]) is None
