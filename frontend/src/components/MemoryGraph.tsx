import { useMemo } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { GraphView } from "../lib/types";
import { computeLayout } from "../lib/layout";
import { edgeStyle } from "../lib/visual";
import MemoryNode, { type MemoryNodeData } from "./MemoryNode";

const nodeTypes = { memory: MemoryNode };

interface Props {
  graph: GraphView;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

export default function MemoryGraph({ graph, selectedId, onSelect }: Props) {
  // Recompute layout only when the set of nodes/edges actually changes.
  const layoutKey = useMemo(
    () =>
      graph.nodes.map((n) => n.id).join(",") +
      "|" +
      graph.edges.map((e) => e.id).join(","),
    [graph],
  );

  const positions = useMemo(
    () => computeLayout(graph.nodes, graph.edges),
    // layoutKey captures the structural identity we care about.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layoutKey],
  );

  const rfNodes: Node<MemoryNodeData>[] = useMemo(
    () =>
      graph.nodes.map((n) => {
        const p = positions.get(n.id) ?? { x: 0, y: 0 };
        return {
          id: n.id,
          type: "memory",
          position: p,
          data: { node: n, selected: n.id === selectedId },
          draggable: true,
        };
      }),
    [graph.nodes, positions, selectedId],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      graph.edges.map((e) => {
        const s = edgeStyle(e.type, e.weight);
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          style: {
            stroke: "#475569",
            strokeWidth: s.width,
            strokeDasharray: s.dash,
          },
          markerEnd:
            e.type === "prerequisite"
              ? { type: MarkerType.ArrowClosed, color: "#475569" }
              : undefined,
          label: e.type,
          labelStyle: { fontSize: 9, fill: "#64748b" },
          labelBgStyle: { fill: "rgba(255,255,255,0.7)" },
          labelBgPadding: [2, 1] as [number, number],
        };
      }),
    [graph.edges],
  );

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      onNodeClick={(_e, node) => onSelect(node.id)}
      onPaneClick={() => onSelect(null)}
      fitView
      minZoom={0.2}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background />
      <Controls />
    </ReactFlow>
  );
}
