"""Retry-safe ingestion orchestration with persisted source metadata and inactive versions."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid5

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.domain.chunking import (
    ChunkerConfig,
    ChunkRecord,
    calculateDocumentVersionHash,
    normalizeContent,
    splitDocument,
)
from cortex.errors import InputValidationError
from cortex.services.model_provider import EmbeddingProvider, buildDeterministicEmbedding

VERSION_NAMESPACE = UUID("cd10c605-4ca0-41bc-8854-1db63c49cdef")
EMBEDDING_DIMENSION = 1024


@dataclass(frozen=True, slots=True)
class SourceDocumentMetadata:
    """Capture persisted document-level source attributes independent of versions."""

    sourceType: str = "text"
    displayName: str = ""
    createdBy: str = "system"


@dataclass(frozen=True, slots=True)
class SourceVersionMetadata:
    """Capture version-level diagnostics and blob metadata needed by source onboarding."""

    versionSeedHash: bytes | None = None
    rawHash: bytes | None = None
    canonicalHash: bytes | None = None
    mimeType: str | None = "text/plain"
    objectKey: str | None = None
    parserName: str = "text-api"
    parserVersion: str = "1.0.0"
    extractionDiagnostics: dict[str, Any] = field(default_factory=dict)
    acceleratorReports: tuple[dict[str, Any], ...] = ()
    malwareStatus: str = "not-scanned"
    quarantineStatus: str = "clear"
    ingestionStatus: str = "processing"
    failureCode: str | None = None
    failureDetail: str | None = None


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
        documentMetadata: SourceDocumentMetadata,
        versionMetadata: SourceVersionMetadata,
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

    async def failVersion(
        self,
        versionState: IngestionVersionState,
        failureCode: str,
        failureDetail: str,
        quarantineStatus: str,
    ) -> None:
        """Persist a failed source version without activating it for retrieval."""
        ...


class InMemoryIngestionRepository:
    """Provide deterministic repository semantics for tests and the local demo runtime."""

    def __init__(self) -> None:
        self.versions: dict[tuple[UUID, UUID, UUID], IngestionVersionState] = {}
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
        documentMetadata: SourceDocumentMetadata,
        versionMetadata: SourceVersionMetadata,
    ) -> IngestionVersionState:
        """Create or return the same processing state for a repeated version."""
        del (
            documentTitle,
            sourceUri,
            sourceAuthority,
            extractionQuality,
            publishedAt,
            metadata,
            documentMetadata,
        )
        versionId = calculateVersionId(
            enterpriseId=enterpriseId,
            documentId=documentId,
            versionSeedHash=resolveVersionSeedHash(versionHash, versionMetadata),
            versionLabel=versionLabel,
        )
        try:
            async with self._lock:
                stateKey = (enterpriseId, documentId, versionId)
                state = self.versions.get(stateKey)
                if state is None:
                    state = IngestionVersionState(
                        id=versionId,
                        enterpriseId=enterpriseId,
                        documentId=documentId,
                        versionHash=versionHash,
                        principalIds=principalIds,
                    )
                    self.versions[stateKey] = state
                    self.chunks[state.id] = {}
                elif not state.isActive:
                    state.status = "processing"
                    state.versionHash = versionHash
                    state.principalIds = principalIds
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

    async def failVersion(
        self,
        versionState: IngestionVersionState,
        failureCode: str,
        failureDetail: str,
        quarantineStatus: str,
    ) -> None:
        """Record the failed state in memory so retry tests reflect worker behavior."""
        del failureCode, failureDetail, quarantineStatus
        versionState.isActive = False
        versionState.status = "failed"


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
        documentMetadata: SourceDocumentMetadata,
        versionMetadata: SourceVersionMetadata,
    ) -> IngestionVersionState:
        """Upsert the source document and deterministic processing version."""
        if not principalIds:
            raise InputValidationError("at least one ACL principal is required")
        versionSeedHash = resolveVersionSeedHash(versionHash, versionMetadata)
        versionId = calculateVersionId(
            enterpriseId=enterpriseId,
            documentId=documentId,
            versionSeedHash=versionSeedHash,
            versionLabel=versionLabel,
        )
        mergedExtractionDiagnostics = {
            "extractionQuality": extractionQuality,
            "metadataKeys": sorted(metadata),
            **versionMetadata.extractionDiagnostics,
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
                        id, enterprise_id, title, display_name, source_type, source_uri,
                        source_fingerprint, metadata, created_by, updated_at
                    )
                    VALUES (
                        :document_id, :enterprise_id, :title, :display_name, :source_type,
                        :source_uri, :source_fingerprint, CAST(:metadata AS jsonb),
                        :created_by, now()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        display_name = EXCLUDED.display_name,
                        source_type = EXCLUDED.source_type,
                        source_uri = EXCLUDED.source_uri,
                        source_fingerprint = EXCLUDED.source_fingerprint,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    """
                ),
                {
                    "document_id": documentId,
                    "enterprise_id": enterpriseId,
                    "title": documentTitle,
                    "display_name": documentMetadata.displayName or documentTitle,
                    "source_type": documentMetadata.sourceType,
                    "source_uri": sourceUri,
                    "source_fingerprint": calculateSourceFingerprint(sourceUri),
                    "metadata": serializeJson(metadata),
                    "created_by": documentMetadata.createdBy,
                },
            )
            await self.session.execute(
                text(
                    """
                    INSERT INTO document_version (
                        id, enterprise_id, document_id, acl_principals, version_hash,
                        version_label, raw_hash, canonical_hash, mime_type, object_key,
                        parser_name, parser_version, source_authority, published_at, status,
                        ingestion_status, quarantine_status, malware_status,
                        extraction_diagnostics, accelerator_reports, failure_code, failure_detail
                    ) VALUES (
                        :version_id, :enterprise_id, :document_id, CAST(:acl_principals AS jsonb),
                        :version_hash, :version_label, :raw_hash, :canonical_hash,
                        :mime_type, :object_key, :parser_name, :parser_version,
                        :source_authority, :published_at, 'processing',
                        :ingestion_status, :quarantine_status, :malware_status,
                        CAST(:extraction_diagnostics AS jsonb),
                        CAST(:accelerator_reports AS jsonb), NULL, NULL
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        acl_principals = EXCLUDED.acl_principals,
                        version_hash = EXCLUDED.version_hash,
                        version_label = EXCLUDED.version_label,
                        raw_hash = EXCLUDED.raw_hash,
                        canonical_hash = EXCLUDED.canonical_hash,
                        mime_type = EXCLUDED.mime_type,
                        object_key = EXCLUDED.object_key,
                        parser_name = EXCLUDED.parser_name,
                        parser_version = EXCLUDED.parser_version,
                        source_authority = EXCLUDED.source_authority,
                        published_at = EXCLUDED.published_at,
                        status = CASE
                            WHEN document_version.status = 'active'
                            THEN 'active'::document_version_status
                            ELSE 'processing'::document_version_status
                        END,
                        ingestion_status = CASE
                            WHEN document_version.status = 'active'
                            THEN 'active'
                            ELSE EXCLUDED.ingestion_status
                        END,
                        quarantine_status = EXCLUDED.quarantine_status,
                        malware_status = EXCLUDED.malware_status,
                        extraction_diagnostics = EXCLUDED.extraction_diagnostics,
                        accelerator_reports = EXCLUDED.accelerator_reports,
                        failure_code = NULL,
                        failure_detail = NULL
                    """
                ),
                {
                    "version_id": versionId,
                    "enterprise_id": enterpriseId,
                    "document_id": documentId,
                    "acl_principals": serializeJson(list(principalIds)),
                    "version_hash": versionHash,
                    "version_label": versionLabel,
                    "raw_hash": versionMetadata.rawHash or versionHash,
                    "canonical_hash": versionMetadata.canonicalHash or versionHash,
                    "mime_type": versionMetadata.mimeType,
                    "object_key": versionMetadata.objectKey,
                    "parser_name": versionMetadata.parserName,
                    "parser_version": versionMetadata.parserVersion,
                    "source_authority": sourceAuthority,
                    "published_at": publishedAt,
                    "ingestion_status": versionMetadata.ingestionStatus,
                    "quarantine_status": versionMetadata.quarantineStatus,
                    "malware_status": versionMetadata.malwareStatus,
                    "extraction_diagnostics": serializeJson(mergedExtractionDiagnostics),
                    "accelerator_reports": serializeJson(list(versionMetadata.acceleratorReports)),
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return IngestionVersionState(
            id=versionId,
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
                            document_version_id = EXCLUDED.document_version_id,
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
                    SET status = 'superseded',
                        ingestion_status = 'superseded'
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
                    SET status = 'active',
                        ingestion_status = 'active',
                        quarantine_status = 'clear',
                        failure_code = NULL,
                        failure_detail = NULL,
                        activated_at = now()
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

    async def failVersion(
        self,
        versionState: IngestionVersionState,
        failureCode: str,
        failureDetail: str,
        quarantineStatus: str,
    ) -> None:
        """Persist failure metadata so source operations can inspect the broken version."""
        try:
            await self.session.execute(
                text(
                    """
                    UPDATE document_version
                    SET status = 'failed',
                        ingestion_status = 'failed',
                        quarantine_status = :quarantine_status,
                        failure_code = :failure_code,
                        failure_detail = :failure_detail
                    WHERE id = :version_id
                    """
                ),
                {
                    "version_id": versionState.id,
                    "quarantine_status": quarantineStatus,
                    "failure_code": failureCode[:120],
                    "failure_detail": failureDetail[:4000],
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        versionState.isActive = False
        versionState.status = "failed"


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
        documentMetadata: SourceDocumentMetadata | None = None,
        versionMetadata: SourceVersionMetadata | None = None,
    ) -> IngestionResult:
        """Ingest text idempotently and leave failed attempts inactive."""
        metadata = metadata or {}
        documentMetadata = documentMetadata or SourceDocumentMetadata(
            sourceType="text",
            displayName=documentTitle,
            createdBy="system",
        )
        versionMetadata = versionMetadata or buildDefaultVersionMetadata(content)
        documentVersionHash = calculateDocumentVersionHash(content, versionLabel, documentId)
        normalizedContent = normalizeContent(content)
        effectiveVersionMetadata = SourceVersionMetadata(
            versionSeedHash=versionMetadata.versionSeedHash,
            rawHash=versionMetadata.rawHash or calculateRawContentHash(content),
            canonicalHash=versionMetadata.canonicalHash
            or calculateCanonicalContentHash(normalizedContent),
            mimeType=versionMetadata.mimeType,
            objectKey=versionMetadata.objectKey,
            parserName=versionMetadata.parserName,
            parserVersion=versionMetadata.parserVersion,
            extractionDiagnostics=versionMetadata.extractionDiagnostics,
            acceleratorReports=versionMetadata.acceleratorReports,
            malwareStatus=versionMetadata.malwareStatus,
            quarantineStatus=versionMetadata.quarantineStatus,
            ingestionStatus=versionMetadata.ingestionStatus,
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
            metadata,
            documentMetadata,
            effectiveVersionMetadata,
        )
        try:
            chunks = splitDocument(enterpriseId, documentVersionHash, normalizedContent, config)
            preparedChunks = await self._prepareChunks(
                documentTitle=documentTitle,
                versionLabel=versionLabel,
                sourceUri=sourceUri,
                sourceAuthority=sourceAuthority,
                extractionQuality=extractionQuality,
                chunks=chunks,
            )
            for batchIndex, batchStart in enumerate(
                range(0, len(preparedChunks), self.batchSize), start=1
            ):
                chunkBatch = preparedChunks[batchStart : batchStart + self.batchSize]
                await self.repository.upsertChunkBatch(versionState, chunkBatch)
                if failAfterBatches is not None and batchIndex >= failAfterBatches:
                    raise RuntimeError("injected ingestion failure")
            expectedChunkIds = {preparedChunk.chunk.id for preparedChunk in preparedChunks}
            await self.repository.activateVersion(versionState, expectedChunkIds)
        except Exception as error:
            await self.repository.failVersion(
                versionState=versionState,
                failureCode="INGESTION_FAILED",
                failureDetail=str(error),
                quarantineStatus="quarantined",
            )
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


def calculateVersionId(
    enterpriseId: UUID,
    documentId: UUID,
    versionSeedHash: bytes,
    versionLabel: str,
) -> UUID:
    """Create a deterministic version row identifier that survives retries before parsing."""
    if len(versionSeedHash) != 32:
        raise InputValidationError("versionSeedHash must contain 32 bytes")
    if not versionLabel.strip():
        raise InputValidationError("versionLabel cannot be empty")
    return uuid5(
        VERSION_NAMESPACE,
        f"{enterpriseId}:{documentId}:{versionSeedHash.hex()}:{versionLabel.strip()}",
    )


def resolveVersionSeedHash(
    versionHash: bytes,
    versionMetadata: SourceVersionMetadata,
) -> bytes:
    """Prefer an onboarding seed hash while keeping text-only ingestion deterministic."""
    seedHash = versionMetadata.versionSeedHash or versionMetadata.rawHash or versionHash
    if len(seedHash) != 32:
        raise InputValidationError("version seed hash must contain 32 bytes")
    return seedHash


def buildDefaultVersionMetadata(content: str) -> SourceVersionMetadata:
    """Build deterministic defaults for internal text ingestion without binary source blobs."""
    normalizedContent = normalizeContent(content)
    return SourceVersionMetadata(
        rawHash=calculateRawContentHash(content),
        canonicalHash=calculateCanonicalContentHash(normalizedContent),
        mimeType="text/plain",
        parserName="text-api",
        parserVersion="1.0.0",
        ingestionStatus="processing",
        quarantineStatus="clear",
        malwareStatus="not-scanned",
    )


def calculateRawContentHash(content: str) -> bytes:
    """Hash raw pre-normalized text so uploads can deduplicate exact bytes."""
    return hashlib.sha256(content.encode("utf-8")).digest()


def calculateCanonicalContentHash(normalizedContent: str) -> bytes:
    """Hash normalized content so canonical document equality survives superficial formatting."""
    return hashlib.sha256(normalizedContent.encode("utf-8")).digest()


def formatVector(embedding: list[float]) -> str:
    """Serialize a dense vector into pgvector's textual input format."""
    if len(embedding) != EMBEDDING_DIMENSION:
        raise InputValidationError(
            f"embedding dimension must be {EMBEDDING_DIMENSION}, received {len(embedding)}"
        )
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def serializeJson(value: Any) -> str:
    """Serialize JSON payloads deterministically for raw SQL inserts."""
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
