import { Handle, Position } from "@xyflow/react";
import type { Node, NodeProps } from "@xyflow/react";
import type { GraphNode } from "../types";
import { masteryColor, masteryDiameter, salienceOpacity } from "../format";

export type MemoryFlowNode = Node<{ memory: GraphNode }, "memory">;

const TYPE_BADGE: Record<string, { label: string; className: string }> = {
  concept: { label: "concept", className: "badge badge-concept" },
  preference: { label: "preference", className: "badge badge-preference" },
  goal: { label: "goal", className: "badge badge-goal" },
};

export default function MemoryNode({ data, selected }: NodeProps<MemoryFlowNode>) {
  const m = data.memory;
  const diameter = masteryDiameter(m.mastery);
  const color = masteryColor(m.mastery);
  const opacity = salienceOpacity(m.salience);
  const forgotten = m.forgotten_at != null;
  const badge = TYPE_BADGE[m.type] ?? { label: m.type, className: "badge" };

  return (
    <div
      className={`memory-node${selected ? " memory-node-selected" : ""}${forgotten ? " memory-node-forgotten" : ""}`}
      style={{ opacity: forgotten ? Math.min(opacity, 0.35) : opacity }}
      title={m.summary ?? m.label}
    >
      <span className={badge.className}>{badge.label}</span>
      <div
        className="memory-node-circle"
        style={{
          width: diameter,
          height: diameter,
          background: color,
          borderStyle: forgotten ? "dashed" : "solid",
        }}
      />
      <div className="memory-node-label">{m.label}</div>
      <Handle type="target" position={Position.Top} className="memory-node-handle" />
      <Handle type="source" position={Position.Bottom} className="memory-node-handle" />
    </div>
  );
}
