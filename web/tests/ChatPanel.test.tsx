import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChatPanel } from '../src/components/ChatPanel'
import { applyFrame, assistantTurn, userTurn } from '../src/chat'
import type { SSEFrame } from '../src/sse'

const FRAMES: SSEFrame[] = [
  { event: 'context', data: { text_block: '' } },
  { event: 'delta', data: { text: 'A limit ' } },
  { event: 'delta', data: { text: 'is…' } },
  { event: 'saved', data: { events: [{ type: 'utterance', text: 'q' }, { type: 'tutor_explanation', text: 'A limit is…' }] } },
  { event: 'done', data: { reply: 'A limit is…' } },
]

describe('ChatPanel', () => {
  it('renders recalled memory, the assembled reply, and saved events from a frame sequence', () => {
    const assistant = FRAMES.reduce(applyFrame, assistantTurn())
    render(
      <ChatPanel
        turns={[userTurn('what is a limit?'), assistant]}
        pending={null}
        onSend={vi.fn()}
        onConsolidate={vi.fn()}
        busy={false}
      />,
    )
    expect(screen.getByText(/A limit is…/)).toBeInTheDocument()
    expect(screen.getByText(/recalled:/)).toHaveTextContent('(none yet)')
    expect(screen.getByText(/💾 saved:/)).toHaveTextContent('utterance, tutor_explanation')
  })
})
