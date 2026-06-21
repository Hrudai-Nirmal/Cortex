"""Scoped lexical/vector SQL, bounded fusion, and deterministic reranking helpers."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.errors import AuthorizationScopeError, InputValidationError
from cortex.services.ingestion import formatVector

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

VECTOR_RETRIEVAL_SQL = """
SELECT
    c.id,
    c.normalized_content,
    c.structural_locator,
    d.title AS document_title,
    dv.version_label,
    dv.source_authority,
    dv.published_at,
    c.metadata,
    1 - (c.embedding <=> CAST(:query_embedding AS vector)) AS score
FROM chunk AS c
JOIN document_version AS dv ON dv.id = c.document_version_id
JOIN document AS d ON d.id = dv.document_id
WHERE c.enterprise_id = :enterprise_id
  AND dv.status = 'active'
  AND c.embedding IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM chunk_acl AS ca
      WHERE ca.chunk_id = c.id
        AND ca.enterprise_id = :enterprise_id
        AND ca.principal_id = ANY(CAST(:principal_ids AS text[]))
  )
ORDER BY c.embedding <=> CAST(:query_embedding AS vector)
LIMIT :candidate_limit
""".strip()

LEXICAL_RETRIEVAL_SQL = """
SELECT
    c.id,
    c.normalized_content,
    c.structural_locator,
    d.title AS document_title,
    dv.version_label,
    dv.source_authority,
    dv.published_at,
    c.metadata,
    ts_rank_cd(
        c.lexical || to_tsvector('english', d.title),
        websearch_to_tsquery('english', :query_text)
    ) AS score
FROM chunk AS c
JOIN document_version AS dv ON dv.id = c.document_version_id
JOIN document AS d ON d.id = dv.document_id
WHERE c.enterprise_id = :enterprise_id
  AND dv.status = 'active'
  AND (c.lexical || to_tsvector('english', d.title))
      @@ websearch_to_tsquery('english', :query_text)
  AND EXISTS (
      SELECT 1 FROM chunk_acl AS ca
      WHERE ca.chunk_id = c.id
        AND ca.enterprise_id = :enterprise_id
        AND ca.principal_id = ANY(CAST(:principal_ids AS text[]))
  )
