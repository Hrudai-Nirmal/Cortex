"""Regression tests for provider-neutral model request shaping."""

from __future__ import annotations

import json
from typing import Any

import pytest

from cortex.services.model_provider import (
    OllamaModelProvider,
    STRUCTURED_GENERATION_MAX_TOKENS,
    STRUCTURED_GENERATION_REASONING_EFFORT,
)


class FakeAsyncClient:
    """Capture one outbound generation request without hitting a real model endpoint."""

    capturedJson: dict[str, Any] | None = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        return

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, excType, exc, traceback) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any]) -> "FakeResponse":
        FakeAsyncClient.capturedJson = json
        return FakeResponse({"choices": [{"message": {"content": '{"claims":[]}'}}]})


class FakeResponse:
    """Provide the minimal httpx-like response surface the provider consumes."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


@pytest.mark.asyncio
async def testGenerateStructuredDisablesReasoningAndCapsTokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep bounded-claims generation short enough for local package verification."""
    import cortex.services.model_provider as modelProviderModule

    FakeAsyncClient.capturedJson = None
    monkeypatch.setattr(modelProviderModule.httpx, "AsyncClient", FakeAsyncClient)
    provider = OllamaModelProvider(
        baseUrl="http://127.0.0.1:11434",
        generatorModel="qwen3:1.7b",
        embeddingModel="qwen3-embedding:0.6b",
    )

    responsePayload = await provider.generateStructured(
        systemPrompt="Return only supported claims.",
        userPrompt="Evidence:\nchunk_id: abc\ncontent: Retention is 90 days.",
        responseSchema={"type": "object", "properties": {"claims": {"type": "array"}}},
    )

    assert responsePayload == json.loads('{"claims":[]}')
    assert FakeAsyncClient.capturedJson is not None
    assert FakeAsyncClient.capturedJson["max_tokens"] == STRUCTURED_GENERATION_MAX_TOKENS
    assert (
        FakeAsyncClient.capturedJson["reasoning_effort"]
        == STRUCTURED_GENERATION_REASONING_EFFORT
    )
