"""Deterministic normalization and chunk identifiers for retry-safe ingestion."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from cortex.errors import InputValidationError

WHITESPACE_PATTERN = re.compile(r"[ \t\f\v]+")
PARAGRAPH_PATTERN = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class ChunkerConfig:
    """Define every setting that can alter chunk boundaries or content."""

    name: str = "paragraph-window"
    implementationVersion: str = "1.0.0"
    tokenizer: str = "unicode-codepoint"
    size: int = 900
    overlap: int = 120
    separators: tuple[str, ...] = ("\n\n", "\n", ". ", " ")
    normalization: str = "nfkc-whitespace-v1"

    def validate(self) -> None:
        """Reject chunking configurations that cannot make forward progress."""
        if not self.name.strip() or not self.implementationVersion.strip():
            raise InputValidationError("chunker name and version are required")
        if self.size < 64:
            raise InputValidationError("chunk size must be at least 64 characters")
        if self.overlap < 0 or self.overlap >= self.size:
            raise InputValidationError("chunk overlap must be non-negative and smaller than size")
        if not self.separators or any(not separator for separator in self.separators):
            raise InputValidationError("at least one non-empty separator is required")

    def toCanonicalMapping(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation for hashing."""
        self.validate()
        return {
            "implementationVersion": self.implementationVersion,
            "name": self.name,
            "normalization": self.normalization,
            "overlap": self.overlap,
            "separators": list(self.separators),
            "size": self.size,
            "tokenizer": self.tokenizer,
        }


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """Represent a deterministic chunk ready for repository upsert."""

    id: bytes
    ordinal: int
    structuralLocator: str
    normalizedContent: str
    chunkerConfigHash: bytes

    @property
    def idHex(self) -> str:
        """Expose the binary primary key in API-safe hexadecimal form."""
        return self.id.hex()


def normalizeContent(content: str) -> str:
    """Normalize inconsequential whitespace without destroying paragraph boundaries."""
    if not isinstance(content, str) or not content.strip():
        raise InputValidationError("document content cannot be empty")
    normalizedLines = [WHITESPACE_PATTERN.sub(" ", line).strip() for line in content.splitlines()]
    normalizedContent = "\n".join(normalizedLines).strip()
    return PARAGRAPH_PATTERN.sub("\n\n", normalizedContent)


def serializeCanonicalJson(value: Any) -> bytes:
    """Serialize JSON deterministically so configuration hashes survive restarts."""
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def calculateChunkerConfigHash(config: ChunkerConfig) -> bytes:
    """Calculate the SHA-256 digest of every boundary-affecting setting."""
    return hashlib.sha256(serializeCanonicalJson(config.toCanonicalMapping())).digest()


def encodeLengthDelimited(parts: list[bytes]) -> bytes:
    """Encode hash inputs without ambiguous concatenation boundaries."""
    encodedParts = bytearray()
    for part in parts:
        encodedParts.extend(len(part).to_bytes(8, byteorder="big", signed=False))
        encodedParts.extend(part)
    return bytes(encodedParts)


def calculateChunkId(
    enterpriseId: UUID,
    documentVersionHash: bytes,
    structuralLocator: str,
    normalizedChunkContent: str,
    chunkerConfigHash: bytes,
) -> bytes:
    """Calculate a stable 32-byte primary key for one chunk occurrence."""
    if len(documentVersionHash) != 32 or len(chunkerConfigHash) != 32:
        raise InputValidationError("version and chunker hashes must each contain 32 bytes")
    if not structuralLocator.strip() or not normalizedChunkContent.strip():
        raise InputValidationError("chunk locator and content cannot be empty")
    canonicalInput = encodeLengthDelimited(
        [
            enterpriseId.bytes,
            documentVersionHash,
            structuralLocator.encode("utf-8"),
            normalizedChunkContent.encode("utf-8"),
            chunkerConfigHash,
        ]
    )
    return hashlib.sha256(canonicalInput).digest()


def splitDocument(
    enterpriseId: UUID,
    documentVersionHash: bytes,
    content: str,
    config: ChunkerConfig,
) -> list[ChunkRecord]:
    """Split normalized content into deterministic overlapping character windows."""
    config.validate()
    normalizedDocument = normalizeContent(content)
    configHash = calculateChunkerConfigHash(config)
    stepSize = config.size - config.overlap
    chunks: list[ChunkRecord] = []
    startOffset = 0
    ordinal = 0
    while startOffset < len(normalizedDocument):
        endOffset = min(startOffset + config.size, len(normalizedDocument))
        chunkContent = normalizedDocument[startOffset:endOffset].strip()
        if chunkContent:
            structuralLocator = f"char:{startOffset}-{endOffset}:ordinal:{ordinal}"
            chunkId = calculateChunkId(
                enterpriseId,
                documentVersionHash,
                structuralLocator,
                chunkContent,
                configHash,
            )
            chunks.append(
                ChunkRecord(
                    id=chunkId,
                    ordinal=ordinal,
                    structuralLocator=structuralLocator,
                    normalizedContent=chunkContent,
                    chunkerConfigHash=configHash,
                )
            )
            ordinal += 1
        startOffset += stepSize
    if not chunks:
        raise InputValidationError("normalization produced no chunks")
    return chunks


def calculateDocumentVersionHash(content: str, versionLabel: str, documentId: UUID) -> bytes:
    """Bind stable document identity and source version to normalized document bytes."""
    if not versionLabel.strip():
        raise InputValidationError("versionLabel cannot be empty")
    normalizedDocument = normalizeContent(content)
    return hashlib.sha256(
        encodeLengthDelimited(
            [documentId.bytes, versionLabel.encode("utf-8"), normalizedDocument.encode("utf-8")]
        )
    ).digest()
