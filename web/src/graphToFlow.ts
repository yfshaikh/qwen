import dagre from 'dagre'
import { MarkerType, type Edge, type Node } from 'reactflow'
import type { GraphResponse } from './types'

const W = 180
const H = 96

// Edge styling by relation type. Direction is carried by the arrowhead;
// relates_to is undirected noise, so it gets no arrow and stays faint.
const EDGE_STYLE: Record<string, Partial<Edge>> = {
  prerequisite: {
    animated: true,
    style: { stroke: '#6366f1', strokeDasharray: '5 4', strokeWidth: 1.5, opacity: 0.55 },
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: '#6366f1' },
  },
  part_of: {
    style: { stroke: '#10b981', strokeDasharray: '2 3', strokeWidth: 1.25, opacity: 0.5 },
    markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: '#10b981' },
  },
  relates_to: {
    style: { stroke: '#a1a1aa', strokeDasharray: '1 4', strokeWidth: 1, opacity: 0.35 },
  },
}

export function graphToFlow(g: GraphResponse): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = g.nodes.map((n) => ({
    id: n.id,
    type: 'engram',
    position: { x: 0, y: 0 },
    data: { label: n.label, type: n.type, mastery: n.mastery, node: n },
  }))
  const edges: Edge[] = g.edges.map((e) => ({
    id: e.id ?? `${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    type: 'smoothstep',
    ...(EDGE_STYLE[e.type] ?? EDGE_STYLE.relates_to),
  }))
  return { nodes: layout(nodes, edges), edges }
}

function layout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', nodesep: 70, ranksep: 90 })
  nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }))
  edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)
  return nodes.map((n) => {
    const p = g.node(n.id)
    return { ...n, position: { x: p.x - W / 2, y: p.y - H / 2 } }
  })
}
