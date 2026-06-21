"""Provider-neutral model contracts with an offline Ollama-compatible implementation."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from cortex.errors import InputValidationError, ProviderOperationError

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class EmbeddingProvider(Protocol):
    """Define the replaceable embedding provider contract."""

    async def embedTexts(self, texts: list[str]) -> list[list[float]]:
        """Embed non-empty normalized strings in request order."""
        ...


class StructuredGeneratorProvider(Protocol):
    """Define bounded schema-constrained generation without autonomous tools."""

    async def generateStructured(
        self, systemPrompt: str, userPrompt: str, responseSchema: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate one JSON value conforming to the supplied schema."""
        ...


def buildDeterministicEmbedding(text: str, dimension: int = 1024) -> list[float]:
    """Create a stable token-aware embedding when a live model provider is absent."""
    if not text.strip():
        raise InputValidationError("embedding text cannot be empty")
    if dimension < 8:
        raise InputValidationError("embedding dimension must be at least 8")
    tokens = TOKEN_PATTERN.findall(text.lower())
    if not tokens:
        tokens = [text.lower()]
    embeddingValues = [0.0] * dimension
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        primaryIndex = int.from_bytes(digest[:4], byteorder="big") % dimension
        secondaryIndex = int.from_bytes(digest[4:8], byteorder="big") % dimension
        sign = 1.0 if digest[8] % 2 == 0 else -1.0
        weight = 1.0 + ((digest[9] % 31) / 100.0)
        embeddingValues[primaryIndex] += sign * weight
        embeddingValues[secondaryIndex] += (sign * weight) / 2.0
    vectorNorm = sum(value * value for value in embeddingValues) ** 0.5
    if vectorNorm == 0:
        return embeddingValues
    return [value / vectorNorm for value in embeddingValues]


class OllamaModelProvider:
    """Call local OpenAI-compatible Ollama endpoints with pinned model names."""

    def __init__(
        self,
        baseUrl: str,
        generatorModel: str,
        embeddingModel: str,
        timeoutSeconds: float = 120.0,
    ) -> None:
        normalizedBaseUrl = baseUrl.rstrip("/")
        if not normalizedBaseUrl or not generatorModel.strip() or not embeddingModel.strip():
            raise InputValidationError("model endpoint and model names cannot be empty")
        self.baseUrl = normalizedBaseUrl
        self.generatorModel = generatorModel
        self.embeddingModel = embeddingModel
        self.timeoutSeconds = timeoutSeconds

    def getBaseHost(self) -> str:
        """Return the configured endpoint host for offline-compatibility checks."""
        parsedUrl = urlparse(self.baseUrl)
        return parsedUrl.hostname or ""

    async def embedTexts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts through Ollama's OpenAI-compatible embeddings endpoint."""
        if not texts or any(not text.strip() for text in texts):
            raise InputValidationError("embedding input must contain non-empty strings")
        try:
            async with httpx.AsyncClient(timeout=self.timeoutSeconds) as client:
                response = await client.post(
                    f"{self.baseUrl}/v1/embeddings",
                    json={"model": self.embeddingModel, "input": texts},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, KeyError) as error:
            raise ProviderOperationError("local embedding request failed") from error
        embeddingRows = payload.get("data")
        if not isinstance(embeddingRows, list) or len(embeddingRows) != len(texts):
            raise ProviderOperationError("embedding provider returned an invalid row count")
        return [row["embedding"] for row in embeddingRows]

    async def generateStructured(
        self, systemPrompt: str, userPrompt: str, responseSchema: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate deterministic JSON without exposing dynamic tool definitions."""
        if not systemPrompt.strip() or not userPrompt.strip() or not responseSchema:
            raise InputValidationError("prompts and response schema are required")
        requestPayload = {
            "model": self.generatorModel,
            "messages": [
                {"role": "system", "content": systemPrompt},
                {"role": "user", "content": userPrompt},
            ],
            "temperature": 0,
            "seed": 7,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "cortex_response", "schema": responseSchema},
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeoutSeconds) as client:
                response = await client.post(
                    f"{self.baseUrl}/v1/chat/completions",
                    json=requestPayload,
                )
                response.raise_for_status()
                responsePayload = response.json()
                generatedContent = responsePayload["choices"][0]["message"]["content"]
                return httpx.Response(200, content=generatedContent).json()
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
            raise ProviderOperationError("bounded generation request failed") from error

    async def checkHealth(self) -> tuple[bool, str]:
        """Verify the local model endpoint is reachable without running a generation."""
        try:
            async with httpx.AsyncClient(timeout=min(self.timeoutSeconds, 10.0)) as client:
                response = await client.get(f"{self.baseUrl}/api/tags")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            return False, str(error)
        models = payload.get("models", [])
        availableModelNames = {
            modelEntry.get("name", "") for modelEntry in models if isinstance(modelEntry, dict)
        }
        missingModels = [
            modelName
            for modelName in (self.generatorModel, self.embeddingModel)
            if modelName not in availableModelNames
        ]
        if missingModels:
            return False, f"missing models: {', '.join(missingModels)}"
        return True, "ollama models ready"
