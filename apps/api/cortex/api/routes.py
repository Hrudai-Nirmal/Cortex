"""Versioned API routes for the executable Cortex live integration baseline."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings, getSettings
from cortex.database import getDatabaseSession
from cortex.domain.chunking import ChunkerConfig
from cortex.errors import CortexError
from cortex.schemas import (
    IngestTextRequest,
    IngestTextResponse,
    PipelineGraphResponse,
    PipelineNodeSchema,
    QueryRequest,
    QueryResponse,
    QueuedJobResponse,
    RuntimeHealthResponse,
    SeedFixturesResponse,
    TraceSummaryResponse,
)
from cortex.services.ingestion import IngestionService, PostgresIngestionRepository
from cortex.services.jobs import DurableJobService
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.query import QueryService
from cortex.services.runtime import RuntimeHealthService
from cortex.services.seed import seedFixtures

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
