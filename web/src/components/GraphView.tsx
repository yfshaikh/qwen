import { useMemo } from 'react'
import ReactFlow, { Background, Controls, type Node as RFNode } from 'reactflow'
import 'reactflow/dist/style.css'
import { graphToFlow } from '../graphToFlow'
import type { GraphNode, GraphResponse } from '../types'

export function GraphView({
  graph,
  flashIds,
  onSelect,
}: {
  graph: GraphResponse
  flashIds: Set<string>
  onSelect: (n: GraphNode) => void
}) {
  const { nodes, edges } = useMemo(() => graphToFlow(graph), [graph])
  if (graph.nodes.length === 0) {
    return <div className="graph-empty">Chat, then Consolidate to grow memory.</div>
  }
  const styled = nodes.map((n) => (flashIds.has(n.id) ? { ...n, className: 'flash' } : n))
  return (
    <ReactFlow
      nodes={styled}
      edges={edges}
      fitView
      onNodeClick={(_, n: RFNode) => onSelect((n.data as { node: GraphNode }).node)}
    >
      <Background />
      <Controls />
    </ReactFlow>
  )
}
