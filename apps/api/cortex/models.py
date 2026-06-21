"""SQLAlchemy models for the security and retention relationships used by Cortex."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base metadata used by Alembic and SQLAlchemy repositories."""


class TraceMemory(Base):
    """Hold sensitive execution payloads under the shorter trace retention policy."""

    __tablename__ = "trace_memory"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    enterpriseId: Mapped[UUID] = mapped_column(
        "enterprise_id", PostgresUUID(as_uuid=True), nullable=False
    )
    actorId: Mapped[str] = mapped_column("actor_id", Text, nullable=False)
    rawQuery: Mapped[str] = mapped_column("raw_query", Text, nullable=False)
    rawResponse: Mapped[str | None] = mapped_column("raw_response", Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    createdAt: Mapped[datetime] = mapped_column("created_at", DateTime(timezone=True))
    rawContentExpiresAt: Mapped[datetime] = mapped_column(
        "raw_content_expires_at", DateTime(timezone=True)
    )
    expiresAt: Mapped[datetime] = mapped_column("expires_at", DateTime(timezone=True))


class AuditLog(Base):
    """Retain content-free evidence that an action occurred after its trace is purged."""

    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    enterpriseId: Mapped[UUID] = mapped_column(
        "enterprise_id", PostgresUUID(as_uuid=True), nullable=False
    )
    traceMemoryId: Mapped[UUID | None] = mapped_column(
        "trace_memory_id",
        PostgresUUID(as_uuid=True),
        ForeignKey("trace_memory.id", ondelete="SET NULL"),
        nullable=True,
    )
    traceIdentifierHash: Mapped[bytes] = mapped_column(
        "trace_identifier_hash", LargeBinary(32), nullable=False
    )
    actorId: Mapped[str] = mapped_column("actor_id", Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pipelineVersion: Mapped[int | None] = mapped_column("pipeline_version", Integer)
    modelVersions: Mapped[dict[str, str]] = mapped_column("model_versions", JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    eventPayload: Mapped[dict[str, Any]] = mapped_column("event_payload", JSONB, nullable=False)
    eventHash: Mapped[bytes] = mapped_column("event_hash", LargeBinary(32), nullable=False)
    createdAt: Mapped[datetime] = mapped_column("created_at", DateTime(timezone=True))
    expiresAt: Mapped[datetime] = mapped_column("expires_at", DateTime(timezone=True))


class Chunk(Base):
    """Represent an idempotent, immutable chunk row."""

    __tablename__ = "chunk"

    id: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    enterpriseId: Mapped[UUID] = mapped_column(
        "enterprise_id", PostgresUUID(as_uuid=True), nullable=False, index=True
    )
    documentVersionId: Mapped[UUID] = mapped_column(
        "document_version_id", PostgresUUID(as_uuid=True), nullable=False, index=True
    )
    structuralLocator: Mapped[str] = mapped_column("structural_locator", Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    normalizedContent: Mapped[str] = mapped_column("normalized_content", Text, nullable=False)
    chunkerConfigHash: Mapped[bytes] = mapped_column(
        "chunker_config_hash", LargeBinary(32), nullable=False
    )


class Document(Base):
    """Represent one enterprise source record with a stable fingerprint."""

    __tablename__ = "document"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    enterpriseId: Mapped[UUID] = mapped_column(
        "enterprise_id", PostgresUUID(as_uuid=True), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    sourceUri: Mapped[str] = mapped_column("source_uri", Text, nullable=False)
    sourceFingerprint: Mapped[bytes] = mapped_column(
        "source_fingerprint",
        LargeBinary,
        nullable=False,
    )


class DocumentVersion(Base):
    """Represent one immutable version of a document and its freshness metadata."""

    __tablename__ = "document_version"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    enterpriseId: Mapped[UUID] = mapped_column(
        "enterprise_id", PostgresUUID(as_uuid=True), nullable=False
    )
    documentId: Mapped[UUID] = mapped_column(
        "document_id",
        PostgresUUID(as_uuid=True),
        nullable=False,
    )
    versionHash: Mapped[bytes] = mapped_column("version_hash", LargeBinary(32), nullable=False)
    versionLabel: Mapped[str] = mapped_column("version_label", Text, nullable=False)
    parserVersion: Mapped[str] = mapped_column("parser_version", Text, nullable=False)
    sourceAuthority: Mapped[float] = mapped_column("source_authority", Float, nullable=False)
    publishedAt: Mapped[datetime | None] = mapped_column("published_at", DateTime(timezone=True))


class DurableJob(Base):
    """Represent a retryable unit of worker work with an idempotency key."""

    __tablename__ = "durable_job"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    enterpriseId: Mapped[UUID] = mapped_column(
        "enterprise_id", PostgresUUID(as_uuid=True), nullable=False
    )
    jobType: Mapped[str] = mapped_column("job_type", String(80), nullable=False)
    idempotencyKey: Mapped[str] = mapped_column("idempotency_key", String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lastError: Mapped[str | None] = mapped_column("last_error", Text)
