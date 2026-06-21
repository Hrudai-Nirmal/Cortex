"""Versioned API routes for the executable Cortex live integration baseline."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings, getSettings
from cortex.database import getDatabaseSession
from cortex.domain.chunking import ChunkerConfig
from cortex.errors import CortexError
from cortex.schemas import (
    CreateUploadSourceResponse,
    CreateWebsiteSourceRequest,
    CreateWebsiteSourceResponse,
    IngestTextRequest,
    IngestTextResponse,
    JobStatusResponse,
    JobSummaryResponse,
    PipelineGraphResponse,
    PipelineNodeSchema,
    QueryRequest,
    QueryResponse,
    QueuedJobResponse,
    RuntimeHealthResponse,
    SeedFixturesResponse,
    SourceDetailResponse,
    SourceSummaryResponse,
    TraceSummaryResponse,
)
from cortex.services.ingestion import IngestionService, PostgresIngestionRepository
from cortex.services.jobs import DurableJobService
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.object_storage import LocalObjectStorage
from cortex.services.query import QueryService
from cortex.services.runtime import RuntimeHealthService
from cortex.services.seed import seedFixtures
from cortex.services.sources import SourceService

router = APIRouter()
settings = getSettings()
DatabaseSession = Annotated[AsyncSession, Depends(getDatabaseSession)]


def buildModelProvider(activeSettings: Settings) -> OllamaModelProvider:
    """Create the configured local model provider for request-scoped services."""
    return OllamaModelProvider(
        baseUrl=activeSettings.ollamaBaseUrl,
        generatorModel=activeSettings.generatorModel,
        embeddingModel=activeSettings.embeddingModel,
    )


def buildSourceService(session: AsyncSession) -> SourceService:
    """Create the live source operations service backed by local object storage."""
    return SourceService(
        session=session,
        settings=settings,
        objectStorage=LocalObjectStorage(Path(settings.objectStorageRoot)),
    )


@router.get("/health/live")
async def getLiveness() -> dict[str, str]:
    """Report process liveness without touching external dependencies."""
    return {"status": "live"}


@router.get("/health/ready", response_model=RuntimeHealthResponse)
async def getReadiness(session: DatabaseSession) -> RuntimeHealthResponse:
    """Report actual runtime readiness across the live local stack components."""
    runtimeHealthService = RuntimeHealthService(
        session=session,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    return await runtimeHealthService.getReadiness()


@router.post("/v1/ingestion/text", response_model=IngestTextResponse)
async def ingestText(
    request: IngestTextRequest,
    session: DatabaseSession,
) -> IngestTextResponse:
    """Ingest text through deterministic chunking, embeddings, and idempotent activation."""
    try:
        ingestionService = IngestionService(
            repository=PostgresIngestionRepository(session),
            embeddingProvider=buildModelProvider(settings),
        )
        ingestionResult = await ingestionService.ingestText(
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
            publishedAt=parseOptionalTimestamp(request.publishedAt),
            metadata=request.metadata,
        )
    except CortexError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ingestion failed"
        ) from error
    return IngestTextResponse(
        documentVersionId=ingestionResult.documentVersionId,
        documentVersionHash=ingestionResult.documentVersionHash,
        chunkCount=ingestionResult.chunkCount,
        chunkIds=list(ingestionResult.chunkIds),
        status=ingestionResult.status,
    )


@router.post("/v1/ingestion/jobs/text", response_model=QueuedJobResponse)
async def enqueueTextIngestionJob(
    request: IngestTextRequest,
    session: DatabaseSession,
) -> QueuedJobResponse:
    """Queue ingestion for the durable worker instead of processing inline."""
    try:
        jobService = DurableJobService(session)
        jobId = await jobService.enqueueIngestionJob(request)
    except CortexError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job enqueue failed"
        ) from error
    return QueuedJobResponse(jobId=jobId, status="queued")


@router.post("/v1/sources/uploads", response_model=CreateUploadSourceResponse)
async def createUploadSource(
    enterpriseId: Annotated[UUID, Form()],
    actorId: Annotated[str, Form()],
    displayName: Annotated[str, Form()],
    versionLabel: Annotated[str, Form()],
    principalIds: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    session: DatabaseSession,
    documentId: Annotated[UUID | None, Form()] = None,
    sourceAuthority: Annotated[float, Form()] = 0.85,
    extractionQuality: Annotated[float, Form()] = 0.9,
    publishedAt: Annotated[str | None, Form()] = None,
    metadata: Annotated[str | None, Form()] = None,
) -> CreateUploadSourceResponse:
    """Accept a file upload, store it once by hash, and queue deterministic ingestion."""
    if file.content_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="uploaded file is missing its content type",
        )
    try:
        rawContent = await file.read()
        sourceService = buildSourceService(session)
        return await sourceService.createUploadSource(
            enterpriseId=enterpriseId,
            actorId=actorId,
            displayName=displayName,
            versionLabel=versionLabel,
            principalIds=parsePrincipalIds(principalIds),
            fileName=file.filename or "upload.bin",
            mimeType=file.content_type,
            content=rawContent,
            documentId=documentId,
            sourceAuthority=sourceAuthority,
            extractionQuality=extractionQuality,
            publishedAt=parseOptionalTimestamp(publishedAt),
            metadata=parseOptionalMetadata(metadata),
        )
    except CortexError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"source upload failed: {error}",
        ) from error


@router.post("/v1/sources/website", response_model=CreateWebsiteSourceResponse)
async def createWebsiteSource(
    request: CreateWebsiteSourceRequest,
    session: DatabaseSession,
) -> CreateWebsiteSourceResponse:
    """Fetch one allowlisted page, persist its snapshot, and queue deterministic ingestion."""
    try:
        sourceService = buildSourceService(session)
        return await sourceService.createWebsiteSource(request)
    except CortexError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"website source failed: {error}",
        ) from error


@router.get("/v1/sources", response_model=list[SourceSummaryResponse])
async def listSources(
    enterpriseId: UUID,
    session: DatabaseSession,
) -> list[SourceSummaryResponse]:
    """Return the developer source inventory with the latest version status for each source."""
    sourceService = buildSourceService(session)
    return await sourceService.listSources(enterpriseId)


@router.get("/v1/sources/{documentId}", response_model=SourceDetailResponse)
async def getSourceDetail(
    documentId: UUID,
    enterpriseId: UUID,
    session: DatabaseSession,
) -> SourceDetailResponse:
    """Return one source record plus its ordered version history."""
    sourceService = buildSourceService(session)
    try:
        return await sourceService.getSourceDetail(enterpriseId, documentId)
    except CortexError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/v1/jobs", response_model=list[JobSummaryResponse])
async def listJobs(
    enterpriseId: UUID,
    session: DatabaseSession,
) -> list[JobSummaryResponse]:
    """Return the newest durable jobs for the developer jobs panel."""
    sourceService = buildSourceService(session)
    return await sourceService.listJobs(enterpriseId)


@router.get("/v1/jobs/{jobId}", response_model=JobStatusResponse)
async def getJobStatus(
    jobId: UUID,
    session: DatabaseSession,
) -> JobStatusResponse:
    """Return one persisted durable job row for polling and failure inspection."""
    sourceService = buildSourceService(session)
    jobStatus = await sourceService.getJobStatus(jobId)
    if jobStatus is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return jobStatus


@router.post("/v1/query", response_model=QueryResponse)
async def submitQuery(
    request: QueryRequest,
    session: DatabaseSession,
) -> QueryResponse:
    """Execute the fixed query route and return only validated claims."""
    try:
        queryService = QueryService(
            session=session,
            settings=settings,
            modelProvider=buildModelProvider(settings),
        )
        return await queryService.answerQuery(request)
    except CortexError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="query failed"
        ) from error


@router.get("/v1/query/{traceId}/events")
async def streamQueryEvents(
    traceId: UUID,
    request: Request,
    session: DatabaseSession,
) -> StreamingResponse:
    """Stream persisted stage-level progress without exposing unvalidated answer tokens."""
    queryService = QueryService(
        session=session,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    traceSummary = await queryService.getTrace(traceId)
    if traceSummary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")

    async def generateEvents():
        try:
            for stageEvent in traceSummary.stageEvents:
                if await request.is_disconnected():
                    return
                yield (f"event: stage\ndata: {json.dumps(stageEvent.model_dump(mode='json'))}\n\n")
                await asyncio.sleep(0.12)
            if await request.is_disconnected():
                return
            yield f"event: complete\ndata: {json.dumps({'traceId': str(traceId)})}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(generateEvents(), media_type="text/event-stream")


@router.get("/v1/traces/latest", response_model=TraceSummaryResponse | None)
async def getLatestTrace(
    enterpriseId: UUID,
    session: DatabaseSession,
) -> TraceSummaryResponse | None:
    """Return the latest trace for the developer console trace timeline."""
    queryService = QueryService(
        session=session,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    return await queryService.getLatestTrace(enterpriseId)


@router.get("/v1/traces/{traceId}", response_model=TraceSummaryResponse)
async def getTrace(traceId: UUID, session: DatabaseSession) -> TraceSummaryResponse:
    """Return one persisted trace and its exact stage timeline."""
    queryService = QueryService(
        session=session,
        settings=settings,
        modelProvider=buildModelProvider(settings),
    )
    traceSummary = await queryService.getTrace(traceId)
    if traceSummary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")
    return traceSummary


@router.post("/v1/dev/seed", response_model=SeedFixturesResponse)
async def seedDevelopmentFixtures(session: DatabaseSession) -> SeedFixturesResponse:
    """Seed a deterministic fixture corpus for the live integration baseline."""
    try:
        return await seedFixtures(session, settings, buildModelProvider(settings))
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"fixture seeding failed: {error}",
        ) from error


@router.get("/v1/pipelines/active", response_model=PipelineGraphResponse)
async def getActivePipeline() -> PipelineGraphResponse:
    """Return the immutable graph rendered by the developer console."""
    nodes = [
        ("ingest", "Ingest & Normalize", "ingestion", "1.1.0"),
        ("authorize", "Access Scope", "security", "1.0.0"),
        ("retrieve", "Hybrid Retrieval", "retrieval", "1.3.0"),
        ("rerank", "Cross-Encoder", "reranking", "1.1.0"),
        ("score", "Source Confidence", "scoring", "1.1.0"),
        ("generate", "Bounded Generation", "generation", "1.1.0"),
        ("validate", "Claims & Citations", "validation", "1.1.0"),
    ]
    return PipelineGraphResponse(
        name="Enterprise evidence pipeline",
        version=settings.pipelineVersion,
        status="active",
        rerankTopK=settings.rerankTopK,
        nodes=[
            PipelineNodeSchema(
                id=nodeId,
                label=label,
                category=category,
                status="healthy",
                version=version,
                config={"required": True},
            )
            for nodeId, label, category, version in nodes
        ],
        edges=[
            {"source": nodes[index][0], "target": nodes[index + 1][0]}
            for index in range(len(nodes) - 1)
        ],
    )


def parseOptionalTimestamp(timestampValue: str | None) -> datetime | None:
    """Parse optional ISO timestamps supplied through the ingestion API."""
    if timestampValue is None:
        return None
    return datetime.fromisoformat(timestampValue.replace("Z", "+00:00")).astimezone(UTC)


def parsePrincipalIds(rawPrincipalIds: str) -> list[str]:
    """Parse principals supplied through multipart forms as JSON or comma-separated text."""
    normalizedValue = rawPrincipalIds.strip()
    if not normalizedValue:
        raise ValueError("principalIds cannot be empty")
    if normalizedValue.startswith("["):
        parsedValue = json.loads(normalizedValue)
        if not isinstance(parsedValue, list):
            raise ValueError("principalIds JSON must be a list")
        return [str(principalId) for principalId in parsedValue]
    return [
        principalId.strip()
        for principalId in normalizedValue.split(",")
        if principalId.strip()
    ]


def parseOptionalMetadata(rawMetadata: str | None) -> dict[str, object]:
    """Parse optional metadata supplied through multipart forms as a JSON object."""
    if rawMetadata is None or not rawMetadata.strip():
        return {}
    parsedMetadata = json.loads(rawMetadata)
    if not isinstance(parsedMetadata, dict):
        raise ValueError("metadata must be a JSON object")
    return {str(key): value for key, value in parsedMetadata.items()}
