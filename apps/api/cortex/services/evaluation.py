"""Absolute and regression quality gates used before immutable pipeline promotion."""

from __future__ import annotations

from dataclasses import dataclass

from cortex.errors import InputValidationError


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    """Record the mandatory quality and isolation metrics for one evaluation run."""

    scopeLeakCount: int
    recallAt10: float
    citationPrecision: float
    citationCompleteness: float
    unsupportedClaimRate: float
    abstentionRecall: float


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Explain whether a pipeline may proceed to administrator approval."""

    isEligible: bool
    failedGates: tuple[str, ...]


def evaluatePromotion(metrics: EvaluationMetrics) -> PromotionDecision:
    """Apply the first-release absolute gates without allowing metric averaging to hide leaks."""
    metricValues = (
        metrics.recallAt10,
        metrics.citationPrecision,
        metrics.citationCompleteness,
        metrics.unsupportedClaimRate,
        metrics.abstentionRecall,
    )
    if metrics.scopeLeakCount < 0 or any(value < 0 or value > 1 for value in metricValues):
        raise InputValidationError("evaluation metrics must use valid counts and 0-1 rates")
    failedGates: list[str] = []
    if metrics.scopeLeakCount != 0:
        failedGates.append("scope-isolation")
    if metrics.recallAt10 < 0.90:
        failedGates.append("recall-at-10")
    if metrics.citationPrecision < 0.98:
        failedGates.append("citation-precision")
    if metrics.citationCompleteness < 0.95:
        failedGates.append("citation-completeness")
    if metrics.unsupportedClaimRate > 0.01:
        failedGates.append("unsupported-claim-rate")
    if metrics.abstentionRecall < 0.95:
        failedGates.append("abstention-recall")
    return PromotionDecision(isEligible=not failedGates, failedGates=tuple(failedGates))
