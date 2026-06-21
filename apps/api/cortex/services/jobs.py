"""PostgreSQL-backed durable job queue for worker-driven ingestion and retention work."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings
from cortex.domain.chunking import ChunkerConfig
from cortex.schemas import IngestTextRequest
from cortex.services.ingestion import (
    IngestionService,
    PostgresIngestionRepository,
    SourceDocumentMetadata,
    SourceVersionMetadata,
    calculateCanonicalContentHash,
)
from cortex.services.malware_scanner import NoOpMalwareScanner
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.object_storage import LocalObjectStorage
from cortex.services.parser import ParserRegistry
from cortex.services.retention import purgeExpiredTraces, redactExpiredRawContent


class SourceIngestionJobPayload(BaseModel):
    """Validate durable source-ingestion jobs before worker execution mutates state."""

    actorId: str = Field(min_length=1)
    displayName: str = Field(min_length=1)
    documentId: UUID
    enterpriseId: UUID
    extractionQuality: float = Field(ge=0, le=1)
    fileName: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    mimeType: str = Field(min_length=1)
    objectKey: str = Field(min_length=1)
    principalIds: list[str] = Field(min_length=1)
    publishedAt: str | None = None
    rawSha256: str = Field(min_length=64, max_length=64)
    sourceAuthority: float = Field(ge=0, le=1)
    sourceType: str = Field(min_length=1)
    sourceUri: str = Field(min_length=1)
    versionId: UUID
    versionLabel: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class DurableJobRecord:
    """Represent one claimed queue item ready for worker execution."""

    id: UUID
    enterpriseId: UUID
    jobType: str
    payload: dict[str, Any]


class DurableJobService:
    """Enqueue and claim durable jobs without introducing an external broker."""

    def __init__(self, session: AsyncSession) -> None:
        if session is None:
            raise ValueError("session is required")
        self.session = session

    async def enqueueIngestionJob(self, request: IngestTextRequest) -> UUID:
        """Persist a worker-executed text ingestion request under a stable idempotency key."""
        return await self._enqueueJob(
            enterpriseId=request.enterpriseId,
            jobType="ingestion.text",
            payload=request.model_dump(mode="json"),
        )

    async def enqueueSourceIngestionJob(self, payload: dict[str, Any]) -> UUID:
        """Persist a queued source-object ingestion request under a stable idempotency key."""
        enterpriseId = UUID(str(payload["enterpriseId"]))
        return await self._enqueueJob(
            enterpriseId=enterpriseId,
            jobType="ingestion.source",
            payload=payload,
        )

    async def _enqueueJob(
        self,
        *,
        enterpriseId: UUID,
        jobType: str,
        payload: dict[str, Any],
    ) -> UUID:
        serializedPayload = normalizePayload(payload)
        idempotencyKey = buildIdempotencyKey(jobType, serializedPayload)
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
            result = await self.session.execute(
                text(
                    """
                    INSERT INTO durable_job (
                        id, enterprise_id, job_type, idempotency_key, payload, status
                    ) VALUES (
                        :job_id, :enterprise_id, :job_type, :idempotency_key,
                        CAST(:payload AS jsonb), 'queued'
                    )
                    ON CONFLICT (enterprise_id, idempotency_key) DO UPDATE SET
                        updated_at = now()
                    RETURNING id
                    """
                ),
                {
                    "job_id": uuid4(),
                    "enterprise_id": enterpriseId,
                    "job_type": jobType,
                    "idempotency_key": idempotencyKey,
                    "payload": json.dumps(serializedPayload, sort_keys=True, separators=(",", ":")),
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return result.scalar_one()

    async def claimNextJob(self) -> DurableJobRecord | None:
        """Claim one queued job with SKIP LOCKED so workers can scale horizontally."""
        try:
            result = await self.session.execute(
                text(
                    """
                    WITH next_job AS (
                        SELECT id
                        FROM durable_job
                        WHERE status = 'queued' AND available_at <= now()
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE durable_job AS job
                    SET status = 'running',
                        locked_at = now(),
                        attempts = attempts + 1,
                        updated_at = now()
                    FROM next_job
                    WHERE job.id = next_job.id
                    RETURNING job.id, job.enterprise_id, job.job_type, job.payload
                    """
                )
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        row = result.mappings().first()
        if row is None:
            return None
        payloadValue = row["payload"] if isinstance(row["payload"], dict) else {}
        return DurableJobRecord(
            id=row["id"],
            enterpriseId=row["enterprise_id"],
            jobType=row["job_type"],
            payload=payloadValue,
        )

    async def completeJob(self, jobId: UUID) -> None:
        """Mark a claimed job complete once its side effect has committed safely."""
        try:
            await self.session.execute(
                text(
                    """
                    UPDATE durable_job
                    SET status = 'completed', locked_at = NULL, updated_at = now()
                    WHERE id = :job_id
                    """
                ),
                {"job_id": jobId},
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def failJob(self, jobId: UUID, errorMessage: str) -> None:
        """Persist a job failure without losing its last error detail."""
        try:
            await self.session.execute(
                text(
                    """
                    UPDATE durable_job
                    SET status = 'failed',
                        locked_at = NULL,
                        last_error = :last_error,
                        updated_at = now()
                    WHERE id = :job_id
                    """
                ),
                {"job_id": jobId, "last_error": errorMessage[:4000]},
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise


async def processJob(
    session: AsyncSession,
    settings: Settings,
    modelProvider: OllamaModelProvider,
    jobRecord: DurableJobRecord,
) -> None:
    """Execute one durable job type using the same deterministic runtime services."""
    if jobRecord.jobType == "ingestion.text":
        request = IngestTextRequest.model_validate(jobRecord.payload)
        ingestionService = IngestionService(
            repository=PostgresIngestionRepository(session),
            embeddingProvider=modelProvider,
            batchSize=50,
        )
        await ingestionService.ingestText(
            enterpriseId=request.enterpriseId,
            documentId=request.documentId,
            documentTitle=request.documentTitle,
            versionLabel=request.versionLabel,
            content=request.content,
            config=ChunkerConfig(size=request.chunkSize, overlap=request.chunkOverlap),
            sourceUri=request.sourceUri,
            principalIds=tuple(request.principalIds),
            sourceAuthority=request.sourceAuthority,
            extractionQuality=request.extractionQuality,
            publishedAt=parseOptionalIsoTimestamp(request.publishedAt),
            metadata=request.metadata,
        )
        return
    if jobRecord.jobType == "ingestion.source":
        await processSourceIngestionJob(session, settings, modelProvider, jobRecord.payload)
        return
    if jobRecord.jobType == "retention.redact":
        await redactExpiredRawContent(session, datetime.now(UTC))
        return
    if jobRecord.jobType == "retention.purge":
        await purgeExpiredTraces(session, datetime.now(UTC))
        return
    raise ValueError(f"unsupported job type: {jobRecord.jobType}")


async def processSourceIngestionJob(
    session: AsyncSession,
    settings: Settings,
    modelProvider: OllamaModelProvider,
    payload: dict[str, Any],
) -> None:
    """Parse, scan, and deterministically ingest one persisted source object."""
    jobPayload = SourceIngestionJobPayload.model_validate(payload)
    rawHash = bytes.fromhex(jobPayload.rawSha256)
    repository = PostgresIngestionRepository(session)
    objectStorage = LocalObjectStorage(Path(settings.objectStorageRoot))
    malwareScanner = NoOpMalwareScanner()
    parserRegistry = ParserRegistry(settings)

    content = await objectStorage.getObject(jobPayload.objectKey)
    scanResult = await malwareScanner.scanBytes(content, jobPayload.fileName, jobPayload.mimeType)
    if scanResult.status != "clean":
        await _markVersionFailure(
            session=session,
            versionId=jobPayload.versionId,
            failureCode="MALWARE_QUARANTINED",
            failureDetail=scanResult.detail,
            quarantineStatus="quarantined",
            malwareStatus=scanResult.status,
        )
        raise ValueError(scanResult.detail)

    await _markVersionProcessing(
        session=session,
        versionId=jobPayload.versionId,
        malwareStatus=scanResult.status,
    )
    try:
        parsedDocument = await parserRegistry.parseBytes(
            content=content,
            mimeType=jobPayload.mimeType,
            fileName=jobPayload.fileName,
        )
        ingestionService = IngestionService(
            repository=repository,
            embeddingProvider=modelProvider,
            batchSize=50,
        )
        await ingestionService.ingestText(
            enterpriseId=jobPayload.enterpriseId,
            documentId=jobPayload.documentId,
            documentTitle=jobPayload.displayName,
            versionLabel=jobPayload.versionLabel,
            content=parsedDocument.content,
            config=ChunkerConfig(size=900, overlap=120),
            sourceUri=jobPayload.sourceUri,
            principalIds=tuple(jobPayload.principalIds),
            sourceAuthority=jobPayload.sourceAuthority,
            extractionQuality=jobPayload.extractionQuality,
            publishedAt=parseOptionalIsoTimestamp(jobPayload.publishedAt),
            metadata=jobPayload.metadata,
            documentMetadata=SourceDocumentMetadata(
                sourceType=jobPayload.sourceType,
                displayName=jobPayload.displayName,
                createdBy=jobPayload.actorId,
            ),
            versionMetadata=SourceVersionMetadata(
                versionSeedHash=rawHash,
                rawHash=rawHash,
                canonicalHash=calculateCanonicalContentHash(parsedDocument.content),
                mimeType=jobPayload.mimeType,
                objectKey=jobPayload.objectKey,
                parserName=parsedDocument.parserName,
                parserVersion=parsedDocument.parserVersion,
                extractionDiagnostics={
                    **parsedDocument.extractionDiagnostics,
                    "fileName": jobPayload.fileName,
                },
                acceleratorReports=tuple(
                    {
                        "actualDevice": report.actualDevice,
                        "isStrict": report.isStrict,
                        "requiredDevice": report.requiredDevice,
                        "stageName": report.stageName,
                    }
                    for report in parsedDocument.acceleratorReports
                ),
                malwareStatus=scanResult.status,
                quarantineStatus="clear",
                ingestionStatus="processing",
            ),
        )
    except Exception as error:
        await _markVersionFailure(
            session=session,
            versionId=jobPayload.versionId,
            failureCode="SOURCE_PARSE_FAILED",
            failureDetail=str(error),
            quarantineStatus="quarantined",
            malwareStatus=scanResult.status,
        )
        raise


async def _markVersionProcessing(
    session: AsyncSession,
    versionId: UUID,
    malwareStatus: str,
) -> None:
    """Record that a queued source version has started scanning and parsing."""
    try:
        await session.execute(
            text(
                """
                UPDATE document_version
                SET ingestion_status = 'processing',
                    malware_status = :malware_status
                WHERE id = :version_id
                """
            ),
            {"version_id": versionId, "malware_status": malwareStatus},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def _markVersionFailure(
    session: AsyncSession,
    versionId: UUID,
    failureCode: str,
    failureDetail: str,
    quarantineStatus: str,
    malwareStatus: str,
) -> None:
    """Persist source-version failures that happen before chunk ingestion begins."""
    try:
        await session.execute(
            text(
                """
                UPDATE document_version
                SET status = 'failed',
                    ingestion_status = 'failed',
                    quarantine_status = :quarantine_status,
                    malware_status = :malware_status,
                    failure_code = :failure_code,
                    failure_detail = :failure_detail
                WHERE id = :version_id
                """
            ),
            {
                "version_id": versionId,
                "quarantine_status": quarantineStatus,
                "malware_status": malwareStatus,
                "failure_code": failureCode[:120],
                "failure_detail": failureDetail[:4000],
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise


def buildIdempotencyKey(jobType: str, payload: dict[str, Any]) -> str:
    """Hash one payload deterministically so retries do not fan out duplicate jobs."""
    encodedPayload = json.dumps(
        {"jobType": jobType, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encodedPayload).hexdigest()


def normalizePayload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize nested payloads before hashing or persistence so retries stay stable."""
    return json.loads(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


def parseOptionalIsoTimestamp(timestampValue: str | None) -> datetime | None:
    """Parse optional ISO timestamps supplied by seeded fixtures or ingestion requests."""
    if timestampValue is None:
        return None
    return datetime.fromisoformat(timestampValue.replace("Z", "+00:00")).astimezone(UTC)
