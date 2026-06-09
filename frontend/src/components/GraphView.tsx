import { useEffect, useMemo } from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import type { Edge as FlowEdge, NodeMouseHandler } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { EdgeType, GraphResponse } from "../types";
import { layoutGraph } from "../layout";
import MemoryNode, { type MemoryFlowNode } from "./MemoryNode";

const nodeTypes = { memory: MemoryNode };

interface Props {
  graph: GraphResponse;
  /** Changes when a new learner is loaded — triggers a fit-to-view. */
  fitKey: string;
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
}

function edgeProps(type: EdgeType, weight: number | null): Partial<FlowEdge> {
  const w = weight == null ? 1 : Math.max(0.2, Math.min(3, weight));
  switch (type) {
    case "prerequisite":
      return {
        style: { stroke: "#475569", strokeWidth: 1 + w },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#475569", width: 18, height: 18 },
        label: "prereq",
      };
    case "relates_to":
      return {
        style: { stroke: "#64748b", strokeWidth: 1 + w * 0.5, strokeDasharray: "6 4" },
      };
    case "part_of":
      return {
        style: { stroke: "#94a3b8", strokeWidth: 1 },
      };
    default:
      return { style: { stroke: "#94a3b8", strokeWidth: 1 } };
  }
}

function GraphCanvas({ graph, fitKey, selectedNodeId, onSelectNode }: Props) {
  const { fitView } = useReactFlow();

  const { flowNodes, flowEdges } = useMemo(() => {
    const positions = layoutGraph(graph.nodes, graph.edges);
    const flowNodes: MemoryFlowNode[] = graph.nodes.map((n) => ({
      id: n.id,
      type: "memory" as const,
      position: positions.get(n.id) ?? { x: 0, y: 0 },
      data: { memory: n },
      selected: n.id === selectedNodeId,
    }));
    const flowEdges: FlowEdge[] = graph.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      ...edgeProps(e.type, e.weight),
    }));
    return { flowNodes, flowEdges };
  }, [graph, selectedNodeId]);

  const [nodes, setNodes, onNodesChange] = useNodesState<MemoryFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);

  useEffect(() => {
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  useEffect(() => {
    // Fit once the new learner's graph has rendered.
    const t = window.setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 60);
    return () => window.clearTimeout(t);
  }, [fitKey, fitView]);

  const onNodeClick: NodeMouseHandler = (_evt, node) => onSelectNode(node.id);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={onNodeClick}
      onPaneClick={() => onSelectNode(null)}
      nodesConnectable={false}
      fitView
      minZoom={0.1}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={24} />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable />
    </ReactFlow>
  );
}

export default function GraphView(props: Props) {
  if (props.graph.nodes.length === 0) {
    return (
      <div className="graph-empty">
        <p>No memory nodes yet for this learner.</p>
        <p className="muted">
          Seed some raw events with the Ingest helper, then press "Consolidate now" to build the
          graph.
        </p>
      </div>
    );
  }
  return (
    <ReactFlowProvider>
      <GraphCanvas {...props} />
    </ReactFlowProvider>
  );
}
