"""Deterministic fixture seeding for the live integration development baseline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings
from cortex.domain.chunking import ChunkerConfig
from cortex.schemas import AccessScopeSchema, QueryRequest, SeedFixturesResponse
from cortex.services.ingestion import IngestionService, PostgresIngestionRepository
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.query import QueryService

SECOND_ENTERPRISE_ID = UUID("00000000-0000-0000-0000-000000000002")


@dataclass(frozen=True, slots=True)
class SeedDocument:
    """Describe one deterministic document fixture and its authorization scope."""

    documentId: UUID
    documentTitle: str
    versionLabel: str
    sourceUri: str
    content: str
    principalIds: tuple[str, ...]
    publishedAt: datetime | None = None
    sourceAuthority: float = 0.85
    extractionQuality: float = 0.9
    enterpriseId: UUID | None = None


DEFAULT_CHUNKER = ChunkerConfig(size=700, overlap=100)


def buildSeedDocuments(settings: Settings) -> tuple[SeedDocument, ...]:
    """Return the stable fixture corpus used by tests and local operator flows."""
    return (
        SeedDocument(
            documentId=UUID("10000000-0000-0000-0000-000000000001"),
            documentTitle="Cortex Retention Standard",
            versionLabel="1.3",
            sourceUri="seed://retention-standard",
            publishedAt=datetime(2024, 3, 1, tzinfo=UTC),
            sourceAuthority=0.7,
            content=(
                "Raw query content is retained for 45 days. Detailed traces are retained for "
                "120 days. Audit metadata is retained for 400 days."
            ),
            principalIds=("group:employees", "role:builder", "role:auditor"),
        ),
        SeedDocument(
            documentId=UUID("10000000-0000-0000-0000-000000000001"),
            documentTitle="Cortex Retention Standard",
            versionLabel="1.4",
            sourceUri="seed://retention-standard",
            publishedAt=datetime(2026, 1, 12, tzinfo=UTC),
            sourceAuthority=0.95,
            content=(
                "Raw query and response content is retained for 30 days. Detailed traces are "
                "retained for 90 days. Content-free audit metadata is retained for 365 days."
            ),
            principalIds=("group:employees", "role:builder", "role:auditor"),
        ),
        SeedDocument(
            documentId=UUID("10000000-0000-0000-0000-000000000002"),
            documentTitle="Enterprise Data Handling Policy",
            versionLabel="3.2",
            sourceUri="seed://data-handling-policy",
            publishedAt=datetime(2026, 2, 4, tzinfo=UTC),
            sourceAuthority=0.93,
            content=(
                "Customer documents remain inside the dedicated enterprise deployment. Access is "
                "evaluated against the requesting user's current group and document ACL "
                "before retrieval."
            ),
            principalIds=("group:employees", "role:builder"),
        ),
        SeedDocument(
            documentId=UUID("10000000-0000-0000-0000-000000000003"),
            documentTitle="Pipeline Promotion Policy",
            versionLabel="2.0",
            sourceUri="seed://pipeline-promotion-policy",
            publishedAt=datetime(2026, 2, 9, tzinfo=UTC),
            sourceAuthority=0.92,
            content=(
                "A pipeline version must pass retrieval, citation, hallucination, latency, and "
                "access isolation gates before an administrator can promote it to active."
            ),
            principalIds=("role:builder", "role:auditor"),
        ),
        SeedDocument(
            documentId=UUID("10000000-0000-0000-0000-000000000004"),
            documentTitle="Revenue Worksheet",
            versionLabel="2026-Q1",
            sourceUri="seed://revenue-worksheet",
            publishedAt=datetime(2026, 4, 1, tzinfo=UTC),
            sourceAuthority=0.9,
            content=(
                "The revenue worksheet values are 18, 27, and 45. These values are approved for "
                "quarter one planning."
            ),
            principalIds=("group:employees", "role:builder"),
        ),
        SeedDocument(
            documentId=UUID("10000000-0000-0000-0000-000000000005"),
            documentTitle="Support Escalation Runbook",
            versionLabel="2026.05",
            sourceUri="seed://support-escalation-runbook",
            publishedAt=datetime(2026, 5, 18, tzinfo=UTC),
            sourceAuthority=0.94,
            content=(
                "The current support escalation window is 24 hours for standard enterprise "
                "incidents."
            ),
            principalIds=("group:employees", "role:builder"),
        ),
        SeedDocument(
            documentId=UUID("10000000-0000-0000-0000-000000000006"),
            documentTitle="Legacy Support Bulletin",
            versionLabel="2024.01",
            sourceUri="seed://legacy-support-bulletin",
            publishedAt=datetime(2024, 1, 6, tzinfo=UTC),
            sourceAuthority=0.52,
            content=("The support escalation window is 48 hours for standard incidents."),
            principalIds=("group:employees", "role:builder"),
        ),
        SeedDocument(
            documentId=UUID("10000000-0000-0000-0000-000000000007"),
            documentTitle="HR Compensation Review",
            versionLabel="2026.01",
            sourceUri="seed://hr-compensation-review",
            publishedAt=datetime(2026, 1, 21, tzinfo=UTC),
            sourceAuthority=0.88,
            content="This HR-only review contains salary planning notes.",
            principalIds=("group:hr",),
        ),
        SeedDocument(
            documentId=UUID("20000000-0000-0000-0000-000000000001"),
            documentTitle="Second Enterprise Private Handbook",
            versionLabel="1.0",
            sourceUri="seed://second-enterprise-handbook",
            publishedAt=datetime(2026, 2, 2, tzinfo=UTC),
            enterpriseId=SECOND_ENTERPRISE_ID,
            sourceAuthority=0.9,
            content=(
                "This handbook belongs to a different enterprise and must never leak across scope."
            ),
            principalIds=("group:employees",),
        ),
    )


async def seedFixtures(
    session: AsyncSession,
    settings: Settings,
    modelProvider: OllamaModelProvider,
) -> SeedFixturesResponse:
    """Seed the deterministic fixture corpus and produce a couple of developer traces."""
    ingestionService = IngestionService(
        repository=PostgresIngestionRepository(session),
        embeddingProvider=modelProvider,
        batchSize=50,
    )
    queryService = QueryService(session=session, settings=settings, modelProvider=modelProvider)
    seededEnterpriseIds: set[UUID] = set()
    for seedDocument in buildSeedDocuments(settings):
        await ingestionService.ingestText(
            enterpriseId=seedDocument.enterpriseId or settings.enterpriseId,
            documentId=seedDocument.documentId,
            documentTitle=seedDocument.documentTitle,
            versionLabel=seedDocument.versionLabel,
            content=seedDocument.content,
            config=DEFAULT_CHUNKER,
            sourceUri=seedDocument.sourceUri,
            principalIds=seedDocument.principalIds,
            sourceAuthority=seedDocument.sourceAuthority,
            extractionQuality=seedDocument.extractionQuality,
            publishedAt=seedDocument.publishedAt,
            metadata={"fixture": True},
        )
        seededEnterpriseIds.add(seedDocument.enterpriseId or settings.enterpriseId)
    traceCount = 0
    for queryText in (
        "What are our retentin rules?",
        "What is the total from the revenue worksheet values?",
    ):
        await queryService.answerQuery(
            QueryRequest(
                query=queryText,
                accessScope=AccessScopeSchema(
                    enterpriseId=settings.enterpriseId,
                    actorId="maya.chen@example.com",
                    principalIds=["group:employees"],
                ),
            )
        )
        traceCount += 1
    return SeedFixturesResponse(
        seededDocuments=len(buildSeedDocuments(settings)),
        enterprises=sorted(seededEnterpriseIds, key=str),
        traceCount=traceCount,
    )
