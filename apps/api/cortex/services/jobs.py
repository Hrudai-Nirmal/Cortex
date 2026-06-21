"""PostgreSQL-backed durable job queue for worker-driven ingestion and retention work."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings
from cortex.domain.chunking import ChunkerConfig
from cortex.schemas import IngestTextRequest
from cortex.services.ingestion import IngestionService, PostgresIngestionRepository
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.retention import purgeExpiredTraces, redactExpiredRawContent


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
        """Persist a worker-executed ingestion request under a deterministic idempotency key."""
        serializedPayload = request.model_dump(mode="json")
        idempotencyKey = buildIdempotencyKey("ingestion.text", serializedPayload)
        jobId = uuid4()
        try:
            await self.session.execute(
                text(
                    """
                    INSERT INTO enterprise (id, name)
                    VALUES (:enterprise_id, 'Cortex Enterprise')
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"enterprise_id": request.enterpriseId},
            )
            await self.session.execute(
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
                    """
                ),
                {
                    "job_id": jobId,
                    "enterprise_id": request.enterpriseId,
                    "job_type": "ingestion.text",
                    "idempotency_key": idempotencyKey,
                    "payload": json.dumps(serializedPayload, sort_keys=True, separators=(",", ":")),
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return jobId

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
    if jobRecord.jobType == "retention.redact":
        await redactExpiredRawContent(session, datetime.now(UTC))
        return
    if jobRecord.jobType == "retention.purge":
        await purgeExpiredTraces(session, datetime.now(UTC))
        return
    raise ValueError(f"unsupported job type: {jobRecord.jobType}")


def buildIdempotencyKey(jobType: str, payload: dict[str, Any]) -> str:
    """Hash one payload deterministically so retries do not fan out duplicate jobs."""
    encodedPayload = json.dumps(
        {"jobType": jobType, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encodedPayload).hexdigest()


def parseOptionalIsoTimestamp(timestampValue: str | None) -> datetime | None:
    """Parse optional ISO timestamps supplied by seeded fixtures or ingestion requests."""
    if timestampValue is None:
        return None
    return datetime.fromisoformat(timestampValue.replace("Z", "+00:00")).astimezone(UTC)
