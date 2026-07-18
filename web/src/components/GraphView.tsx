import { useMemo } from 'react'
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Node as RFNode,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { graphToFlow } from '../graphToFlow'
import { EngramNode } from './EngramNode'
import type { GraphNode, GraphResponse } from '../types'

const nodeTypes = { engram: EngramNode }

function miniColor(n: RFNode): string {
  const t = (n.data as { type?: string })?.type
  if (t === 'concept') return '#6366f1'
  if (t === 'preference') return '#10b981'
  if (t === 'goal') return '#f59e0b'
  return '#a1a1aa'
}

export function GraphView({
  graph,
  flashIds,
  onSelect,
  highlightIds,
}: {
  graph: GraphResponse
  flashIds: Set<string>
  onSelect: (n: GraphNode) => void
  highlightIds?: Set<string>
}) {
  const { nodes, edges } = useMemo(() => graphToFlow(graph), [graph])

  if (graph.nodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <div className="grid h-12 w-12 place-items-center rounded-full bg-zinc-100 text-xl text-zinc-300">
          ◍
        </div>
        <p className="text-sm font-medium text-zinc-500">No memory yet</p>
        <p className="max-w-xs text-xs text-zinc-400">
          Chat with the tutor, then hit <span className="font-medium text-zinc-500">Consolidate</span> to
          watch the knowledge graph grow.
        </p>
      </div>
    )
  }

  const hl = highlightIds && highlightIds.size > 0 ? highlightIds : null
  const styled = nodes.map((n) => {
    const classes = []
    if (flashIds.has(n.id)) classes.push('engram-node-flash')
    if (hl) classes.push(hl.has(n.id) ? 'engram-node-highlight' : 'engram-node-dim')
    return classes.length ? { ...n, className: classes.join(' ') } : n
  })
  return (
    <ReactFlow
      nodes={styled}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.25 }}
      minZoom={0.2}
      onNodeClick={(_, n: RFNode) => onSelect((n.data as { node: GraphNode }).node)}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#e4e4e7" />
      <MiniMap
        pannable
        nodeColor={miniColor}
        nodeStrokeWidth={0}
        maskColor="rgba(244,244,245,0.7)"
        className="!rounded-lg !border !border-zinc-200 !bg-white !shadow-sm"
      />
      <Controls
        showInteractive={false}
        className="!overflow-hidden !rounded-lg !border !border-zinc-200 !shadow-sm"
      />
    </ReactFlow>
  )
}
