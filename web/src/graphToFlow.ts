import type { CSSProperties } from 'react'
import dagre from 'dagre'
import type { Edge, Node } from 'reactflow'
import type { GraphNode, GraphResponse } from './types'

const TYPE_COLOR: Record<string, string> = {
  concept: '#4f8cff',
  preference: '#22c55e',
  goal: '#f59e0b',
}
const W = 160
const H = 48

export function graphToFlow(g: GraphResponse): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = g.nodes.map((n) => ({
    id: n.id,
    position: { x: 0, y: 0 },
    data: { label: n.label, type: n.type, mastery: n.mastery, node: n },
    style: nodeStyle(n),
  }))
  const edges: Edge[] = g.edges.map((e) => ({
    id: e.id ?? `${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    label: e.type,
  }))
  return { nodes: layout(nodes, edges), edges }
}

function nodeStyle(n: GraphNode): CSSProperties {
  const m = n.mastery ?? 0
  return {
    background: TYPE_COLOR[n.type] ?? '#888',
    color: '#fff',
    borderRadius: 8,
    padding: 8,
    width: W,
    border: `${1 + Math.round(m * 3)}px solid rgba(255,255,255,0.85)`,
    opacity: n.mastery == null ? 0.6 : 1,
  }
}

function layout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 80 })
  nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }))
  edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)
  return nodes.map((n) => {
    const p = g.node(n.id)
    return { ...n, position: { x: p.x - W / 2, y: p.y - H / 2 } }
  })
}
