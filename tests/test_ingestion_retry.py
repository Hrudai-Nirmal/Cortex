"""Failure-injection tests prove retries converge on one active database state."""

from uuid import UUID

import pytest
from cortex.domain.chunking import ChunkerConfig
from cortex.services.ingestion import IngestionService, InMemoryIngestionRepository

ENTERPRISE_ID = UUID("00000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000101")


@pytest.mark.asyncio
async def testInterruptedIngestionRetriesWithoutDuplicates() -> None:
    """A failed batch must remain invisible and retry to byte-identical chunks."""
    repository = InMemoryIngestionRepository()
    ingestionService = IngestionService(repository, batchSize=2)
    content = "Enterprise evidence must be deterministic. " * 180
    config = ChunkerConfig(size=160, overlap=20)

    with pytest.raises(RuntimeError, match="injected ingestion failure"):
        await ingestionService.ingestText(
            ENTERPRISE_ID,
            DOCUMENT_ID,
            "Deterministic Retry Policy",
            "version-1",
            content,
            config,
            failAfterBatches=2,
        )

    failedState = next(iter(repository.versions.values()))
    assert failedState.isActive is False
    partialIds = set(repository.chunks[failedState.id])

    retryResult = await ingestionService.ingestText(
        ENTERPRISE_ID,
        DOCUMENT_ID,
        "Deterministic Retry Policy",
        "version-1",
        content,
        config,
    )
    finalState = next(iter(repository.versions.values()))
    finalChunks = repository.chunks[finalState.id]

    assert retryResult.status == "active"
    assert finalState.isActive is True
    assert partialIds.issubset(finalChunks)
    assert len(finalChunks) == len(set(retryResult.chunkIds))
    assert {chunkId.hex() for chunkId in finalChunks} == set(retryResult.chunkIds)
