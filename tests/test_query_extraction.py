"""Verify deterministic extractive claims avoid unnecessary generator round-trips."""

from __future__ import annotations

import pytest

from cortex.config import Settings
from cortex.services.query import QueryService
from cortex.services.retrieval import RetrievedChunk


class GuardModelProvider:
    """Fail fast if a deterministic extraction path still reaches generation."""

    def __init__(self) -> None:
        self.wasCalled = False

    async def generateStructured(self, systemPrompt, userPrompt, responseSchema):  # type: ignore[no-untyped-def]
        self.wasCalled = True
        raise AssertionError("generateStructured should not be called for exact extractive evidence")


@pytest.mark.asyncio
async def testDeterministicExtractiveClaimsSkipGeneratorForStrongTopEvidence() -> None:
    """Strong exact evidence should answer immediately without a model-backed claim pass."""
    settings = Settings(environment="test", requiredAccelerator="cpu")
    modelProvider = GuardModelProvider()
    service = QueryService(
        session=object(),
        settings=settings,
        modelProvider=modelProvider,
    )

    claims, citations, evidenceStatus = await service._generateValidatedClaims(
        [
            RetrievedChunk(
                chunkId="abc123",
                content=(
                    "Raw query and response content is retained for 30 days. Detailed traces "
                    "are retained for 90 days. Content-free audit metadata is retained for "
                    "365 days."
                ),
                structuralLocator="p.1",
                documentTitle="Cortex Retention Standard",
                documentVersion="1.4",
                fusedScore=0.94,
                rerankScore=0.98,
                sourceScore=0.97,
                supportScore=0.96,
                publishedAt=None,
                metadata={},
            )
        ],
        "What are our retention rules?",
    )

    assert modelProvider.wasCalled is False
    assert evidenceStatus == "sufficient"
    assert claims[0].text.startswith("Raw query and response content is retained for 30 days.")
    assert citations[0].exactSpan == claims[0].text
