/** Interactive typed pipeline canvas for the builder surface. */

import { useCallback } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import { PipelineNode, type PipelineNodeData } from "./pipeline-node";

interface PipelineGraphProps {
  selectedNodeId: string;
  onSelectNode: (nodeId: string) => void;
}

const pipelineNodes: Node<PipelineNodeData>[] = [
  { id: "ingest", type: "pipeline", position: { x: 15, y: 60 }, data: { label: "Ingest & Normalize", sequence: 1, category: "ingestion", version: "v1.4.0", status: "healthy" } },
  { id: "scope", type: "pipeline", position: { x: 160, y: 60 }, data: { label: "Access Scope", sequence: 2, category: "security", version: "v1.0.0", status: "healthy" } },
  { id: "retrieval", type: "pipeline", position: { x: 305, y: 60 }, data: { label: "Hybrid Retrieval", sequence: 3, category: "retrieval", version: "v2.6.1", status: "healthy" } },
  { id: "rerank", type: "pipeline", position: { x: 450, y: 60 }, data: { label: "Cross-Encoder", sequence: 4, category: "reranking", version: "Top 40", status: "healthy" } },
  { id: "confidence", type: "pipeline", position: { x: 595, y: 60 }, data: { label: "Source Confidence", sequence: 5, category: "scoring", version: "v2.1.0", status: "healthy" } },
  { id: "generation", type: "pipeline", position: { x: 740, y: 60 }, data: { label: "Bounded Generation", sequence: 6, category: "generation", version: "qwen3:14b", status: "healthy" } },
  { id: "citations", type: "pipeline", position: { x: 885, y: 60 }, data: { label: "Claims & Citations", sequence: 7, category: "validation", version: "v1.3.2", status: "healthy" } },
  { id: "bm25", type: "pipeline", position: { x: 230, y: 225 }, data: { label: "BM25 Index", sequence: 3, category: "retrieval", version: "Postgres FTS", status: "healthy", isAuxiliary: true } },
  { id: "vector", type: "pipeline", position: { x: 350, y: 225 }, data: { label: "Vector Index", sequence: 3, category: "retrieval", version: "HNSW · 1024d", status: "healthy", isAuxiliary: true } },
  { id: "reranker-model", type: "pipeline", position: { x: 475, y: 225 }, data: { label: "Reranker Model", sequence: 4, category: "reranking", version: "MiniLM", status: "healthy", isAuxiliary: true } },
  { id: "abstain", type: "pipeline", position: { x: 610, y: 225 }, data: { label: "Insufficient Evidence", sequence: 5, category: "abstention", version: "No answer", status: "warning", isAuxiliary: true } },
];

const mainNodeIds = ["ingest", "scope", "retrieval", "rerank", "confidence", "generation", "citations"];
const pipelineEdges: Edge[] = [
  ...mainNodeIds.slice(0, -1).map((nodeId, index) => ({
    id: `${nodeId}-${mainNodeIds[index + 1]}`,
    source: nodeId,
    target: mainNodeIds[index + 1],
    animated: index === 2,
    style: { stroke: "#8a96a8", strokeWidth: 1.5 },
  })),
  { id: "bm25-retrieval", source: "bm25", target: "retrieval", style: { stroke: "#7199cf", strokeDasharray: "4 4" } },
  { id: "vector-retrieval", source: "vector", target: "retrieval", style: { stroke: "#7199cf", strokeDasharray: "4 4" } },
  { id: "model-rerank", source: "reranker-model", target: "rerank", style: { stroke: "#8b62cf", strokeDasharray: "4 4" } },
  { id: "confidence-abstain", source: "confidence", target: "abstain", style: { stroke: "#d38c37", strokeDasharray: "4 4" } },
];

const nodeTypes = { pipeline: PipelineNode };

/** Render the constrained graph and report node selection to the inspector. */
export function PipelineGraph({ selectedNodeId, onSelectNode }: PipelineGraphProps) {
  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => onSelectNode(node.id),
    [onSelectNode],
  );
  const selectedNodes = pipelineNodes.map((node) => ({ ...node, selected: node.id === selectedNodeId }));

  return (
    <ReactFlow
      nodes={selectedNodes}
      edges={pipelineEdges}
      nodeTypes={nodeTypes}
      onNodeClick={handleNodeClick}
      nodesDraggable={false}
      nodesConnectable={false}
      fitView
      fitViewOptions={{ padding: 0.04 }}
      minZoom={0.55}
      maxZoom={1.4}
      aria-label="Active Cortex pipeline"
    >
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#dfe5ee" />
      <Controls showInteractive={false} position="bottom-left" />
    </ReactFlow>
  );
}
