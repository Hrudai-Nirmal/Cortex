"""Verify absolute promotion gates fail closed on security and quality regressions."""

from cortex.services.evaluation import EvaluationMetrics, evaluatePromotion


def testPromotionPassesAllAbsoluteGates() -> None:
    """A qualifying evaluation proceeds to manual administrator approval."""
    decision = evaluatePromotion(
        EvaluationMetrics(
            scopeLeakCount=0,
            recallAt10=0.93,
            citationPrecision=0.99,
            citationCompleteness=0.97,
            unsupportedClaimRate=0.005,
            abstentionRecall=0.96,
        )
    )

    assert decision.isEligible is True
    assert decision.failedGates == ()


def testAnyScopeLeakBlocksPromotion() -> None:
    """Strong average scores can never compensate for an authorization leak."""
    decision = evaluatePromotion(
        EvaluationMetrics(
            scopeLeakCount=1,
            recallAt10=1.0,
            citationPrecision=1.0,
            citationCompleteness=1.0,
            unsupportedClaimRate=0.0,
            abstentionRecall=1.0,
        )
    )

    assert decision.isEligible is False
    assert "scope-isolation" in decision.failedGates
