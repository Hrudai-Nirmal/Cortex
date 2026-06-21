/** Custom React Flow node mirrors the selected graph-first visual target. */

import { CheckCircle, LockKey, WarningCircle } from "@phosphor-icons/react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

export interface PipelineNodeData extends Record<string, unknown> {
  label: string;
  sequence: number;
  category: string;
  version: string;
  status: "healthy" | "warning";
  isAuxiliary?: boolean;
}

/** Render one typed pipeline stage with visible health and version metadata. */
export function PipelineNode({ data, selected }: NodeProps) {
  const nodeData = data as PipelineNodeData;
  const isSecurityNode = nodeData.category === "security";
  return (
    <div className={`pipeline-node pipeline-node--${nodeData.category}${nodeData.isAuxiliary ? " pipeline-node--auxiliary" : ""}${selected ? " is-selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="pipeline-node__header">
        <span className="pipeline-node__sequence">{nodeData.sequence}</span>
        {nodeData.status === "healthy" ? (
          <CheckCircle aria-label="Healthy" size={16} weight="fill" />
        ) : (
          <WarningCircle aria-label="Warning" size={16} weight="fill" />
        )}
      </div>
      <strong>{nodeData.label}</strong>
      <span>{isSecurityNode ? <LockKey aria-hidden size={13} /> : null}{nodeData.version}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
