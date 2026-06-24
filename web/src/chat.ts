import type { SSEFrame } from './sse'
import type { SavedEvent } from './types'

export interface PendingTurn {
  role: 'user' | 'assistant'
  content: string
  recalled?: string
  saved?: SavedEvent[]
  error?: string
  done?: boolean
}

export function userTurn(text: string): PendingTurn {
  return { role: 'user', content: text }
}

export function assistantTurn(): PendingTurn {
  return { role: 'assistant', content: '' }
}

export function applyFrame(turn: PendingTurn, frame: SSEFrame): PendingTurn {
  switch (frame.event) {
    case 'context':
      return { ...turn, recalled: frame.data.text_block ?? '' }
    case 'delta':
      return { ...turn, content: turn.content + (frame.data.text ?? '') }
    case 'saved':
      return { ...turn, saved: frame.data.events ?? [] }
    case 'done':
      return { ...turn, done: true }
    case 'error':
      return { ...turn, error: frame.data.detail ?? 'error', done: true }
    default:
      return turn
  }
}
