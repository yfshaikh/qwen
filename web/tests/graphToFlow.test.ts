import { describe, expect, it } from 'vitest'
import { graphToFlow } from '../src/graphToFlow'
import type { GraphResponse } from '../src/types'

const G: GraphResponse = {
  nodes: [
    { id: 'a', label: 'Limits', type: 'concept', summary: null, mastery: 0.5,
      confidence: null, salience: null, evidence: [] },
    { id: 'b', label: 'Continuity', type: 'goal', summary: null, mastery: null,
      confidence: null, salience: null, evidence: [] },
  ],
  edges: [{ id: 'e1', source: 'a', target: 'b', type: 'prerequisite', weight: 1 }],
}

describe('graphToFlow', () => {
  it('maps nodes with label under data.label and a dagre position', () => {
    const { nodes } = graphToFlow(G)
    const a = nodes.find((n) => n.id === 'a')!
    expect(a.data.label).toBe('Limits')
    expect((a.data as { node: { id: string } }).node.id).toBe('a')
    expect(typeof a.position.x).toBe('number')
    expect(typeof a.position.y).toBe('number')
  })

  it('positions distinct nodes at distinct coordinates', () => {
    const { nodes } = graphToFlow(G)
    const [a, b] = nodes
    expect(a.position.x !== b.position.x || a.position.y !== b.position.y).toBe(true)
  })

  it('maps edges with source/target/label', () => {
    const { edges } = graphToFlow(G)
    expect(edges[0]).toMatchObject({ id: 'e1', source: 'a', target: 'b', label: 'prerequisite' })
  })

  it('uses the custom node renderer and carries the type (for coloring)', () => {
    const { nodes } = graphToFlow(G)
    const a = nodes.find((n) => n.id === 'a')!
    expect(a.type).toBe('engram')
    expect((a.data as { type: string }).type).toBe('concept')
  })
})
