"""Fail-closed accelerator enforcement for expensive ingestion model stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cortex.errors import HardwareAccelerationError
from cortex.logging_config import getLogger

AcceleratorName = Literal["cpu", "mps", "cuda", "unknown"]
logger = getLogger("ingestion-accelerator")


@dataclass(frozen=True, slots=True)
class AcceleratorReport:
    """Record the configured and observed device for one model stage."""

    stageName: str
    requiredDevice: str
    actualDevice: AcceleratorName
    isStrict: bool


def detectAvailableAccelerator() -> AcceleratorName:
    """Detect the best accelerator exposed by the installed PyTorch runtime."""
    try:
        import torch
    except ImportError:
        return "unknown"
    if bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def enforceAcceleratorBinding(
    stageName: str,
    requiredDevice: str,
    actualDevice: AcceleratorName,
    isStrict: bool,
) -> AcceleratorReport:
    """Emit an auditable mismatch and halt strict profiles before slow OCR proceeds."""
    if not stageName.strip() or not requiredDevice.strip():
        raise ValueError("stageName and requiredDevice cannot be empty")
    report = AcceleratorReport(
        stageName=stageName,
        requiredDevice=requiredDevice,
        actualDevice=actualDevice,
        isStrict=isStrict,
    )
    if requiredDevice not in {"auto", actualDevice}:
        logger.error(
            "OCR_ACCELERATOR_MISMATCH",
            eventCode="OCR_ACCELERATOR_MISMATCH",
            stageName=stageName,
            requiredAccelerator=requiredDevice,
            actualAccelerator=actualDevice,
            isStrict=isStrict,
        )
        if isStrict:
            raise HardwareAccelerationError(
                f"{stageName} requires {requiredDevice} but resolved {actualDevice}"
            )
    else:
        logger.info(
            "accelerator_binding_verified",
            stageName=stageName,
            requiredAccelerator=requiredDevice,
            actualAccelerator=actualDevice,
        )
    return report
