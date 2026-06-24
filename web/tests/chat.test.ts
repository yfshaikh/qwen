import { describe, expect, it } from 'vitest'
import { applyFrame, assistantTurn } from '../src/chat'
import type { SSEFrame } from '../src/sse'

function reduce(frames: SSEFrame[]) {
  return frames.reduce(applyFrame, assistantTurn())
}

describe('applyFrame', () => {
  it('folds a full frame sequence into a turn', () => {
    const t = reduce([
      { event: 'context', data: { text_block: 'mem' } },
      { event: 'delta', data: { text: 'Hel' } },
      { event: 'delta', data: { text: 'lo' } },
      { event: 'saved', data: { events: [{ type: 'utterance', text: 'q' }] } },
      { event: 'done', data: { reply: 'Hello' } },
    ])
    expect(t.recalled).toBe('mem')
    expect(t.content).toBe('Hello')
    expect(t.saved).toEqual([{ type: 'utterance', text: 'q' }])
    expect(t.done).toBe(true)
  })

  it('records an error frame', () => {
    const t = reduce([{ event: 'error', data: { detail: 'boom' } }])
    expect(t.error).toBe('boom')
    expect(t.done).toBe(true)
  })
})
