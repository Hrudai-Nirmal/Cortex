"""Allowlisted, side-effect-free computation functions for deterministic routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from statistics import mean
from typing import Any

from cortex.errors import InputValidationError

ComputeFunction = Callable[[dict[str, Any]], float | int]


@dataclass(frozen=True, slots=True)
class ComputeResult:
    """Return a deterministic value and the named function that produced it."""

    functionName: str
    value: float | int
    inputs: dict[str, Any]


def calculateSum(inputs: dict[str, Any]) -> float:
    """Sum a non-empty list of finite numeric values."""
    values = inputs.get("values")
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, int | float) for value in values)
    ):
        raise InputValidationError("sum requires a non-empty numeric values list")
    return float(sum(values))


def calculateMean(inputs: dict[str, Any]) -> float:
    """Calculate the arithmetic mean of finite numeric values."""
    values = inputs.get("values")
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, int | float) for value in values)
    ):
        raise InputValidationError("mean requires a non-empty numeric values list")
    return float(mean(values))


def calculateDateDifference(inputs: dict[str, Any]) -> int:
    """Calculate whole days between two ISO-8601 dates."""
    startDateValue = inputs.get("startDate")
    endDateValue = inputs.get("endDate")
    if not isinstance(startDateValue, str) or not isinstance(endDateValue, str):
        raise InputValidationError("dateDifference requires startDate and endDate strings")
    try:
        startDate = date.fromisoformat(startDateValue)
        endDate = date.fromisoformat(endDateValue)
    except ValueError as error:
        raise InputValidationError("dates must use ISO-8601 YYYY-MM-DD format") from error
    return (endDate - startDate).days


COMPUTE_REGISTRY: dict[str, ComputeFunction] = {
    "sum": calculateSum,
    "mean": calculateMean,
    "dateDifference": calculateDateDifference,
}


def executeComputation(functionName: str, inputs: dict[str, Any]) -> ComputeResult:
    """Execute only a pre-registered pure function."""
    computeFunction = COMPUTE_REGISTRY.get(functionName)
    if computeFunction is None:
        raise InputValidationError(f"unsupported computation function: {functionName}")
    return ComputeResult(functionName=functionName, value=computeFunction(inputs), inputs=inputs)
