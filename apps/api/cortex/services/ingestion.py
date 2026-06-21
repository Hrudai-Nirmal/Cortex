"""Retry-safe ingestion orchestration with persisted embeddings and inactive versions."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid5

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.domain.chunking import (
    ChunkerConfig,
    ChunkRecord,
    calculateDocumentVersionHash,
    splitDocument,
)
from cortex.errors import InputValidationError
from cortex.services.model_provider import EmbeddingProvider, buildDeterministicEmbedding

VERSION_NAMESPACE = UUID("cd10c605-4ca0-41bc-8854-1db63c49cdef")
EMBEDDING_DIMENSION = 1024


@dataclass(slots=True)
class IngestionVersionState:
    """Track one version's chunks and activation state for idempotent retries."""

    id: UUID
    enterpriseId: UUID
    documentId: UUID
    versionHash: bytes
    principalIds: tuple[str, ...]
    isActive: bool = False
    status: str = "processing"


@dataclass(frozen=True, slots=True)
class PreparedChunkRecord:
    """Carry one chunk plus its persisted embedding and scoring metadata."""

    chunk: ChunkRecord
    embedding: list[float]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Describe the stable database outcome of an ingestion attempt."""

    documentVersionId: UUID
    documentVersionHash: str
    chunkCount: int
    chunkIds: tuple[str, ...]
    status: str


class IngestionRepository(Protocol):
    """Define persistence operations required by the ingestion transaction."""

    async def beginVersion(
        self,
        enterpriseId: UUID,
        documentId: UUID,
        documentTitle: str,
        versionHash: bytes,
        versionLabel: str,
        sourceUri: str,
        principalIds: tuple[str, ...],
        sourceAuthority: float,
        extractionQuality: float,
        publishedAt: datetime | None,
        metadata: dict[str, Any],
    ) -> IngestionVersionState:
        """Create or reopen a processing version by deterministic identity."""
        ...

    async def upsertChunkBatch(
        self,
        versionState: IngestionVersionState,
        chunkBatch: list[PreparedChunkRecord],
    ) -> None:
        """Upsert a deterministic batch without duplicating rows."""
        ...

    async def activateVersion(
        self, versionState: IngestionVersionState, expectedChunkIds: set[bytes]
    ) -> None:
        """Reconcile stale chunks and atomically make the completed version visible."""
        ...


class InMemoryIngestionRepository:
    """Provide deterministic repository semantics for tests and the local demo runtime."""

    def __init__(self) -> None:
        self.versions: dict[tuple[UUID, UUID, bytes], IngestionVersionState] = {}
        self.chunks: dict[UUID, dict[bytes, PreparedChunkRecord]] = {}
        self._lock = asyncio.Lock()

    async def beginVersion(
        self,
        enterpriseId: UUID,
        documentId: UUID,
        documentTitle: str,
        versionHash: bytes,
        versionLabel: str,
        sourceUri: str,
        principalIds: tuple[str, ...],
        sourceAuthority: float,
        extractionQuality: float,
        publishedAt: datetime | None,
        metadata: dict[str, Any],
    ) -> IngestionVersionState:
        """Create or return the same processing state for a repeated version."""
        del (
            documentTitle,
            versionLabel,
            sourceUri,
            sourceAuthority,
            extractionQuality,
            publishedAt,
            metadata,
        )
        try:
            async with self._lock:
                stateKey = (enterpriseId, documentId, versionHash)
                state = self.versions.get(stateKey)
                if state is None:
                    deterministicId = uuid5(
                        VERSION_NAMESPACE,
                        f"{enterpriseId}:{documentId}:{versionHash.hex()}",
                    )
                    state = IngestionVersionState(
                        id=deterministicId,
                        enterpriseId=enterpriseId,
                        documentId=documentId,
                        versionHash=versionHash,
                        principalIds=principalIds,
                    )
                    self.versions[stateKey] = state
                    self.chunks[state.id] = {}
                elif not state.isActive:
                    state.status = "processing"
                return state
        except Exception:
            raise

    async def upsertChunkBatch(
        self,
        versionState: IngestionVersionState,
        chunkBatch: list[PreparedChunkRecord],
    ) -> None:
        """Replace rows by deterministic primary key inside one lock."""
        if not chunkBatch:
            raise InputValidationError("chunk batch cannot be empty")
        try:
            async with self._lock:
                for preparedChunk in chunkBatch:
                    self.chunks[versionState.id][preparedChunk.chunk.id] = preparedChunk
        except Exception:
            raise

    async def activateVersion(
        self, versionState: IngestionVersionState, expectedChunkIds: set[bytes]
    ) -> None:
        """Remove stale rows and expose only a complete expected chunk set."""
        if not expectedChunkIds:
            raise InputValidationError("cannot activate a version with no chunks")
        try:
            async with self._lock:
                versionChunks = self.chunks[versionState.id]
                self.chunks[versionState.id] = {
                    chunkId: preparedChunk
                    for chunkId, preparedChunk in versionChunks.items()
                    if chunkId in expectedChunkIds
                }
                if set(self.chunks[versionState.id]) != expectedChunkIds:
                    raise InputValidationError("version activation found missing chunk rows")
                versionState.isActive = True
                versionState.status = "active"
        except Exception:
            raise


class PostgresIngestionRepository:
    """Persist retry checkpoints while keeping processing versions invisible."""

    def __init__(self, session: AsyncSession) -> None:
        if session is None:
            raise ValueError("session is required")
        self.session = session

    async def beginVersion(
        self,
        enterpriseId: UUID,
        documentId: UUID,
        documentTitle: str,
        versionHash: bytes,
        versionLabel: str,
        sourceUri: str,
        principalIds: tuple[str, ...],
        sourceAuthority: float,
        extractionQuality: float,
        publishedAt: datetime | None,
        metadata: dict[str, Any],
    ) -> IngestionVersionState:
        """Upsert the source and deterministic processing version."""
        if not principalIds:
            raise InputValidationError("at least one ACL principal is required")
        deterministicId = uuid5(
            VERSION_NAMESPACE,
            f"{enterpriseId}:{documentId}:{versionHash.hex()}",
        )
        extractionDiagnostics = {
            "extractionQuality": extractionQuality,
            "metadataKeys": sorted(metadata),
        }
        try:
            await self.session.execute(
                text(
                    """
                    INSERT INTO enterprise (id, name)
                    VALUES (:enterprise_id, 'Cortex Enterprise')
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"enterprise_id": enterpriseId},
            )
            await self.session.execute(
                text(
                    """
                    INSERT INTO document (
                        id, enterprise_id, title, source_uri, source_fingerprint, metadata
                    )
                    VALUES (
                        :document_id, :enterprise_id, :title, :source_uri,
                        :source_fingerprint, CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        source_uri = EXCLUDED.source_uri,
                        source_fingerprint = EXCLUDED.source_fingerprint,
                        metadata = EXCLUDED.metadata
                    """
                ),
                {
                    "document_id": documentId,
                    "enterprise_id": enterpriseId,
                    "title": documentTitle,
                    "source_uri": sourceUri,
                    "source_fingerprint": calculateSourceFingerprint(sourceUri),
                    "metadata": serializeJson(metadata),
                },
            )
            await self.session.execute(
                text(
                    """
                    INSERT INTO document_version (
                        id, enterprise_id, document_id, version_hash, version_label, raw_hash,
                        canonical_hash, parser_version, source_authority, published_at,
                        extraction_diagnostics, status
                    ) VALUES (
                        :version_id, :enterprise_id, :document_id, :version_hash, :version_label,
                        :version_hash, :version_hash, 'text-api-v1',
                        :source_authority, :published_at,
                        CAST(:extraction_diagnostics AS jsonb), 'processing'
                    )
                    ON CONFLICT (enterprise_id, document_id, version_hash) DO UPDATE SET
                        version_label = EXCLUDED.version_label,
                        source_authority = EXCLUDED.source_authority,
                        published_at = EXCLUDED.published_at,
                        extraction_diagnostics = EXCLUDED.extraction_diagnostics,
                        status = CASE
                            WHEN document_version.status = 'active'
                            THEN 'active'::document_version_status
                            ELSE 'processing'::document_version_status
                        END
                    """
                ),
                {
                    "version_id": deterministicId,
                    "enterprise_id": enterpriseId,
                    "document_id": documentId,
                    "version_hash": versionHash,
                    "version_label": versionLabel,
                    "source_authority": sourceAuthority,
                    "published_at": publishedAt,
                    "extraction_diagnostics": serializeJson(extractionDiagnostics),
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return IngestionVersionState(
            id=deterministicId,
            enterpriseId=enterpriseId,
            documentId=documentId,
            versionHash=versionHash,
            principalIds=principalIds,
        )

    async def upsertChunkBatch(
        self,
        versionState: IngestionVersionState,
        chunkBatch: list[PreparedChunkRecord],
    ) -> None:
        """Upsert chunk rows and exact ACL principals, then commit the retry checkpoint."""
        if not chunkBatch:
            raise InputValidationError("chunk batch cannot be empty")
        try:
            for preparedChunk in chunkBatch:
                chunk = preparedChunk.chunk
                await self.session.execute(
                    text(
                        """
                        INSERT INTO chunk (
                            id, enterprise_id, document_version_id, structural_locator,
                            ordinal, normalized_content, chunker_config_hash, metadata, embedding
                        ) VALUES (
                            :chunk_id, :enterprise_id, :version_id, :locator,
                            :ordinal, :content, :config_hash, CAST(:metadata AS jsonb),
                            CAST(:embedding AS vector)
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            structural_locator = EXCLUDED.structural_locator,
                            ordinal = EXCLUDED.ordinal,
                            normalized_content = EXCLUDED.normalized_content,
                            chunker_config_hash = EXCLUDED.chunker_config_hash,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding
                        """
                    ),
                    {
                        "chunk_id": chunk.id,
                        "enterprise_id": versionState.enterpriseId,
                        "version_id": versionState.id,
                        "locator": chunk.structuralLocator,
                        "ordinal": chunk.ordinal,
                        "content": chunk.normalizedContent,
                        "config_hash": chunk.chunkerConfigHash,
                        "metadata": serializeJson(preparedChunk.metadata),
                        "embedding": formatVector(preparedChunk.embedding),
                    },
                )
                await self.session.execute(
                    text(
                        """
                        DELETE FROM chunk_acl
                        WHERE chunk_id = :chunk_id AND enterprise_id = :enterprise_id
                        """
                    ),
                    {"chunk_id": chunk.id, "enterprise_id": versionState.enterpriseId},
                )
                for principalId in versionState.principalIds:
                    await self.session.execute(
                        text(
                            """
                            INSERT INTO chunk_acl (chunk_id, enterprise_id, principal_id)
                            VALUES (:chunk_id, :enterprise_id, :principal_id)
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {
                            "chunk_id": chunk.id,
                            "enterprise_id": versionState.enterpriseId,
                            "principal_id": principalId,
                        },
                    )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def activateVersion(
        self, versionState: IngestionVersionState, expectedChunkIds: set[bytes]
    ) -> None:
        """Reconcile stale retry artifacts and atomically promote the complete version."""
        if not expectedChunkIds:
            raise InputValidationError("cannot activate a version with no chunks")
        try:
            deleteStatement = text(
                """
                DELETE FROM chunk
                WHERE document_version_id = :version_id AND id NOT IN :expected_ids
                """
            ).bindparams(bindparam("expected_ids", expanding=True))
            await self.session.execute(
                deleteStatement,
                {"version_id": versionState.id, "expected_ids": list(expectedChunkIds)},
            )
            countResult = await self.session.execute(
                text("SELECT count(*) FROM chunk WHERE document_version_id = :version_id"),
                {"version_id": versionState.id},
            )
            if int(countResult.scalar_one()) != len(expectedChunkIds):
                raise InputValidationError("version activation found missing chunk rows")
            await self.session.execute(
                text(
                    """
                    UPDATE document_version
                    SET status = 'superseded'
                    WHERE document_id = :document_id
                      AND status = 'active'
                      AND id <> :version_id
                    """
                ),
                {"document_id": versionState.documentId, "version_id": versionState.id},
            )
            await self.session.execute(
                text(
                    """
                    UPDATE document_version
                    SET status = 'active', activated_at = now()
                    WHERE id = :version_id
                    """
                ),
                {"version_id": versionState.id},
            )
            await self.session.commit()
            versionState.isActive = True
            versionState.status = "active"
        except Exception:
            await self.session.rollback()
            raise


class IngestionService:
    """Coordinate deterministic chunk creation, embeddings, and repository activation."""

    def __init__(
        self,
        repository: IngestionRepository,
        embeddingProvider: EmbeddingProvider | None = None,
        batchSize: int = 100,
    ) -> None:
        if repository is None:
            raise ValueError("repository is required")
        if batchSize < 1:
            raise ValueError("batchSize must be positive")
        self.repository = repository
        self.embeddingProvider = embeddingProvider
        self.batchSize = batchSize

    async def ingestText(
        self,
        enterpriseId: UUID,
        documentId: UUID,
        documentTitle: str,
        versionLabel: str,
        content: str,
        config: ChunkerConfig,
        sourceUri: str = "memory://document",
        principalIds: tuple[str, ...] = ("group:employees",),
        sourceAuthority: float = 0.85,
        extractionQuality: float = 0.9,
        publishedAt: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        failAfterBatches: int | None = None,
    ) -> IngestionResult:
        """Ingest text idempotently and leave failed attempts inactive."""
        documentVersionHash = calculateDocumentVersionHash(content, versionLabel, documentId)
        chunks = splitDocument(enterpriseId, documentVersionHash, content, config)
        preparedChunks = await self._prepareChunks(
            documentTitle=documentTitle,
            versionLabel=versionLabel,
            sourceUri=sourceUri,
            sourceAuthority=sourceAuthority,
            extractionQuality=extractionQuality,
            chunks=chunks,
        )
        versionState = await self.repository.beginVersion(
            enterpriseId,
            documentId,
            documentTitle,
            documentVersionHash,
            versionLabel,
            sourceUri,
            principalIds,
            sourceAuthority,
            extractionQuality,
            publishedAt.astimezone(UTC) if publishedAt else None,
            metadata or {},
        )
        try:
            for batchIndex, batchStart in enumerate(
                range(0, len(preparedChunks), self.batchSize), start=1
            ):
                chunkBatch = preparedChunks[batchStart : batchStart + self.batchSize]
                await self.repository.upsertChunkBatch(versionState, chunkBatch)
                if failAfterBatches is not None and batchIndex >= failAfterBatches:
                    versionState.status = "failed"
                    raise RuntimeError("injected ingestion failure")
            expectedChunkIds = {preparedChunk.chunk.id for preparedChunk in preparedChunks}
            await self.repository.activateVersion(versionState, expectedChunkIds)
        except Exception:
            versionState.isActive = False
            raise
        return IngestionResult(
            documentVersionId=versionState.id,
            documentVersionHash=documentVersionHash.hex(),
            chunkCount=len(preparedChunks),
            chunkIds=tuple(preparedChunk.chunk.idHex for preparedChunk in preparedChunks),
            status=versionState.status,
        )

    async def _prepareChunks(
        self,
        documentTitle: str,
        versionLabel: str,
        sourceUri: str,
        sourceAuthority: float,
        extractionQuality: float,
        chunks: list[ChunkRecord],
    ) -> list[PreparedChunkRecord]:
        """Attach persisted metadata and embeddings without changing chunk identities."""
        chunkTexts = [chunk.normalizedContent for chunk in chunks]
        if self.embeddingProvider is None:
            embeddings = [buildDeterministicEmbedding(chunkText) for chunkText in chunkTexts]
        else:
            embeddings = await self.embeddingProvider.embedTexts(chunkTexts)
        if len(embeddings) != len(chunks):
            raise InputValidationError("embedding provider returned the wrong number of vectors")
        preparedChunks: list[PreparedChunkRecord] = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            if len(embedding) != EMBEDDING_DIMENSION:
                raise InputValidationError(
                    f"embedding dimension must be {EMBEDDING_DIMENSION}, received {len(embedding)}"
                )
            preparedChunks.append(
                PreparedChunkRecord(
                    chunk=chunk,
                    embedding=embedding,
                    metadata={
                        "documentTitle": documentTitle,
                        "documentVersion": versionLabel,
                        "sourceUri": sourceUri,
                        "sourceAuthority": sourceAuthority,
                        "extractionQuality": extractionQuality,
                    },
                )
            )
        return preparedChunks


def calculateSourceFingerprint(sourceUri: str) -> bytes:
    """Create a stable fingerprint without retaining credentials from source URLs."""
    normalizedUri = sourceUri.strip().lower()
    if not normalizedUri:
        raise InputValidationError("sourceUri cannot be empty")
    return hashlib.sha256(normalizedUri.encode("utf-8")).digest()


def formatVector(embedding: list[float]) -> str:
    """Serialize a dense vector into pgvector's textual input format."""
    if len(embedding) != EMBEDDING_DIMENSION:
        raise InputValidationError(
            f"embedding dimension must be {EMBEDDING_DIMENSION}, received {len(embedding)}"
        )
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def serializeJson(value: dict[str, Any]) -> str:
    """Serialize JSON payloads deterministically for raw SQL inserts."""
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