ORDER BY score DESC
LIMIT :candidate_limit
""".strip()


@dataclass(frozen=True, slots=True)
class AccessScope:
    """Carry the mandatory enterprise and principal predicate into retrieval."""

    enterpriseId: UUID
    actorId: str
    principalIds: tuple[str, ...]

    def validate(self) -> None:
        """Reject empty principal closures before any retrieval operation."""
        if not self.actorId.strip():
            raise AuthorizationScopeError("actorId is required")
        if not self.principalIds or any(not principal.strip() for principal in self.principalIds):
            raise AuthorizationScopeError("at least one non-empty ACL principal is required")

    def toSqlParameters(self) -> dict[str, object]:
        """Return parameters that must accompany every retrieval SQL statement."""
        self.validate()
        return {
            "enterprise_id": self.enterpriseId,
            "principal_ids": list(self.principalIds),
        }


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """Represent one candidate and its fused reciprocal rank score."""

    chunkId: str
    content: str
    score: float
    structuralLocator: str = ""
    documentTitle: str = ""
    documentVersion: str = ""
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """Carry full provenance and final ranking values for answer validation."""

    chunkId: str
    content: str
    structuralLocator: str
    documentTitle: str
    documentVersion: str
    fusedScore: float
    rerankScore: float
    sourceScore: float
    supportScore: float
    publishedAt: datetime | None
    metadata: dict[str, Any]


def fuseReciprocalRanks(
    lexicalCandidates: list[RankedCandidate],
    vectorCandidates: list[RankedCandidate],
    rerankTopK: int = 40,
    rankConstant: int = 60,
) -> list[RankedCandidate]:
    """Fuse two rankings and strictly truncate before cross-encoder reranking."""
    if rerankTopK < 30 or rerankTopK > 50:
        raise InputValidationError("rerankTopK must stay within the validated 30-50 range")
    if rankConstant < 1:
        raise InputValidationError("rankConstant must be positive")
    candidateContent: dict[str, RankedCandidate] = {}
    fusedScores: dict[str, float] = {}
    for candidateList in (lexicalCandidates, vectorCandidates):
        for rank, candidate in enumerate(candidateList, start=1):
            candidateContent[candidate.chunkId] = candidate
            fusedScores[candidate.chunkId] = fusedScores.get(candidate.chunkId, 0.0) + (
                1.0 / (rankConstant + rank)
            )
    fusedCandidates = [
        RankedCandidate(
            chunkId=chunkId,
            content=candidateContent[chunkId].content,
            score=score,
            structuralLocator=candidateContent[chunkId].structuralLocator,
            documentTitle=candidateContent[chunkId].documentTitle,
            documentVersion=candidateContent[chunkId].documentVersion,
            metadata=candidateContent[chunkId].metadata,
        )
        for chunkId, score in fusedScores.items()
    ]
    return sorted(fusedCandidates, key=lambda candidate: candidate.score, reverse=True)[:rerankTopK]


class PostgresRetrievalService:
    """Run scoped hybrid retrieval and deterministic reranking against PostgreSQL."""

    def __init__(
        self,
        session: AsyncSession,
        candidateLimit: int,
        rerankTopK: int,
        sourceConfidenceThreshold: float,
    ) -> None:
        if session is None:
            raise ValueError("session is required")
        self.session = session
        self.candidateLimit = candidateLimit
        self.rerankTopK = rerankTopK
        self.sourceConfidenceThreshold = sourceConfidenceThreshold

    async def retrieve(
        self,
        queryText: str,
        queryEmbedding: list[float],
        accessScope: AccessScope,
    ) -> list[RetrievedChunk]:
        """Run SQL-scoped retrieval, fuse, rerank, and filter low-confidence evidence."""
        if not queryText.strip():
            raise InputValidationError("queryText cannot be empty")
        queryParameters = accessScope.toSqlParameters()
        lexicalCandidates = await self._runLexicalQuery(queryText, queryParameters)
        vectorCandidates = await self._runVectorQuery(queryEmbedding, queryParameters)
        fusedCandidates = fuseReciprocalRanks(
            lexicalCandidates,
            vectorCandidates,
            rerankTopK=self.rerankTopK,
        )
        rerankedChunks = [
            self._rerankCandidate(queryText, candidate) for candidate in fusedCandidates
        ]
        filteredChunks = [
            candidate
            for candidate in sorted(
                rerankedChunks,
                key=lambda item: item.supportScore,
                reverse=True,
            )
            if candidate.supportScore >= self.sourceConfidenceThreshold
        ]
        if filteredChunks or not rerankedChunks:
            return filteredChunks
        if not lexicalCandidates:
            return []
        highestConfidenceChunk = max(
            rerankedChunks,
            key=lambda candidate: candidate.supportScore,
        )
        return [highestConfidenceChunk]

    async def _runLexicalQuery(
        self,
        queryText: str,
        queryParameters: dict[str, object],
    ) -> list[RankedCandidate]:
        result = await self.session.execute(
            text(LEXICAL_RETRIEVAL_SQL),
            {
                **queryParameters,
                "query_text": queryText,
                "candidate_limit": self.candidateLimit,
            },
        )
        return [self._rowToRankedCandidate(row) for row in result.mappings().all()]

    async def _runVectorQuery(
        self,
        queryEmbedding: list[float],
        queryParameters: dict[str, object],
    ) -> list[RankedCandidate]:
        result = await self.session.execute(
            text(VECTOR_RETRIEVAL_SQL),
            {
                **queryParameters,
                "query_embedding": formatVector(queryEmbedding),
                "candidate_limit": self.candidateLimit,
            },
        )
        return [self._rowToRankedCandidate(row) for row in result.mappings().all()]

    def _rowToRankedCandidate(self, row: Any) -> RankedCandidate:
        metadataValue = row["metadata"] if isinstance(row["metadata"], dict) else {}
        return RankedCandidate(
            chunkId=bytes(row["id"]).hex(),
            content=row["normalized_content"],
            score=float(row["score"] or 0.0),
            structuralLocator=row["structural_locator"],
            documentTitle=row["document_title"],
            documentVersion=row["version_label"],
            metadata={
                **metadataValue,
                "publishedAt": normalizeTimestamp(row["published_at"]),
                "sourceAuthority": float(row["source_authority"] or 0.0),
            },
        )

    def _rerankCandidate(self, queryText: str, candidate: RankedCandidate) -> RetrievedChunk:
        queryTokens = set(TOKEN_PATTERN.findall(queryText.lower()))
        contentTokens = set(TOKEN_PATTERN.findall(candidate.content.lower()))
        titleTokens = set(TOKEN_PATTERN.findall(candidate.documentTitle.lower()))
        tokenRecall = len(queryTokens & contentTokens) / len(queryTokens) if queryTokens else 0.0
        titleBoost = 0.2 if queryTokens & titleTokens else 0.0
        rerankScore = min(1.0, candidate.score + tokenRecall + titleBoost)
        metadataValue = candidate.metadata or {}
        sourceAuthority = float(metadataValue.get("sourceAuthority", 0.0))
        extractionQuality = float(metadataValue.get("extractionQuality", 0.85))
        publishedAt = parseTimestamp(metadataValue.get("publishedAt"))
        freshnessScore = calculateFreshnessScore(publishedAt)
        sourceScore = min(
            1.0,
            (0.45 * sourceAuthority) + (0.25 * extractionQuality) + (0.30 * freshnessScore),
        )
        supportScore = min(
            1.0,
            (0.45 * rerankScore) + (0.35 * sourceScore) + (0.20 * candidate.score),
        )
        return RetrievedChunk(
            chunkId=candidate.chunkId,
            content=candidate.content,
            structuralLocator=candidate.structuralLocator,
            documentTitle=candidate.documentTitle,
            documentVersion=candidate.documentVersion,
            fusedScore=candidate.score,
            rerankScore=rerankScore,
            sourceScore=sourceScore,
            supportScore=supportScore,
            publishedAt=publishedAt,
            metadata=metadataValue,
        )


def calculateFreshnessScore(publishedAt: datetime | None, now: datetime | None = None) -> float:
    """Convert recency into a bounded freshness score for authority blending."""
    if publishedAt is None:
        return 0.5
    comparisonTime = now or datetime.now(UTC)
    ageDays = max(0.0, (comparisonTime - publishedAt.astimezone(UTC)).total_seconds() / 86400.0)
    return max(0.1, min(1.0, math.exp(-ageDays / 365.0)))


def parseTimestamp(timestampValue: Any) -> datetime | None:
    """Parse timestamps from SQL rows or metadata without widening accepted formats."""
    if timestampValue is None:
        return None
    if isinstance(timestampValue, datetime):
        return timestampValue.astimezone(UTC)
    if isinstance(timestampValue, str):
        normalizedValue = timestampValue.replace("Z", "+00:00")
        return datetime.fromisoformat(normalizedValue).astimezone(UTC)
    raise InputValidationError("unsupported timestamp value")


def normalizeTimestamp(timestampValue: datetime | None) -> str | None:
    """Serialize timestamps consistently for persisted JSON payloads."""
    if timestampValue is None:
        return None
    return timestampValue.astimezone(UTC).isoformat()
