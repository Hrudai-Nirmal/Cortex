"""Content-free audit hashing and independent trace identity preservation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings
from cortex.domain.chunking import serializeCanonicalJson
from cortex.models import AuditLog


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Represent the immutable payload whose hash excludes the nullable trace pointer."""

    id: UUID
    enterpriseId: UUID
    traceMemoryId: UUID | None
    traceIdentifierHash: bytes
    actorId: str
    action: str
    scope: dict[str, Any]
    outcome: str
    createdAt: datetime
    eventHash: bytes


def calculateTraceIdentifierHash(traceId: UUID) -> bytes:
    """Preserve correlation after sensitive trace payload deletion."""
    return hashlib.sha256(traceId.bytes).digest()


def calculateAuditEventHash(
    eventId: UUID,
    enterpriseId: UUID,
    traceIdentifierHash: bytes,
    actorId: str,
    action: str,
    scope: dict[str, Any],
    outcome: str,
    createdAt: datetime,
) -> bytes:
    """Hash only immutable content-free audit fields."""
    canonicalPayload = {
        "action": action,
        "actorId": actorId,
        "createdAt": createdAt.astimezone(UTC).isoformat(),
        "enterpriseId": str(enterpriseId),
        "eventId": str(eventId),
        "outcome": outcome,
        "scope": scope,
        "traceIdentifierHash": traceIdentifierHash.hex(),
    }
    return hashlib.sha256(serializeCanonicalJson(canonicalPayload)).digest()


async def persistControlPlaneAudit(
    *,
    session: AsyncSession,
    settings: Settings,
    enterpriseId: UUID,
    actorId: str,
    action: str,
    scope: dict[str, Any],
    outcome: str,
    eventPayload: dict[str, Any],
    traceMemoryId: UUID | None = None,
    pipelineVersion: int | None = None,
    modelVersions: dict[str, str] | None = None,
    createdAt: datetime | None = None,
) -> AuditEvent:
    """Persist one non-query audit record without coupling it to trace retention."""
    auditCreatedAt = (createdAt or datetime.now(UTC)).astimezone(UTC)
    await session.execute(
        text(
            """
            INSERT INTO enterprise (id, name)
            VALUES (:enterprise_id, 'Cortex Enterprise')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"enterprise_id": enterpriseId},
    )
    traceCorrelationId = traceMemoryId or uuid4()
    traceIdentifierHash = calculateTraceIdentifierHash(traceCorrelationId)
    auditEventId = uuid4()
    eventHash = calculateAuditEventHash(
        eventId=auditEventId,
        enterpriseId=enterpriseId,
        traceIdentifierHash=traceIdentifierHash,
        actorId=actorId,
        action=action,
        scope=scope,
        outcome=outcome,
        createdAt=auditCreatedAt,
    )
    auditRecord = AuditLog(
        id=auditEventId,
        enterpriseId=enterpriseId,
        traceMemoryId=traceMemoryId,
        traceIdentifierHash=traceIdentifierHash,
        actorId=actorId,
        action=action,
        scope=scope,
        pipelineVersion=pipelineVersion,
        modelVersions=modelVersions or {},
        outcome=outcome,
        eventPayload=eventPayload,
        eventHash=eventHash,
        createdAt=auditCreatedAt,
        expiresAt=auditCreatedAt + timedelta(days=settings.auditRetentionDays),
    )
    session.add(auditRecord)
    await session.flush()
    return AuditEvent(
        id=auditRecord.id,
        enterpriseId=auditRecord.enterpriseId,
        traceMemoryId=auditRecord.traceMemoryId,
        traceIdentifierHash=auditRecord.traceIdentifierHash,
        actorId=auditRecord.actorId,
        action=auditRecord.action,
        scope=auditRecord.scope,
        outcome=auditRecord.outcome,
        createdAt=auditRecord.createdAt,
        eventHash=auditRecord.eventHash,
    )
