"""Verify typed pipeline DAG security and reranker invariants."""

import pytest
from cortex.domain.pipeline import (
    ComponentCapability,
    PipelineDefinition,
    PipelineEdge,
    PipelineNode,
)
from cortex.errors import PipelineValidationError


def buildNode(nodeId: str, capabilities: set[ComponentCapability]) -> PipelineNode:
    """Create a minimal valid test component."""
    return PipelineNode(
        id=nodeId,
        componentType="test",
        componentVersion="1.0.0",
        capabilities=capabilities,
        inputSchema="cortex.input.v1",
        outputSchema="cortex.output.v1",
    )


def testPipelineRequiresNonRemovableCapabilities() -> None:
    """Publishing cannot omit authorization, provenance, audit, or validation."""
    with pytest.raises(PipelineValidationError, match="mandatory capabilities"):
        PipelineDefinition(
            name="unsafe", nodes=[buildNode("retrieve", {ComponentCapability.RETRIEVAL})]
        )


def testPipelineRejectsCycles() -> None:
    """The configured component graph must remain deterministic and acyclic."""
    mandatoryCapabilities = {
        ComponentCapability.AUTHORIZATION,
        ComponentCapability.PROVENANCE,
        ComponentCapability.AUDIT,
        ComponentCapability.CLAIM_VALIDATION,
    }
    with pytest.raises(PipelineValidationError, match="cycle"):
        PipelineDefinition(
            name="cycle",
            nodes=[buildNode("one", mandatoryCapabilities), buildNode("two", set())],
            edges=[
                PipelineEdge(sourceNodeId="one", targetNodeId="two"),
                PipelineEdge(sourceNodeId="two", targetNodeId="one"),
            ],
        )
