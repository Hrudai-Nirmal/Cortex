"""Verify strict MPS development profiles fail closed on CPU fallback."""

import pytest
from cortex.errors import HardwareAccelerationError
from cortex.services.accelerator import enforceAcceleratorBinding


def testStrictMpsProfileRejectsCpu() -> None:
    """Developers must not silently index PDFs on CPU when MPS is required."""
    with pytest.raises(HardwareAccelerationError, match="requires mps"):
        enforceAcceleratorBinding(
            stageName="docling-ocr",
            requiredDevice="mps",
            actualDevice="cpu",
            isStrict=True,
        )


def testExplicitCpuProfileIsAllowed() -> None:
    """CI can opt into CPU without weakening the strict macOS profile."""
    report = enforceAcceleratorBinding(
        stageName="docling-ocr",
        requiredDevice="cpu",
        actualDevice="cpu",
        isStrict=True,
    )

    assert report.actualDevice == "cpu"
