"""Typed DAG definitions and non-removable Cortex capability validation."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from cortex.domain.chunking import serializeCanonicalJson
from cortex.errors import PipelineValidationError


class ComponentCapability(StrEnum):
    """Enumerate capabilities used by pipeline promotion validation."""

    AUTHORIZATION = "authorization"
    PROVENANCE = "provenance"
    AUDIT = "audit"
    CLAIM_VALIDATION = "claim-validation"
    INGESTION = "ingestion"
    RETRIEVAL = "retrieval"
    RERANKING = "reranking"
    GENERATION = "generation"


MANDATORY_CAPABILITIES = frozenset(
    {
        ComponentCapability.AUTHORIZATION,
        ComponentCapability.PROVENANCE,
        ComponentCapability.AUDIT,
        ComponentCapability.CLAIM_VALIDATION,
    }
)


class PipelineNode(BaseModel):
    """Describe one installed component instance in a pipeline version."""

    id: str = Field(min_length=1, max_length=80)
    componentType: str = Field(min_length=1, max_length=120)
    componentVersion: str = Field(min_length=1, max_length=80)
    capabilities: set[ComponentCapability]
    config: dict[str, Any] = Field(default_factory=dict)
    inputSchema: str = Field(min_length=1)
    outputSchema: str = Field(min_length=1)


class PipelineEdge(BaseModel):
    """Connect compatible node output and input contracts."""

    sourceNodeId: str = Field(min_length=1)
    targetNodeId: str = Field(min_length=1)


class PipelineDefinition(BaseModel):
    """Represent an immutable pipeline DAG suitable for hashing and promotion."""

    name: str = Field(min_length=1, max_length=160)
    nodes: list[PipelineNode] = Field(min_length=1)
    edges: list[PipelineEdge] = Field(default_factory=list)
    rerankTopK: int = Field(default=40, ge=30, le=50)

    @model_validator(mode="after")
    def validateGraph(self) -> PipelineDefinition:
        """Reject missing capabilities, dangling edges, and cycles."""
        nodeIds = [node.id for node in self.nodes]
        if len(nodeIds) != len(set(nodeIds)):
            raise PipelineValidationError("pipeline node IDs must be unique")
        nodeIdSet = set(nodeIds)
        for edge in self.edges:
            if edge.sourceNodeId not in nodeIdSet or edge.targetNodeId not in nodeIdSet:
                raise PipelineValidationError("pipeline edge references an unknown node")
        actualCapabilities = {capability for node in self.nodes for capability in node.capabilities}
        missingCapabilities = MANDATORY_CAPABILITIES - actualCapabilities
        if missingCapabilities:
            missingNames = ", ".join(sorted(capability.value for capability in missingCapabilities))
            raise PipelineValidationError(
                f"pipeline is missing mandatory capabilities: {missingNames}"
            )
        self._validateAcyclic(nodeIds)
        return self

    def _validateAcyclic(self, nodeIds: list[str]) -> None:
        adjacency = {nodeId: [] for nodeId in nodeIds}
        indegree = {nodeId: 0 for nodeId in nodeIds}
        for edge in self.edges:
            adjacency[edge.sourceNodeId].append(edge.targetNodeId)
            indegree[edge.targetNodeId] += 1
        readyNodes = [nodeId for nodeId, degree in indegree.items() if degree == 0]
        visitedCount = 0
        while readyNodes:
            currentNode = readyNodes.pop()
            visitedCount += 1
            for targetNode in adjacency[currentNode]:
                indegree[targetNode] -= 1
                if indegree[targetNode] == 0:
                    readyNodes.append(targetNode)
        if visitedCount != len(nodeIds):
            raise PipelineValidationError("pipeline graph cannot contain a cycle")

    def calculateDefinitionHash(self) -> bytes:
        """Return a stable digest used to deduplicate immutable versions."""
        return hashlib.sha256(serializeCanonicalJson(self.model_dump(mode="json"))).digest()
