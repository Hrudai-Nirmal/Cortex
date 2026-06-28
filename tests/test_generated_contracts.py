"""Generated frontend contracts should stay aligned with the packaged API boundary."""

from __future__ import annotations

from pathlib import Path


def testGeneratedApiContractIncludesExternalChatFacade() -> None:
    """The generated web contract should expose the replaceable chat facade and metadata."""
    generatedTypesText = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "web"
        / "src"
        / "generated"
        / "cortex-api.ts"
    ).read_text(encoding="utf-8")
    assert '"/v1/chat/completions"' in generatedTypesText
    assert '"/v1/chat/contracts/v1"' in generatedTypesText
    assert "ChatCompletionResponseSchema" in generatedTypesText
    assert "ExternalQueryContractDescriptorSchema" in generatedTypesText
    assert "ExternalQueryMetadataSchema" in generatedTypesText
    assert "contractVersion: \"v1\";" in generatedTypesText
    assert "traceEventsPath: string;" in generatedTypesText
    assert "requestOptions:" in generatedTypesText
    assert "userMessageSelectionPolicy: \"last-non-empty-user-message\";" in generatedTypesText
    assert "querySurfaceMode: \"bundled\" | \"external\";" in generatedTypesText
    assert "bundledQueryUiAvailable: boolean;" in generatedTypesText
    assert "requestSchemaPath: string;" in generatedTypesText
    assert "responseSchemaPath: string;" in generatedTypesText
    assert "employeeSafeExtensionFields: string[];" in generatedTypesText
    assert "operatorOnlyExtensionFields: string[];" in generatedTypesText
    assert "errorStatuses:" in generatedTypesText
    assert "responseHeaders: string[];" in generatedTypesText
    assert '"/v1/chat/contracts/v1/schemas/request"' in generatedTypesText
    assert '"/v1/chat/contracts/v1/schemas/response"' in generatedTypesText
    assert "TraceSummaryResponse" in generatedTypesText
    assert "RetrievedEvidenceSchema" in generatedTypesText
    assert "claims: components[\"schemas\"][\"ClaimSchema\"][];" in generatedTypesText
