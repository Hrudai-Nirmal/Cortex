"""Object storage abstraction with a traversal-safe offline filesystem implementation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from cortex.errors import InputValidationError, ProviderOperationError


class ObjectStorage(Protocol):
    """Define immutable source-object operations independent of storage vendor."""

    async def putObject(self, objectKey: str, content: bytes) -> None:
        """Store bytes under a validated deployment-local object key."""
        ...

    async def getObject(self, objectKey: str) -> bytes:
        """Read bytes without returning an implicit empty fallback."""
        ...

    async def deleteObject(self, objectKey: str) -> None:
        """Delete one object idempotently during source purge."""
        ...


class LocalObjectStorage:
    """Store offline development objects beneath one configured root directory."""

    def __init__(self, rootPath: Path) -> None:
        self.rootPath = rootPath.resolve()

    def _resolveObjectPath(self, objectKey: str) -> Path:
        normalizedKey = objectKey.strip().lstrip("/")
        if not normalizedKey:
            raise InputValidationError("objectKey cannot be empty")
        objectPath = (self.rootPath / normalizedKey).resolve()
        if self.rootPath not in objectPath.parents:
            raise InputValidationError("objectKey cannot escape the storage root")
        return objectPath

    async def putObject(self, objectKey: str, content: bytes) -> None:
        """Create parent directories and atomically replace local object bytes."""
        if not content:
            raise InputValidationError("object content cannot be empty")
        objectPath = self._resolveObjectPath(objectKey)
        temporaryPath = objectPath.with_suffix(f"{objectPath.suffix}.partial")
        try:
            await asyncio.to_thread(objectPath.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(temporaryPath.write_bytes, content)
            await asyncio.to_thread(temporaryPath.replace, objectPath)
        except OSError as error:
            raise ProviderOperationError(f"failed to store object: {objectKey}") from error

    async def getObject(self, objectKey: str) -> bytes:
        """Read an existing local object or report its absence explicitly."""
        objectPath = self._resolveObjectPath(objectKey)
        try:
            return await asyncio.to_thread(objectPath.read_bytes)
        except OSError as error:
            raise ProviderOperationError(f"failed to read object: {objectKey}") from error

    async def deleteObject(self, objectKey: str) -> None:
        """Delete an existing object without treating absence as successful state."""
        objectPath = self._resolveObjectPath(objectKey)
        try:
            await asyncio.to_thread(objectPath.unlink)
        except FileNotFoundError:
            return
        except OSError as error:
            raise ProviderOperationError(f"failed to delete object: {objectKey}") from error
