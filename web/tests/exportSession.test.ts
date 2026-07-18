import { describe, expect, it } from 'vitest'
import { buildSessionExport } from '../src/exportSession'

describe('buildSessionExport', () => {
  it('captures messages, keeper, and graph', () => {
    const out = buildSessionExport({
      learner: 'demo-1',
      turns: [
        { role: 'user', content: 'q' },
        { role: 'assistant', content: 'a' },
      ],
      report: null,
      audit: [{ id: '1', op: 'extract', rationale: null, model: null, tokens: null, cost: null, ts: 't' }],
      graph: { nodes: [], edges: [] },
      now: '2026-06-25T00:00:00Z',
    })
    expect(out.learner).toBe('demo-1')
    expect(out.exportedAt).toBe('2026-06-25T00:00:00Z')
    expect(out.messages[1]).toMatchObject({ role: 'assistant', content: 'a' })
    expect(out.keeper.audit[0].op).toBe('extract')
    expect(out.graph).toEqual({ nodes: [], edges: [] })
  })
})
