"""Validated runtime settings shared by the API and worker processes."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Describe the deployable Cortex runtime profile."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CORTEX_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    authMode: Literal["fixture"] = "fixture"
    databaseUrl: str = "postgresql+asyncpg://cortex:cortex@127.0.0.1:5432/cortex"
    enterpriseId: UUID = UUID("00000000-0000-0000-0000-000000000001")
    devMode: bool = True
    requiredAccelerator: Literal["auto", "cpu", "mps", "cuda"] = "mps"
    oidcIssuerUrl: str = "https://cortex.local/oidc"
    oidcAudience: str = "cortex"
    ollamaBaseUrl: str = "http://127.0.0.1:11434"
    generatorModel: str = "qwen3:14b"
    embeddingModel: str = "qwen3-embedding:0.6b"
    objectStorageRoot: str = ".cortex-data/object-storage"
    pipelineVersion: int = Field(default=3, ge=1)
    retrievalCandidateLimit: int = Field(default=120, ge=20, le=500)
    rerankTopK: int = Field(default=40, ge=30, le=50)
    sourceConfidenceThreshold: float = Field(default=0.58, ge=0.0, le=1.0)
    queryContentRetentionDays: int = Field(default=30, ge=1)
    traceRetentionDays: int = Field(default=90, ge=1)
    auditRetentionDays: int = Field(default=365, ge=1)
    maxUploadBytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    sourceFetchTimeoutSeconds: float = Field(default=10.0, ge=1.0, le=60.0)
    workerPollIntervalSeconds: float = Field(default=1.0, ge=0.1, le=30.0)
    seedPrincipalIds: tuple[str, ...] = ("group:employees", "role:builder", "role:auditor")
    websiteAllowlist: tuple[str, ...] = ("127.0.0.1", "localhost")
    allowedUploadMimeTypes: tuple[str, ...] = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/html",
        "text/plain",
        "text/markdown",
        "text/csv",
    )

    @field_validator(
        "databaseUrl",
        "oidcIssuerUrl",
        "oidcAudience",
        "ollamaBaseUrl",
        "generatorModel",
        "embeddingModel",
        "objectStorageRoot",
    )
    @classmethod
    def validateNonEmptyValue(cls, value: str) -> str:
        """Reject empty infrastructure identifiers at process startup."""
        normalizedValue = value.strip()
        if not normalizedValue:
            raise ValueError("configuration value cannot be empty")
        return normalizedValue

    @field_validator("websiteAllowlist")
    @classmethod
    def validateNormalizedSequence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Normalize configured string tuples so runtime checks stay deterministic."""
        normalizedValues = tuple(value.strip().lower() for value in values if value.strip())
        return normalizedValues

    @field_validator("allowedUploadMimeTypes")
    @classmethod
    def validateAllowedMimeTypes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require at least one accepted MIME type for upload onboarding."""
        normalizedValues = cls.validateNormalizedSequence(values)
        if not normalizedValues:
            raise ValueError("allowedUploadMimeTypes cannot be empty")
        return normalizedValues


@lru_cache(maxsize=1)
def getSettings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()
