"""Content-free audit hashing and independent trace identity preservation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from cortex.domain.chunking import serializeCanonicalJson


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
