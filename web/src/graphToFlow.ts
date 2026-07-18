import dagre from 'dagre'
import type { Edge, Node } from 'reactflow'
import type { GraphResponse } from './types'

const W = 180
const H = 96

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
    label: e.type,
    type: 'smoothstep',
    style: { stroke: '#cbd0d8', strokeWidth: 1.5 },
    labelStyle: { fill: '#71717a', fontSize: 11 },
    labelBgStyle: { fill: '#fafafa' },
    labelBgPadding: [4, 2] as [number, number],
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
