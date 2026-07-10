import { describe, it, expect } from 'vitest'
import { VoiceSession } from './voice'

describe('VoiceSession event dispatch', () => {
  it('parses server JSON frames to typed listeners', () => {
    const vs = new VoiceSession({ learnerId: 'a' })
    const seen: string[] = []
    vs.on('transcript', (e) => seen.push(`t:${e.role}:${e.text}`))
    vs.on('token', (e) => seen.push(`k:${e.text}`))
    vs.on('turn_done', () => seen.push('done'))

    // drive the private message handler with canned frames
    const handle = (vs as any).handleMessage.bind(vs)
    handle({ data: JSON.stringify({ type: 'transcript', role: 'user', text: 'hi' }) })
    handle({ data: JSON.stringify({ type: 'token', text: 'He' }) })
    handle({ data: JSON.stringify({ type: 'turn_done' }) })

    expect(seen).toEqual(['t:user:hi', 'k:He', 'done'])
  })
})
