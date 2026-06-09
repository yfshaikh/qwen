import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { GraphNode } from "../lib/types";
import { masteryColor, masterySize, salienceOpacity, typeMeta } from "../lib/visual";

// Data carried on each React Flow node.
export interface MemoryNodeData {
  node: GraphNode;
  selected: boolean;
  [key: string]: unknown;
}

// Custom node: size+color encode mastery, opacity encodes salience,
// a corner badge encodes type (concept/preference/goal).
export default function MemoryNode({ data }: NodeProps) {
  const { node, selected } = data as MemoryNodeData;
  const size = masterySize(node.mastery);
  const color = masteryColor(node.mastery);
  const opacity = salienceOpacity(node);
  const meta = typeMeta(node.type);

  return (
    <div
      title={`${meta.label}: ${node.label}`}
      style={{ opacity, position: "relative" }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          background: color,
          border: selected ? "3px solid #111827" : `2px solid ${meta.accent}`,
          boxShadow: selected
            ? "0 0 0 4px rgba(17,24,39,0.18)"
            : "0 1px 4px rgba(0,0,0,0.3)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#fff",
          fontWeight: 700,
          fontSize: 11,
          textAlign: "center",
          padding: 4,
          boxSizing: "border-box",
          cursor: "pointer",
        }}
      >
        {/* type badge */}
        <span
          style={{
            position: "absolute",
            top: -6,
            right: -6,
            width: 18,
            height: 18,
            borderRadius: "50%",
            background: meta.accent,
            color: "#fff",
            fontSize: 10,
            lineHeight: "18px",
            textAlign: "center",
            border: "2px solid #fff",
          }}
        >
          {meta.badge}
        </span>
      </div>
      {/* label below the circle */}
      <div
        style={{
          position: "absolute",
          top: size + 2,
          left: "50%",
          transform: "translateX(-50%)",
          whiteSpace: "nowrap",
          fontSize: 11,
          fontWeight: 600,
          color: "#1f2937",
          background: "rgba(255,255,255,0.7)",
          padding: "0 3px",
          borderRadius: 3,
          pointerEvents: "none",
        }}
      >
        {node.label}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}
