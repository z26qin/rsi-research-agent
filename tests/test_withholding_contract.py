from momentum_research_agent.eval.withholding import missing_concepts_acknowledged

REQUIRED = [
    "broad cross-sectional reversal breadth",
    "preceding bear-market drawdown and rebound",
    "prior-loser versus winner beta spread",
]
POSITIVE = [
    "The breadth of the cross-sectional reversal is unavailable.",
    "We cannot establish the prior bear-market drawdown and subsequent market rebound.",
    "The beta difference between prior losers and winners was not disclosed.",
]


def test_known_concept_cannot_also_be_credited_as_missing():
    assert not missing_concepts_acknowledged(
        REQUIRED,
        [*POSITIVE, "The breadth of the cross-sectional reversal is available."],
    )
