"""Verify deterministic chunk identity and boundary-affecting inputs."""

from uuid import UUID

from cortex.domain.chunking import (
    ChunkerConfig,
    calculateChunkerConfigHash,
    calculateDocumentVersionHash,
    splitDocument,
)

ENTERPRISE_ID = UUID("00000000-0000-0000-0000-000000000001")


def testChunkIdsRepeatForIdenticalInputs() -> None:
    """The same version and config must yield byte-identical primary keys."""
    content = "A deterministic paragraph. " * 120
    documentId = UUID("00000000-0000-0000-0000-000000000101")
    versionHash = calculateDocumentVersionHash(content, "v1", documentId)
    config = ChunkerConfig(size=240, overlap=40)

    firstChunks = splitDocument(ENTERPRISE_ID, versionHash, content, config)
    secondChunks = splitDocument(ENTERPRISE_ID, versionHash, content, config)

    assert [chunk.id for chunk in firstChunks] == [chunk.id for chunk in secondChunks]
    assert all(len(chunk.id) == 32 for chunk in firstChunks)


def testRepeatedPassagesRemainDistinctByLocator() -> None:
    """Identical text occurrences must not collide inside one document version."""
    content = "Repeated phrase. " * 200
    documentId = UUID("00000000-0000-0000-0000-000000000101")
    versionHash = calculateDocumentVersionHash(content, "v1", documentId)
    chunks = splitDocument(
        ENTERPRISE_ID,
        versionHash,
        content,
        ChunkerConfig(size=128, overlap=0),
    )

    assert len(chunks) == len({chunk.id for chunk in chunks})


def testChunkerConfigHashChangesWithOverlap() -> None:
    """Any boundary-affecting setting must change the configuration digest."""
    firstHash = calculateChunkerConfigHash(ChunkerConfig(size=200, overlap=20))
    secondHash = calculateChunkerConfigHash(ChunkerConfig(size=200, overlap=40))

    assert firstHash != secondHash


def testDifferentDocumentsCannotCollideOnIdenticalContent() -> None:
    """Source identity must keep separately governed duplicate documents distinct."""
    content = "The same approved policy text."
    firstDocumentId = UUID("00000000-0000-0000-0000-000000000101")
    secondDocumentId = UUID("00000000-0000-0000-0000-000000000102")

    firstHash = calculateDocumentVersionHash(content, "v1", firstDocumentId)
    secondHash = calculateDocumentVersionHash(content, "v1", secondDocumentId)

    assert firstHash != secondHash
